"""
Navi Server
A FastAPI backend that serves the AI agent via HTTP API.
The chat widget talks to this server, which talks to Claude and ERPNext.
"""

import os
import re
import uuid
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import anthropic
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from erpnext_client import ERPNextClient
from navi_core import (
    MODEL_NAME,
    SYSTEM_PROMPT,
    TOOLS,
    execute_tool,
    extract_actions_from_result,
    format_confirmed_action_result,
    is_affirmative,
    is_negative,
    json_result,
)

load_dotenv()

app = FastAPI(title="Navi AI Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

erp_client = ERPNextClient(
    base_url=os.getenv("ERPNEXT_URL", "http://localhost:8080"),
    username=os.getenv("ERPNEXT_USERNAME", "Administrator"),
    password=os.getenv("ERPNEXT_PASSWORD", "admin"),
)
claude_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_BASE_URL = "https://api.elevenlabs.io/v1"
DEFAULT_TTS_MODEL = os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")
DEFAULT_EN_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID_EN", "21m00Tcm4TlvDq8ikWAM")
DEFAULT_HI_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID_HI", DEFAULT_EN_VOICE_ID)
PROXY_TIMEOUT = 60
APP_BOOT_ID = uuid.uuid4().hex

# In-memory conversation state for the MVP.
conversations: dict[str, dict] = {}


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None
    language: str = "en-IN"


class ChatResponse(BaseModel):
    reply: str
    spoken_reply: str
    conversation_id: str
    actions: list = []


class TTSRequest(BaseModel):
    text: str
    language: str = "en-IN"


def get_conversation_state(conversation_id: str) -> dict:
    if conversation_id not in conversations:
        conversations[conversation_id] = {
            "messages": [],
            "pending_action": None,
            "language": "en-IN",
        }
    return conversations[conversation_id]


def build_system_prompt(language: str) -> str:
    from datetime import date
    today = date.today().isoformat()
    normalized = (language or "en-IN").lower()
    date_context = (
        f"\nToday's date is {today}. Always resolve relative date references like "
        "'yesterday', 'last week', 'this month' into actual YYYY-MM-DD values before "
        "using them in tool calls or navigate_to_page paths."
    )
    if normalized.startswith("hi"):
        return (
            SYSTEM_PROMPT
            + date_context
            + "\nAdditional rule: The user has selected Hindi as their language. You MUST reply entirely in Hindi written in Devanagari script, regardless of what language the user writes in. Never switch to English in your replies."
        )
    return (
        SYSTEM_PROMPT
        + date_context
        + "\nAdditional rule: The user has selected English as their language. You MUST reply entirely in English, regardless of what language the user writes in. Never switch to Hindi in your replies."
    )


def fallback_spoken_reply(reply: str, language: str) -> str:
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", reply)
    text = re.sub(r"\b[A-Z]{2,}(?:-[A-Z]+)*-\d{4}-\d+\b", "", text)
    text = re.sub(r"\bSKU\d+\b", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    sentences = re.split(r"(?<=[.!?])\s+", text)
    shortened = " ".join(sentences[:2]).strip()
    return shortened or text


def generate_spoken_reply(reply: str, language: str) -> str:
    language_name = "Hindi" if (language or "").lower().startswith("hi") else "English"
    prompt = (
        f"Rewrite this assistant reply as a short, natural spoken {language_name} response. "
        "Keep it warm and conversational. Remove technical IDs unless essential. "
        "Do not use bullet points. Preserve the business meaning.\n\n"
        f"Reply to rewrite:\n{reply}"
    )

    try:
        response = claude_client.messages.create(
            model=MODEL_NAME,
            max_tokens=180,
            system=(
                "You turn business chat replies into speech-friendly lines for text-to-speech. "
                "Return only the rewritten spoken line."
            ),
            messages=[{"role": "user", "content": prompt}],
        )
        spoken_text = "".join(
            block.text for block in response.content if hasattr(block, "text")
        ).strip()
        return spoken_text or fallback_spoken_reply(reply, language)
    except Exception:
        return fallback_spoken_reply(reply, language)


def format_confirmed_action_result_for_language(result: dict, language: str) -> str:
    is_hindi = (language or "").lower().startswith("hi")
    if result.get("status") != "success":
        return result.get("error", "The action failed.")

    if result.get("invoice_name"):
        if is_hindi:
            return (
                f"{result.get('customer')} के लिए Sales Invoice {result['invoice_name']} बना दिया गया है। "
                f"कुल राशि {result.get('grand_total')} है। "
                "क्या आप चाहते हैं कि मैं इसे ERPNext में खोल दूँ?"
            )
        return format_confirmed_action_result(result)

    if result.get("message"):
        return result["message"]

    if result.get("customer_name"):
        if is_hindi:
            return f"Customer {result['customer_name']} सफलतापूर्वक बना दिया गया है।"
        return format_confirmed_action_result(result)

    if result.get("item_name") or result.get("item_code"):
        item_label = result.get("item_name") or result.get("item_code")
        if is_hindi:
            return f"Item {item_label} सफलतापूर्वक बना दिया गया है।"
        return format_confirmed_action_result(result)

    return format_confirmed_action_result(result)


def handle_pending_action(state: dict, user_message: str) -> tuple[str | None, str | None, list]:
    pending_action = state.get("pending_action")
    if not pending_action:
        return None, None, []

    language = state.get("language", "en-IN")
    is_hindi = language.lower().startswith("hi")

    if is_affirmative(user_message):
        confirmed_input = dict(pending_action["tool_input"])
        confirmed_input["confirmed"] = True
        result = execute_tool(pending_action["tool_name"], confirmed_input, erp_client)
        state["pending_action"] = None

        reply = format_confirmed_action_result_for_language(result, language)
        spoken_reply = generate_spoken_reply(reply, language)
        state["messages"].append({"role": "user", "content": user_message})
        state["messages"].append({"role": "assistant", "content": reply})
        return reply, spoken_reply, extract_actions_from_result(result)

    if is_negative(user_message):
        state["pending_action"] = None
        reply = "ठीक है, मैंने यह कार्रवाई रद्द कर दी है।" if is_hindi else "Okay, I canceled that action."
        spoken_reply = reply
        state["messages"].append({"role": "user", "content": user_message})
        state["messages"].append({"role": "assistant", "content": reply})
        return reply, spoken_reply, []

    reply = (
        "एक कार्रवाई पुष्टि का इंतज़ार कर रही है। आगे बढ़ने के लिए पुष्टि करें या रद्द करने के लिए मना करें।"
        if is_hindi
        else "I have a pending action waiting for confirmation. Please confirm to continue or say cancel to stop."
    )
    spoken_reply = reply
    state["messages"].append({"role": "user", "content": user_message})
    state["messages"].append({"role": "assistant", "content": reply})
    return reply, spoken_reply, []


def normalize_navigation_actions(actions: list, user_message: str) -> list:
    if not actions:
        return actions

    normalized = re.sub(r"\s+", " ", (user_message or "").strip().lower())

    def strip_query(path: str) -> str:
        return path.split("?", 1)[0]

    def is_plain_customer_list_request() -> bool:
        if "customer" not in normalized:
            return False
        if not any(token in normalized for token in {"all", "list", "show me", "open", "take me to", "go to"}):
            return False
        filtered_terms = {
            "today",
            "yesterday",
            "this week",
            "this month",
            "created",
            "creation",
            "recent",
            "latest",
            "new",
            "named",
            "called",
            "with ",
            "from ",
            "before ",
            "after ",
        }
        return not any(term in normalized for term in filtered_terms)

    def is_plain_sales_invoice_list_request() -> bool:
        if "invoice" not in normalized:
            return False
        if not any(token in normalized for token in {"all", "list", "show me", "open", "take me to", "go to"}):
            return False
        filtered_terms = {
            "today",
            "yesterday",
            "this week",
            "this month",
            "unpaid",
            "overdue",
            "paid",
            "draft",
            "recent",
            "latest",
            "customer",
            "from ",
            "before ",
            "after ",
            "between ",
            "status",
            "due",
        }
        return not any(term in normalized for term in filtered_terms)

    normalized_actions = []
    for action in actions:
        if action.get("type") != "navigate" or not action.get("path"):
            normalized_actions.append(action)
            continue

        path = action["path"]
        if path.startswith("/app/customer") and is_plain_customer_list_request():
            action = {**action, "path": "/app/customer"}
        elif path.startswith("/app/sales-invoice") and is_plain_sales_invoice_list_request():
            action = {**action, "path": "/app/sales-invoice"}
        elif "?" in path and (
            (path.startswith("/app/customer") and "all" in normalized)
            or (path.startswith("/app/sales-invoice") and "all" in normalized)
        ):
            action = {**action, "path": strip_query(path)}

        normalized_actions.append(action)

    return normalized_actions


def get_tts_config(language: str) -> tuple[str, str]:
    normalized = (language or "en-IN").lower()
    if normalized.startswith("hi"):
        return DEFAULT_HI_VOICE_ID, "hi"
    return DEFAULT_EN_VOICE_ID, "en"


def should_inject_widget(content_type: str, body: bytes) -> bool:
    if "text/html" not in (content_type or ""):
        return False
    return b"</body>" in body and b'id="navi-widget-container"' not in body


def inject_widget_script(body: bytes, request: Request) -> bytes:
    script = f"""
<script
  src="/widget.js?v={APP_BOOT_ID}"
  data-server="{request.base_url.scheme}://{request.base_url.netloc}"
  data-erpnext-origin="{request.base_url.scheme}://{request.base_url.netloc}"
  data-boot-id="{APP_BOOT_ID}"
  data-title="Navi"></script>
</body>
""".encode("utf-8")
    return body.replace(b"</body>", script, 1)


def rewrite_location_header(location: str, request: Request) -> str:
    if not location:
        return location

    upstream_origin = erp_client.base_url.rstrip("/")
    proxy_origin = f"{request.base_url.scheme}://{request.base_url.netloc}"
    if location.startswith(upstream_origin):
        return location.replace(upstream_origin, proxy_origin, 1)
    return location


def filtered_headers(headers) -> dict:
    excluded = {
        "host",
        "content-length",
        "content-encoding",
        "connection",
        "transfer-encoding",
    }
    return {key: value for key, value in headers.items() if key.lower() not in excluded}


def proxy_to_erpnext(request: Request, path: str) -> Response:
    upstream_url = urljoin(f"{erp_client.base_url}/", path.lstrip("/"))

    try:
        upstream_response = requests.request(
            method=request.method,
            url=upstream_url,
            headers=filtered_headers(request.headers),
            params=request.query_params,
            data=request._body if hasattr(request, "_body") else None,
            cookies=request.cookies,
            allow_redirects=False,
            timeout=PROXY_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"ERPNext proxy request failed: {exc}") from exc

    response_headers = {}
    for key, value in upstream_response.headers.items():
        lowered = key.lower()
        if lowered in {"content-length", "content-encoding", "transfer-encoding", "connection"}:
            continue
        if lowered == "location":
            response_headers[key] = rewrite_location_header(value, request)
        else:
            response_headers[key] = value

    body = upstream_response.content
    content_type = upstream_response.headers.get("Content-Type", "")
    if should_inject_widget(content_type, body):
        body = inject_widget_script(body, request)

    return Response(
        content=body,
        status_code=upstream_response.status_code,
        media_type=None,
        headers=response_headers,
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Main chat endpoint for the widget and demo client."""

    conversation_id = request.conversation_id or str(uuid.uuid4())
    state = get_conversation_state(conversation_id)
    state["language"] = request.language or state.get("language", "en-IN")

    pending_reply, pending_spoken_reply, pending_actions = handle_pending_action(state, request.message)
    if pending_reply is not None:
        return ChatResponse(
            reply=pending_reply,
            spoken_reply=pending_spoken_reply or pending_reply,
            conversation_id=conversation_id,
            actions=normalize_navigation_actions(pending_actions, request.message),
        )

    messages = state["messages"]
    actions = []

    messages.append({"role": "user", "content": request.message})

    response = claude_client.messages.create(
        model=MODEL_NAME,
        max_tokens=4096,
        system=build_system_prompt(state["language"]),
        tools=TOOLS,
        messages=messages,
    )

    while response.stop_reason == "tool_use":
        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue

            result = execute_tool(block.name, block.input, erp_client)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json_result(result),
                }
            )

            if result.get("status") == "confirmation_required":
                state["pending_action"] = {
                    "tool_name": block.name,
                    "tool_input": block.input,
                }
            else:
                result_actions = extract_actions_from_result(result)
                if result_actions:
                    actions = result_actions

        messages.append({"role": "user", "content": tool_results})

        response = claude_client.messages.create(
            model=MODEL_NAME,
            max_tokens=4096,
            system=build_system_prompt(state["language"]),
            tools=TOOLS,
            messages=messages,
        )

    final_text = "".join(
        block.text for block in response.content if hasattr(block, "text")
    )
    spoken_reply = generate_spoken_reply(final_text, state["language"])

    if state.get("pending_action"):
        actions = []
    actions = normalize_navigation_actions(actions, request.message)

    messages.append({"role": "assistant", "content": response.content})
    return ChatResponse(
        reply=final_text,
        spoken_reply=spoken_reply,
        conversation_id=conversation_id,
        actions=actions,
    )


@app.post("/api/tts")
async def text_to_speech(request: TTSRequest):
    """Generate spoken audio for assistant replies using ElevenLabs."""

    if not ELEVENLABS_API_KEY:
        raise HTTPException(status_code=503, detail="ELEVENLABS_API_KEY is not configured.")

    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text is required.")

    voice_id, language_code = get_tts_config(request.language)

    try:
        eleven_response = requests.post(
            f"{ELEVENLABS_BASE_URL}/text-to-speech/{voice_id}",
            params={"output_format": "mp3_44100_128"},
            headers={
                "xi-api-key": ELEVENLABS_API_KEY,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            },
            json={
                "text": text,
                "model_id": DEFAULT_TTS_MODEL,
                "language_code": language_code,
                "voice_settings": {
                    "stability": 0.45,
                    "similarity_boost": 0.75,
                },
            },
            timeout=45,
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"ElevenLabs request failed: {exc}") from exc

    if not eleven_response.ok:
        detail = eleven_response.text[:500] or "ElevenLabs synthesis failed."
        raise HTTPException(status_code=502, detail=detail)

    return Response(
        content=eleven_response.content,
        media_type="audio/mpeg",
        headers={
            "X-Voice-Provider": "elevenlabs",
            "X-ElevenLabs-Voice-Id": voice_id,
            "X-TTS-Language": language_code,
        },
    )


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "navi-agent", "boot_id": APP_BOOT_ID}


@app.get("/widget.js")
async def serve_widget():
    return FileResponse(
        "widget.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/")
async def root(request: Request):
    html = Path("test.html").read_text(encoding="utf-8")
    script_tag = (
        f'<script src="/widget.js?v={APP_BOOT_ID}" data-server="{request.base_url.scheme}://{request.base_url.netloc}" '
        f'data-erpnext-origin="{request.base_url.scheme}://{request.base_url.netloc}" '
        f'data-boot-id="{APP_BOOT_ID}" data-title="Navi"></script>'
    )
    html = re.sub(
        r'<script\s+src="/widget\.js"[^>]*></script>',
        script_tag,
        html,
        count=1,
    )
    return Response(content=html, media_type="text/html")


@app.api_route(
    "/{full_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
async def proxy_erpnext(request: Request, full_path: str):
    """Proxy ERPNext so the widget can live on the same origin as Desk pages."""

    protected_paths = {
        "",
        "widget.js",
        "api/chat",
        "api/tts",
        "api/health",
    }
    # strip query string before checking (e.g. widget.js?v=abc123)
    base_path = full_path.split("?")[0]
    if base_path in protected_paths:
        raise HTTPException(status_code=404, detail="Not Found")

    request._body = await request.body()
    return proxy_to_erpnext(request, full_path)
