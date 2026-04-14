"""
Navi Server
A FastAPI backend that serves the AI agent via HTTP API.
The chat UI talks to this server, which talks to Claude and ERPNext.
"""

import os
import re
import uuid
from urllib.parse import quote

import anthropic
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
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

app = FastAPI(title="Navi AI Agent API")

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
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_BASE_URL = "https://api.elevenlabs.io/v1"
DEFAULT_TTS_MODEL = os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")
DEFAULT_EN_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID_EN", "21m00Tcm4TlvDq8ikWAM")
DEFAULT_HI_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID_HI", DEFAULT_EN_VOICE_ID)

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


def handle_pending_action(state: dict, user_message: str) -> tuple[str | None, str | None, list]:
    pending_action = state.get("pending_action")
    if not pending_action:
        return None, None, []

    language = state.get("language", "en-IN")
    is_hindi = language.lower().startswith("hi")

    if is_affirmative(user_message):
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

        spoken_reply = generate_spoken_reply(reply, language)
        state["messages"].append({"role": "user", "content": user_message})
        state["messages"].append({"role": "assistant", "content": reply})
        return reply, spoken_reply, actions

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


def get_tts_config(language: str) -> tuple[str, str]:
    normalized = (language or "en-IN").lower()
    if normalized.startswith("hi"):
        return DEFAULT_HI_VOICE_ID, "hi"
    return DEFAULT_EN_VOICE_ID, "en"


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Main chat endpoint."""

    conversation_id = request.conversation_id or str(uuid.uuid4())
    state = get_conversation_state(conversation_id)
    state["language"] = request.language or state.get("language", "en-IN")

    pending_reply, pending_spoken_reply, pending_actions = handle_pending_action(state, request.message)
    if pending_reply is not None:
        return ChatResponse(
            reply=pending_reply,
            spoken_reply=pending_spoken_reply or pending_reply,
            conversation_id=conversation_id,
            actions=pending_actions,
        )

    send_reply, send_spoken_reply, send_actions = handle_pending_send(state, request.message)
    if send_reply is not None:
        return ChatResponse(
            reply=send_reply,
            spoken_reply=send_spoken_reply or send_reply,
            conversation_id=conversation_id,
            actions=send_actions,
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

    final_text = "".join(
        block.text for block in response.content if hasattr(block, "text")
    )
    spoken_reply = generate_spoken_reply(final_text, state["language"])

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
    return {"status": "ok", "service": "navi-agent"}


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
async def list_invoices(status: str = None, customer: str = None, limit: int = 20):
    """List invoices with optional filters for the list page."""
    filters = []
    if status:
        if status.lower() == "unpaid":
            filters.append(["outstanding_amount", ">", 0])
        elif status.lower() == "overdue":
            filters.append(["outstanding_amount", ">", 0])
            filters.append(["due_date", "<", __import__("datetime").date.today().isoformat()])
        elif status.lower() == "paid":
            filters.append(["outstanding_amount", "=", 0])
            filters.append(["docstatus", "=", 1])
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


@app.get("/invoice/{name}")
async def invoice_page(name: str):
    """Serve the invoice detail page."""
    return FileResponse("static/invoice.html", media_type="text/html")


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
    return FileResponse("static/invoices.html", media_type="text/html")


@app.get("/customers")
async def customers_page():
    """Serve the customers list page."""
    return FileResponse("static/customers.html", media_type="text/html")


@app.get("/customer/{name}")
async def customer_page(name: str):
    """Serve the customer detail page."""
    return FileResponse("static/customer.html", media_type="text/html")


@app.get("/")
async def root():
    return FileResponse("static/index.html", media_type="text/html")


app.mount("/static", StaticFiles(directory="static"), name="static")
