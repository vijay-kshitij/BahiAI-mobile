"""
Bahi Server
A FastAPI backend that serves the AI agent via HTTP API.
The chat UI talks to this server, which talks to Claude and ERPNext.
"""

import base64
import json as _json
import logging
import os
import re
import time
import uuid
from pathlib import Path
from urllib.parse import quote

log = logging.getLogger("bahi.server")

import anthropic
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from erpnext_client import ERPNextClient
from navi_core import (
    MODEL_NAME,
    SYSTEM_PROMPT,
    TOOLS,
    execute_tool,
    format_confirmed_action_result,
    is_affirmative,
    is_negative,
    json_result,
    normalize_phone,
)

load_dotenv()

app = FastAPI(title="Bahi AI Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

erp_client = ERPNextClient(
    base_url=os.getenv("ERPNEXT_URL", "http://localhost:8080"),
    username=os.getenv("ERPNEXT_USERNAME", "Administrator"),
    password=os.getenv("ERPNEXT_PASSWORD", "admin"),
)
claude_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
SARVAM_BASE_URL = "https://api.sarvam.ai"
SARVAM_TTS_MODEL = os.getenv("SARVAM_TTS_MODEL", "bulbul:v3")
SARVAM_STT_MODEL = os.getenv("SARVAM_STT_MODEL", "saaras:v3")
SARVAM_TTS_SPEAKER = os.getenv("SARVAM_TTS_SPEAKER", "shubh")

# ── Persistent conversation store ──
CONVERSATIONS_DIR = Path(__file__).parent / "conversations"
CONVERSATIONS_DIR.mkdir(exist_ok=True)
MAX_MESSAGES_PER_CONVERSATION = 80
CONVERSATION_TTL_SECONDS = 7 * 24 * 3600  # 7 days

conversations: dict[str, dict] = {}


def _conv_path(conversation_id: str) -> Path:
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", conversation_id)
    return CONVERSATIONS_DIR / f"{safe_id}.json"


def _serialize_content(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return [
            item.model_dump() if hasattr(item, "model_dump") else item
            for item in content
        ]
    return content


def _save_conversation(conversation_id: str, state: dict):
    serialized = {
        "messages": [
            {"role": m["role"], "content": _serialize_content(m["content"])}
            for m in state["messages"][-MAX_MESSAGES_PER_CONVERSATION:]
        ],
        "pending_action": state.get("pending_action"),
        "pending_send": state.get("pending_send"),
        "language": state.get("language", "en-IN"),
        "updated_at": time.time(),
    }
    try:
        _conv_path(conversation_id).write_text(
            _json.dumps(serialized, default=str, ensure_ascii=False)
        )
    except Exception as e:
        log.warning("Failed to save conversation %s: %s", conversation_id, e)


def _load_conversation(conversation_id: str) -> dict | None:
    path = _conv_path(conversation_id)
    if not path.exists():
        return None
    try:
        data = _json.loads(path.read_text())
        age = time.time() - data.get("updated_at", 0)
        if age > CONVERSATION_TTL_SECONDS:
            path.unlink(missing_ok=True)
            return None
        return {
            "messages": data.get("messages", []),
            "pending_action": data.get("pending_action"),
            "pending_send": data.get("pending_send"),
            "language": data.get("language", "en-IN"),
        }
    except Exception as e:
        log.warning("Failed to load conversation %s: %s", conversation_id, e)
        return None


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None
    language: str = "en-IN"


class ChatResponse(BaseModel):
    reply: str
    spoken_reply: str
    conversation_id: str
    actions: list = []
    pending: dict | None = None


class TTSRequest(BaseModel):
    text: str
    language: str = "en-IN"


def get_conversation_state(conversation_id: str) -> dict:
    if conversation_id not in conversations:
        loaded = _load_conversation(conversation_id)
        if loaded:
            conversations[conversation_id] = loaded
        else:
            conversations[conversation_id] = {
                "messages": [],
                "pending_action": None,
                "pending_send": None,
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
        "using them in tool calls."
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


def fallback_spoken_reply(reply: str, _language: str) -> str:
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

    if result.get("invoice_name") and not result.get("payment_name"):
        if is_hindi:
            return (
                f"{result.get('customer')} के लिए Sales Invoice {result['invoice_name']} बना दिया गया है। "
                f"कुल राशि ₹{result.get('grand_total')} है।"
            )
        return format_confirmed_action_result(result)

    if result.get("payment_name"):
        if is_hindi:
            return (
                f"Invoice {result.get('invoice_name')} के विरुद्ध ₹{result.get('amount')} का भुगतान दर्ज हो गया। "
                f"शेष बकाया: ₹{result.get('outstanding_after', 0)}।"
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


def describe_pending_action(pending_action: dict) -> dict:
    """Build a short, structured summary of a pending tool call for UI + classifier."""
    tool_name = pending_action.get("tool_name", "")
    tool_input = pending_action.get("tool_input", {}) or {}

    if tool_name == "create_sales_invoice":
        resolved_customer = tool_input.get("_resolved_customer")
        if isinstance(resolved_customer, dict):
            customer = (
                resolved_customer.get("customer_name")
                or resolved_customer.get("name")
                or tool_input.get("customer", "")
            )
        elif isinstance(resolved_customer, str) and resolved_customer:
            customer = resolved_customer
        else:
            customer = tool_input.get("customer", "")
        items = tool_input.get("_resolved_items") or tool_input.get("items") or []
        total = 0.0
        for it in items:
            try:
                total += float(it.get("rate", 0) or 0) * float(it.get("qty", 0) or 0)
            except (TypeError, ValueError):
                continue
        return {
            "kind": "create_sales_invoice",
            "customer": customer,
            "total": total,
            "summary_en": f"Unconfirmed invoice for {customer} — \u20B9{total:,.0f}",
            "summary_hi": f"{customer} के लिए बिना पुष्टि वाली Invoice — \u20B9{total:,.0f}",
        }

    if tool_name == "record_payment":
        return {
            "kind": "record_payment",
            "summary_en": f"Unconfirmed payment for {tool_input.get('invoice_name', '')}",
            "summary_hi": f"{tool_input.get('invoice_name', '')} के लिए बिना पुष्टि वाला payment",
        }

    if tool_name == "delete_document":
        return {
            "kind": "delete_document",
            "summary_en": f"Unconfirmed deletion of {tool_input.get('name', '')}",
            "summary_hi": f"{tool_input.get('name', '')} के deletion की पुष्टि बाक़ी",
        }

    return {
        "kind": tool_name,
        "summary_en": f"Unconfirmed {tool_name}",
        "summary_hi": f"बिना पुष्टि वाला {tool_name}",
    }


def make_pending_payload(state: dict) -> dict | None:
    """The compact pending descriptor sent to the frontend for the badge."""
    pending_action = state.get("pending_action")
    if not pending_action:
        return None
    desc = describe_pending_action(pending_action)
    is_hindi = (state.get("language") or "").lower().startswith("hi")
    return {
        "kind": desc.get("kind"),
        "summary": desc.get("summary_hi" if is_hindi else "summary_en"),
    }


def classify_pending_intent(user_message: str, pending_action: dict, language: str) -> str:
    """Use Claude to decide whether the user's reply confirms, cancels,
    is unrelated, or needs clarification on a pending action.
    Falls back to the regex helpers if the LLM call fails."""
    desc = describe_pending_action(pending_action)
    summary = desc.get("summary_en", "")
    prompt = (
        f"There is a pending action awaiting the user's confirmation:\n"
        f"  {summary}\n\n"
        f"The user just replied:\n"
        f'  "{user_message}"\n\n'
        f"Classify the reply as exactly ONE of:\n"
        f"- confirm: the user agrees and wants to proceed (e.g. 'yes', 'go ahead', "
        f"'do it', 'haan kar do', 'he has created', 'create karo', 'sure')\n"
        f"- cancel: the user wants to abandon the pending action ('no', 'cancel', 'rehne do')\n"
        f"- unrelated: the user is asking about a completely different task "
        f"('show me invoices', 'list customers', 'what's my balance')\n"
        f"- clarify: the user is asking a question about the pending action itself, "
        f"or expressing uncertainty ('have you done it already?', 'wait', 'what was the total?')\n\n"
        f"Reply with ONLY one word: confirm, cancel, unrelated, or clarify."
    )

    try:
        resp = claude_client.messages.create(
            model=MODEL_NAME,
            max_tokens=10,
            system="You are a strict classifier. Output exactly one of: confirm, cancel, unrelated, clarify.",
            messages=[{"role": "user", "content": prompt}],
        )
        raw = "".join(b.text for b in resp.content if hasattr(b, "text")).strip().lower()
        for option in ("confirm", "cancel", "unrelated", "clarify"):
            if option in raw:
                return option
        return "clarify"
    except Exception as exc:
        log.warning("Pending intent classifier failed: %s", exc)
        if is_affirmative(user_message):
            return "confirm"
        if is_negative(user_message):
            return "cancel"
        return "clarify"


def handle_pending_action(state: dict, user_message: str) -> tuple[str | None, str | None, list] | None:
    """Returns (reply, spoken_reply, actions) when the message was handled by the
    pending flow. Returns None when the main LLM should run instead — either
    because there's no pending action, or because the user shifted intent and
    we released the lock. In the release case, we inject a system notice via
    state['transient_actions']."""
    pending_action = state.get("pending_action")
    if not pending_action:
        return None

    language = state.get("language", "en-IN")
    is_hindi = language.lower().startswith("hi")

    intent = classify_pending_intent(user_message, pending_action, language)

    if intent == "unrelated":
        desc = describe_pending_action(pending_action)
        summary = desc.get("summary_hi" if is_hindi else "summary_en")
        notice = (
            f"रद्द किया: {summary}." if is_hindi else f"Cancelled: {summary}."
        )
        state["pending_action"] = None
        state["pending_send"] = None
        state.setdefault("transient_actions", []).append({"type": "system", "text": notice})
        return None  # fall through to main LLM

    if intent == "clarify":
        desc = describe_pending_action(pending_action)
        if is_hindi:
            reply = (
                f"{desc.get('summary_hi')} अभी पुष्टि का इंतज़ार कर रही है। "
                "क्या मैं इसे बना दूँ या रद्द कर दूँ?"
            )
        else:
            reply = (
                f"{desc.get('summary_en')} is still waiting. "
                "Do you want me to create it, or cancel?"
            )
        state["messages"].append({"role": "user", "content": user_message})
        state["messages"].append({"role": "assistant", "content": reply})
        return reply, reply, []

    if intent == "confirm":
        confirmed_input = dict(pending_action["tool_input"])
        confirmed_input["confirmed"] = True
        tool_name = pending_action["tool_name"]
        result = execute_tool(tool_name, confirmed_input, erp_client)
        state["pending_action"] = None

        actions = extract_card_actions(result)

        # After a successful Sales Invoice create, immediately try to send it on
        # WhatsApp so the user sees a Send button right away — no extra question.
        if (
            tool_name == "create_sales_invoice"
            and result.get("status") == "success"
            and result.get("invoice_name")
        ):
            send_result = execute_tool(
                "send_invoice",
                {"invoice_name": result["invoice_name"]},
                erp_client,
            )
            if send_result.get("status") == "success":
                actions.extend(extract_card_actions(send_result))
                state["pending_send"] = None
                customer = result.get("customer", "")
                reply = (
                    (
                        f"Invoice {result['invoice_name']} बन गया है। "
                        f"{customer} को WhatsApp पर भेजने के लिए नीचे का बटन दबाएँ।"
                    )
                    if is_hindi
                    else (
                        f"Invoice {result['invoice_name']} created for {customer} — "
                        f"₹{result.get('grand_total')}. Tap the Send on WhatsApp button below."
                    )
                )
            else:
                # Usually: no phone number on file. Arm pending_send so the next
                # message that looks like a phone number is routed to send_invoice
                # directly — the LLM tends to misread bare digits as a confirmation.
                state["pending_send"] = {"invoice_name": result["invoice_name"]}
                customer = result.get("customer", "")
                reply = (
                    (
                        f"Invoice {result['invoice_name']} बन गया है। "
                        f"WhatsApp पर भेजने के लिए {customer} का नंबर चाहिए। क्या आप शेयर कर सकते हैं?"
                    )
                    if is_hindi
                    else (
                        f"Invoice {result['invoice_name']} created. "
                        f"I don't have {customer}'s WhatsApp number — what is it (with country code)?"
                    )
                )
        else:
            reply = format_confirmed_action_result_for_language(result, language)

        spoken_reply = fallback_spoken_reply(reply, language)
        state["messages"].append({"role": "user", "content": user_message})
        state["messages"].append({"role": "assistant", "content": reply})
        return reply, spoken_reply, actions

    # intent == "cancel"
    state["pending_action"] = None
    reply = "ठीक है, मैंने यह कार्रवाई रद्द कर दी है।" if is_hindi else "Okay, I canceled that action."
    spoken_reply = reply
    state["messages"].append({"role": "user", "content": user_message})
    state["messages"].append({"role": "assistant", "content": reply})
    return reply, spoken_reply, []


def handle_pending_send(state: dict, user_message: str) -> tuple[str | None, str | None, list]:
    """If we're waiting for a phone number, route a phone-like reply directly
    to send_invoice. The LLM tends to misread bare digits (e.g. "9123456789")
    as a confirmation to re-create the invoice, so we intercept server-side."""
    pending = state.get("pending_send")
    if not pending:
        return None, None, []

    phone = normalize_phone(user_message)
    language = state.get("language", "en-IN")
    is_hindi = language.lower().startswith("hi")

    if not phone:
        # Not a phone number — let the LLM handle whatever the user said.
        # Don't clear pending_send; they may provide the number next turn.
        return None, None, []

    invoice_name = pending["invoice_name"]
    result = execute_tool(
        "send_invoice",
        {"invoice_name": invoice_name, "phone": phone},
        erp_client,
    )
    state["pending_send"] = None

    if result.get("status") == "success":
        actions = extract_card_actions(result)
        customer = result.get("customer", "")
        reply = (
            f"{customer} को WhatsApp पर भेजने के लिए नीचे का बटन दबाएँ।"
            if is_hindi
            else f"Ready to send to {customer} — tap the button below."
        )
    else:
        actions = []
        reply = result.get("error") or (
            "WhatsApp भेजने में दिक्कत हुई।" if is_hindi else "Couldn't send the invoice."
        )

    spoken_reply = reply
    state["messages"].append({"role": "user", "content": user_message})
    state["messages"].append({"role": "assistant", "content": reply})
    return reply, spoken_reply, actions


def extract_card_actions(result: dict) -> list:
    """Extract structured card actions from a tool result for the UI."""
    actions = []
    if result.get("status") != "success":
        return actions

    if (
        result.get("invoice_name")
        and not result.get("payment_name")
        and result.get("action_type") != "send_invoice"
    ):
        actions.append({
            "type": "invoice-card",
            "data": {
                "name": result.get("invoice_name"),
                "customer": result.get("customer"),
                "grand_total": result.get("grand_total"),
                "outstanding_amount": result.get("outstanding_amount"),
                "posting_date": result.get("posting_date"),
                "due_date": result.get("due_date"),
                "status": result.get("invoice_status") or ("Unpaid" if result.get("outstanding_amount") else "Draft"),
            },
        })

    if result.get("payment_name"):
        actions.append({
            "type": "payment-card",
            "data": {
                "payment_name": result.get("payment_name"),
                "invoice_name": result.get("invoice_name"),
                "customer": result.get("customer"),
                "amount": result.get("amount"),
                "mode_of_payment": result.get("mode_of_payment"),
                "outstanding_after": result.get("outstanding_after"),
            },
        })

    if result.get("action") == "navigate" and result.get("path"):
        actions.append({
            "type": "navigate",
            "path": result["path"],
            "description": result.get("description", ""),
        })

    if result.get("action_type") == "send_invoice":
        invoice_name = result.get("invoice_name")
        actions.append({
            "type": "send-invoice",
            "data": {
                "invoice_name": invoice_name,
                "customer": result.get("customer") or "",
                "phone": result.get("phone"),
                "grand_total": result.get("grand_total") or 0,
                "preview_path": f"/invoice/{quote(invoice_name, safe='')}",
            },
        })

    return actions


def get_sarvam_language_code(language: str) -> str:
    normalized = (language or "en-IN").lower()
    if normalized.startswith("hi"):
        return "hi-IN"
    return "en-IN"


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Main chat endpoint."""

    conversation_id = request.conversation_id or str(uuid.uuid4())
    state = get_conversation_state(conversation_id)
    state["language"] = request.language or state.get("language", "en-IN")

    pending_result = handle_pending_action(state, request.message)
    if pending_result is not None:
        pending_reply, pending_spoken_reply, pending_actions = pending_result
        _save_conversation(conversation_id, state)
        return ChatResponse(
            reply=pending_reply,
            spoken_reply=pending_spoken_reply or pending_reply,
            conversation_id=conversation_id,
            actions=pending_actions,
            pending=make_pending_payload(state),
        )

    send_reply, send_spoken_reply, send_actions = handle_pending_send(state, request.message)
    if send_reply is not None:
        _save_conversation(conversation_id, state)
        return ChatResponse(
            reply=send_reply,
            spoken_reply=send_spoken_reply or send_reply,
            conversation_id=conversation_id,
            actions=send_actions,
            pending=make_pending_payload(state),
        )

    messages = state["messages"]

    messages.append({"role": "user", "content": request.message})

    response = claude_client.messages.create(
        model=MODEL_NAME,
        max_tokens=4096,
        system=build_system_prompt(state["language"]),
        tools=TOOLS,
        messages=messages,
    )

    actions = []

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
                    "tool_name": result.get("tool_name", block.name),
                    "tool_input": result.get("pending_input", block.input),
                }
            else:
                actions.extend(extract_card_actions(result))

        messages.append({"role": "user", "content": tool_results})

        response = claude_client.messages.create(
            model=MODEL_NAME,
            max_tokens=4096,
            system=build_system_prompt(state["language"]),
            tools=TOOLS,
            messages=messages,
        )

    # Don't show cards if there's a pending confirmation
    if state.get("pending_action"):
        actions = []

    # Drain any system notices left by handle_pending_action when it released the lock
    transient = state.pop("transient_actions", [])
    actions = transient + actions

    final_text = "".join(
        block.text for block in response.content if hasattr(block, "text")
    )
    spoken_reply = fallback_spoken_reply(final_text, state["language"])

    messages.append({"role": "assistant", "content": response.content})
    _save_conversation(conversation_id, state)
    return ChatResponse(
        reply=final_text,
        spoken_reply=spoken_reply,
        conversation_id=conversation_id,
        actions=actions,
        pending=make_pending_payload(state),
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {_json.dumps(data, default=str, ensure_ascii=False)}\n\n"


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r'(?<=[.!?।])\s+', text)
    return [p for p in parts if p.strip()]


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    """SSE streaming chat endpoint."""

    conversation_id = request.conversation_id or str(uuid.uuid4())
    state = get_conversation_state(conversation_id)
    state["language"] = request.language or state.get("language", "en-IN")

    pending_result = handle_pending_action(state, request.message)
    if pending_result is not None:
        pending_reply, pending_spoken_reply, pending_actions = pending_result
        _save_conversation(conversation_id, state)

        def pending_gen():
            yield _sse("token", {"text": pending_reply})
            for act in pending_actions:
                yield _sse("action", act)
            tts_text = fallback_spoken_reply(pending_reply, state["language"])
            if tts_text.strip():
                yield _sse("tts", {"text": tts_text, "index": 0})
            yield _sse("done", {
                "conversation_id": conversation_id,
                "pending": make_pending_payload(state),
                "full_text": pending_reply,
            })

        return StreamingResponse(pending_gen(), media_type="text/event-stream")

    send_reply, send_spoken_reply, send_actions = handle_pending_send(state, request.message)
    if send_reply is not None:
        _save_conversation(conversation_id, state)

        def send_gen():
            yield _sse("token", {"text": send_reply})
            for act in send_actions:
                yield _sse("action", act)
            tts_text = fallback_spoken_reply(send_reply, state["language"])
            if tts_text.strip():
                yield _sse("tts", {"text": tts_text, "index": 0})
            yield _sse("done", {
                "conversation_id": conversation_id,
                "pending": make_pending_payload(state),
                "full_text": send_reply,
            })

        return StreamingResponse(send_gen(), media_type="text/event-stream")

    def stream_gen():
        messages = state["messages"]
        messages.append({"role": "user", "content": request.message})

        full_text = ""
        actions = []
        sentence_buffer = ""
        tts_index = 0

        while True:
            with claude_client.messages.stream(
                model=MODEL_NAME,
                max_tokens=4096,
                system=build_system_prompt(state["language"]),
                tools=TOOLS,
                messages=messages,
            ) as stream:
                for chunk in stream.text_stream:
                    full_text += chunk
                    sentence_buffer += chunk
                    yield _sse("token", {"text": chunk})

                    sentences = _split_sentences(sentence_buffer)
                    if len(sentences) > 1:
                        for s in sentences[:-1]:
                            tts_text = fallback_spoken_reply(s, state["language"])
                            if tts_text.strip():
                                yield _sse("tts", {"text": tts_text, "index": tts_index})
                                tts_index += 1
                        sentence_buffer = sentences[-1]

                response = stream.get_final_message()

            if response.stop_reason != "tool_use":
                break

            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                result = execute_tool(block.name, block.input, erp_client)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json_result(result),
                })
                if result.get("status") == "confirmation_required":
                    state["pending_action"] = {
                        "tool_name": result.get("tool_name", block.name),
                        "tool_input": result.get("pending_input", block.input),
                    }
                else:
                    actions.extend(extract_card_actions(result))

            messages.append({"role": "user", "content": tool_results})

        if sentence_buffer.strip():
            tts_text = fallback_spoken_reply(sentence_buffer, state["language"])
            if tts_text.strip():
                yield _sse("tts", {"text": tts_text, "index": tts_index})

        if state.get("pending_action"):
            actions = []

        transient = state.pop("transient_actions", [])
        actions = transient + actions

        for act in actions:
            yield _sse("action", act)

        messages.append({"role": "assistant", "content": response.content})
        _save_conversation(conversation_id, state)

        yield _sse("done", {
            "conversation_id": conversation_id,
            "pending": make_pending_payload(state),
            "full_text": full_text,
        })

    return StreamingResponse(stream_gen(), media_type="text/event-stream")


@app.post("/api/tts")
async def text_to_speech(request: TTSRequest):
    """Generate spoken audio for assistant replies using Sarvam AI."""

    if not SARVAM_API_KEY:
        raise HTTPException(status_code=503, detail="SARVAM_API_KEY is not configured.")

    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text is required.")

    language_code = get_sarvam_language_code(request.language)

    try:
        sarvam_response = requests.post(
            f"{SARVAM_BASE_URL}/text-to-speech",
            headers={
                "api-subscription-key": SARVAM_API_KEY,
                "Content-Type": "application/json",
            },
            json={
                "text": text,
                "target_language_code": language_code,
                "model": SARVAM_TTS_MODEL,
                "speaker": SARVAM_TTS_SPEAKER,
                "speech_sample_rate": "24000",
                "output_audio_codec": "mp3",
            },
            timeout=45,
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Sarvam TTS request failed: {exc}") from exc

    if not sarvam_response.ok:
        detail = sarvam_response.text[:500] or "Sarvam TTS failed."
        raise HTTPException(status_code=502, detail=detail)

    data = sarvam_response.json()
    audios = data.get("audios", [])
    if not audios:
        raise HTTPException(status_code=502, detail="Sarvam TTS returned no audio.")

    audio_bytes = base64.b64decode(audios[0])

    return Response(
        content=audio_bytes,
        media_type="audio/mpeg",
        headers={
            "X-Voice-Provider": "sarvam",
            "X-TTS-Language": language_code,
        },
    )


@app.post("/api/voice/transcribe")
async def voice_transcribe(
    file: UploadFile = File(...),
    language: str = "en-IN",
):
    """Transcribe audio to text using Sarvam AI. Handles Hindi + English natively."""
    if not SARVAM_API_KEY:
        raise HTTPException(status_code=503, detail="SARVAM_API_KEY is not configured.")

    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio upload.")

    filename = file.filename or "audio.webm"
    content_type = (file.content_type or "audio/webm").split(";")[0].strip()

    language_code = get_sarvam_language_code(language)

    try:
        resp = requests.post(
            f"{SARVAM_BASE_URL}/speech-to-text",
            headers={"api-subscription-key": SARVAM_API_KEY},
            files={"file": (filename, audio_bytes, content_type)},
            data={
                "model": SARVAM_STT_MODEL,
                "language_code": language_code,
            },
            timeout=60,
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Sarvam STT request failed: {exc}") from exc

    if not resp.ok:
        log.error("Sarvam STT %s rejected upload (%s bytes, type=%s): %s",
                  resp.status_code, len(audio_bytes), content_type, resp.text[:500])
        raise HTTPException(status_code=502, detail=resp.text[:500] or "Sarvam STT failed.")

    data = resp.json()
    log.info("Sarvam STT transcribed %s bytes → %r (%s)",
             len(audio_bytes), (data.get("transcript") or "")[:80], data.get("language_code"))
    return {
        "text": (data.get("transcript") or "").strip(),
        "language_code": data.get("language_code"),
    }


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "bahi-agent"}


@app.get("/api/invoice/{name}/pdf")
async def invoice_pdf(name: str):
    """Proxy the ERPNext print PDF so it can be shared via a public URL."""
    try:
        pdf_response = erp_client.session.get(
            f"{erp_client.base_url}/api/method/frappe.utils.print_format.download_pdf",
            params={"doctype": "Sales Invoice", "name": name, "format": "Standard", "no_letterhead": 0},
        )
        pdf_response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"PDF fetch failed: {exc}") from exc

    return Response(
        content=pdf_response.content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{name}.pdf"'},
    )


@app.post("/api/invoice/{name}/mark-sent")
async def mark_invoice_sent(name: str):
    """Submit a Draft invoice (docstatus 0 → 1) after the user has dispatched it."""
    try:
        doc = erp_client.get_document("Sales Invoice", name)
        if int(doc.get("docstatus", 0)) != 0:
            return {"status": "already_submitted", "invoice_status": doc.get("status")}
        erp_client.submit_document("Sales Invoice", name)
        updated = erp_client.get_document("Sales Invoice", name)
        return {
            "status": "success",
            "invoice_name": name,
            "invoice_status": updated.get("status"),
            "outstanding_amount": updated.get("outstanding_amount"),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/invoice/{name}")
async def get_invoice(name: str):
    """Fetch a single invoice with its items for the detail page."""
    try:
        doc = erp_client.get_document("Sales Invoice", name)
        return {
            "name": doc.get("name"),
            "customer": doc.get("customer"),
            "customer_name": doc.get("customer_name"),
            "posting_date": doc.get("posting_date"),
            "due_date": doc.get("due_date"),
            "status": doc.get("status"),
            "grand_total": doc.get("grand_total"),
            "net_total": doc.get("net_total"),
            "outstanding_amount": doc.get("outstanding_amount"),
            "total_taxes_and_charges": doc.get("total_taxes_and_charges"),
            "taxes_and_charges": doc.get("taxes_and_charges"),
            "currency": doc.get("currency", "INR"),
            "items": [
                {
                    "item_code": item.get("item_code"),
                    "item_name": item.get("item_name"),
                    "qty": item.get("qty"),
                    "rate": item.get("rate"),
                    "amount": item.get("amount"),
                }
                for item in doc.get("items", [])
            ],
            "payments": [
                {
                    "name": ref.get("reference_name"),
                    "amount": ref.get("allocated_amount"),
                }
                for ref in doc.get("payment_schedule", [])
            ] if doc.get("payment_schedule") else [],
        }
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/invoices")
async def list_invoices(status: str = None, customer: str = None, limit: int = 50):
    """List invoices with optional filters for the list page."""
    from datetime import date
    filters = []
    if status:
        if status.lower() == "unpaid":
            filters.append(["docstatus", "=", 1])
            filters.append(["outstanding_amount", ">", 0])
            filters.append(["due_date", ">=", date.today().isoformat()])
        elif status.lower() == "overdue":
            filters.append(["docstatus", "=", 1])
            filters.append(["outstanding_amount", ">", 0])
            filters.append(["due_date", "<", date.today().isoformat()])
        elif status.lower() == "paid":
            filters.append(["docstatus", "=", 1])
            filters.append(["outstanding_amount", "=", 0])
        elif status.lower() == "draft":
            filters.append(["docstatus", "=", 0])
        else:
            filters.append(["status", "=", status])
    if customer:
        filters.append(["customer", "like", f"%{customer}%"])

    try:
        data = erp_client.get_list(
            "Sales Invoice",
            filters=filters or None,
            fields=[
                "name", "customer", "status", "grand_total",
                "outstanding_amount", "posting_date", "due_date",
            ],
            limit=limit,
            order_by="creation desc",
        )
        return {"data": data}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/customer/{name}")
async def get_customer(name: str):
    """Fetch customer details and their invoices for the detail page."""
    try:
        doc = erp_client.get_document("Customer", name)
        invoices = erp_client.get_list(
            "Sales Invoice",
            filters=[["customer", "=", name]],
            fields=[
                "name", "status", "grand_total",
                "outstanding_amount", "posting_date", "due_date",
            ],
            limit=50,
            order_by="creation desc",
        )
        total_outstanding = sum(
            float(inv.get("outstanding_amount", 0)) for inv in invoices
        )
        return {
            "name": doc.get("name"),
            "customer_name": doc.get("customer_name"),
            "customer_type": doc.get("customer_type"),
            "email": doc.get("email_id"),
            "phone": doc.get("mobile_no"),
            "territory": doc.get("territory"),
            "total_outstanding": total_outstanding,
            "invoices": invoices,
        }
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}


@app.get("/invoice/{name}")
async def invoice_page(name: str):
    """Serve the invoice detail page."""
    return FileResponse("static/invoice.html", media_type="text/html", headers=NO_CACHE)


@app.get("/api/customers")
async def list_customers(limit: int = 50):
    """List customers with outstanding totals for the list page."""
    try:
        customers = erp_client.get_list(
            "Customer",
            fields=["name", "customer_name", "customer_type", "mobile_no"],
            limit=limit,
        )
        # Fetch outstanding per customer
        for cust in customers:
            invoices = erp_client.get_list(
                "Sales Invoice",
                filters=[["customer", "=", cust["name"]], ["outstanding_amount", ">", 0]],
                fields=["outstanding_amount"],
                limit=100,
            )
            cust["total_outstanding"] = sum(float(inv.get("outstanding_amount", 0)) for inv in invoices)
            cust["unpaid_count"] = len(invoices)
        return {"data": customers}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/invoices")
async def invoices_page():
    """Serve the invoice list page."""
    return FileResponse("static/invoices.html", media_type="text/html", headers=NO_CACHE)


@app.get("/customers")
async def customers_page():
    """Serve the customers list page."""
    return FileResponse("static/customers.html", media_type="text/html", headers=NO_CACHE)


@app.get("/customer/{name}")
async def customer_page(name: str):
    """Serve the customer detail page."""
    return FileResponse("static/customer.html", media_type="text/html", headers=NO_CACHE)


@app.get("/")
async def root():
    return FileResponse("static/index.html", media_type="text/html", headers=NO_CACHE)


app.mount("/static", StaticFiles(directory="static"), name="static")
