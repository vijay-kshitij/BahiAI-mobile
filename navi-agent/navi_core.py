import json
import logging
import re
from typing import Any

log = logging.getLogger("navi")
logging.basicConfig(level=logging.INFO)


MODEL_NAME = "claude-sonnet-4-6"


def normalize_name(name: str) -> str:
    """Normalize a name for comparison — strips punctuation, extra spaces, lowercases."""
    n = name.strip().lower()
    n = re.sub(r"[.\,\-]+$", "", n)
    n = re.sub(r"\s+", " ", n)
    n = n.replace(".", "").replace(",", "")
    return n.strip()


TOOLS = [
    {
        "name": "list_documents",
        "description": (
            "List ERPNext documents with optional filters. Use for customers, items, sales invoices, "
            "and payment entries. "
            "Supports date filters, status filters, and any field on the doctype. "
            "Each filter is a [field, operator, value] array. "
            "Operators: '=', '!=', '>', '<', '>=', '<=', 'like', 'not like'. "
            "Examples: "
            "[\"posting_date\", \"=\", \"2026-04-03\"] filters invoices by exact date. "
            "[\"posting_date\", \">=\", \"2026-04-01\"] filters from a start date. "
            "[\"status\", \"=\", \"Unpaid\"] filters by status. "
            "[\"customer\", \"like\", \"%Priya%\"] filters by customer name pattern."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "doctype": {
                    "type": "string",
                    "description": "ERPNext document type: Customer, Item, Sales Invoice, or Payment Entry.",
                },
                "filters": {
                    "type": "array",
                    "description": "Optional list of filters. Each filter is a 3-element array: [field, operator, value].",
                    "items": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 3,
                        "maxItems": 3,
                    },
                },
                "fields": {
                    "type": "array",
                    "description": "Optional list of field names to return. If omitted, default fields are returned.",
                    "items": {"type": "string"},
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of rows to return. Default is 20.",
                    "default": 20,
                },
            },
            "required": ["doctype"],
        },
    },
    {
        "name": "get_document",
        "description": "Get a specific ERPNext document by its exact name or ID. Returns all fields.",
        "input_schema": {
            "type": "object",
            "properties": {
                "doctype": {"type": "string"},
                "name": {"type": "string"},
            },
            "required": ["doctype", "name"],
        },
    },
    {
        "name": "search_documents",
        "description": "Search ERPNext documents by partial name when the exact ID is unknown.",
        "input_schema": {
            "type": "object",
            "properties": {
                "doctype": {"type": "string"},
                "query": {"type": "string"},
                "limit": {
                    "type": "integer",
                    "default": 10,
                },
            },
            "required": ["doctype", "query"],
        },
    },
    {
        "name": "create_customer",
        "description": "Create a new customer in ERPNext.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_name": {
                    "type": "string",
                    "description": "Customer name to store in ERPNext. Always use English/transliterated Latin script, not Devanagari.",
                },
                "customer_type": {
                    "type": "string",
                    "enum": ["Individual", "Company"],
                    "default": "Individual",
                },
                "customer_group": {"type": "string", "default": "Individual"},
                "territory": {"type": "string", "default": "India"},
                "email": {"type": "string"},
                "phone": {"type": "string"},
            },
            "required": ["customer_name"],
        },
    },
    {
        "name": "create_item",
        "description": "Create a new item in ERPNext.",
        "input_schema": {
            "type": "object",
            "properties": {
                "item_code": {
                    "type": "string",
                    "description": "English ERP item code in Latin script.",
                },
                "item_name": {
                    "type": "string",
                    "description": "English item name in Latin script, even if the user asked in Hindi.",
                },
                "item_group": {"type": "string", "default": "Products"},
                "stock_uom": {"type": "string", "default": "Nos"},
                "standard_rate": {"type": "number", "default": 0},
                "description": {"type": "string"},
            },
            "required": ["item_code", "item_name"],
        },
    },
    {
        "name": "create_sales_invoice",
        "description": "Create a sales invoice in ERPNext. Use this for invoicing requests after collecting customer, items, quantity, and rates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer": {"type": "string"},
                "due_date": {
                    "type": "string",
                    "description": "Due date in YYYY-MM-DD format when provided by the user.",
                },
                "tax_template": {
                    "type": "string",
                    "description": (
                        "GST tax template to apply. Use when the user mentions GST or tax. "
                        "Options: 'GST 5%', 'GST 12%', 'GST 18%', 'GST 28%'. "
                        "Default to 'GST 18%' if user just says 'add GST' without specifying a rate."
                    ),
                },
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "item_code": {
                                "type": "string",
                                "description": "ERPNext item code or English/plain-language item name, such as SKU002 or Laptop.",
                            },
                            "qty": {"type": "number"},
                            "rate": {"type": "number"},
                        },
                        "required": ["item_code", "qty"],
                    },
                },
                "confirmed": {
                    "type": "boolean",
                    "description": "Only set true after the user has explicitly confirmed the invoice preview.",
                    "default": False,
                },
            },
            "required": ["customer", "items"],
        },
    },
    {
        "name": "send_invoice",
        "description": (
            "Send a Draft sales invoice to the customer on WhatsApp. "
            "Generates a WhatsApp deeplink the user can tap to send the invoice PDF. "
            "Use this when the user says 'send it', 'share it', 'send to customer', or confirms "
            "after you've asked 'Should I send it on WhatsApp?'. "
            "Optionally pass a phone number if the customer has none on file."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "invoice_name": {
                    "type": "string",
                    "description": "The Sales Invoice ID, e.g. ACC-SINV-2026-00001.",
                },
                "phone": {
                    "type": "string",
                    "description": "Optional phone number with country code (e.g. +919876543210). Only needed if the customer has no mobile number saved.",
                },
            },
            "required": ["invoice_name"],
        },
    },
    {
        "name": "record_payment",
        "description": (
            "Record a payment against a Sales Invoice. Creates a Payment Entry in ERPNext. "
            "Use when the user says a customer paid, or asks to record/receive a payment."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "invoice_name": {
                    "type": "string",
                    "description": "The Sales Invoice ID, e.g. ACC-SINV-2026-00001.",
                },
                "amount": {
                    "type": "number",
                    "description": "Payment amount. If omitted, pays the full outstanding amount.",
                },
                "mode_of_payment": {
                    "type": "string",
                    "description": "Mode of payment such as Cash, Bank Transfer, UPI. Default is Cash.",
                    "default": "Cash",
                },
                "confirmed": {
                    "type": "boolean",
                    "description": "Only set true after the user has explicitly confirmed the payment details.",
                    "default": False,
                },
            },
            "required": ["invoice_name"],
        },
    },
    {
        "name": "list_unpaid_sales_invoices",
        "description": "List sales invoices that still have outstanding amount. Use this for unpaid, overdue, or pending receivables questions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "default": 10,
                },
            },
        },
    },
    {
        "name": "update_document",
        "description": (
            "Update fields on an existing ERPNext document. "
            "Use for changing due date, customer details, item rates, etc. "
            "Only works on Draft documents. Submitted documents must be amended."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "doctype": {
                    "type": "string",
                    "description": "Document type: Sales Invoice, Customer, Item, etc.",
                },
                "name": {
                    "type": "string",
                    "description": "The document ID, e.g. ACC-SINV-2026-00001.",
                },
                "updates": {
                    "type": "object",
                    "description": "Key-value pairs of fields to update. e.g. {\"due_date\": \"2026-05-01\"}",
                },
            },
            "required": ["doctype", "name", "updates"],
        },
    },
    {
        "name": "delete_document",
        "description": "Delete an ERPNext document only after an explicit confirmation from the user.",
        "input_schema": {
            "type": "object",
            "properties": {
                "doctype": {"type": "string"},
                "name": {"type": "string"},
                "confirmed": {
                    "type": "boolean",
                    "default": False,
                },
            },
            "required": ["doctype", "name"],
        },
    },
    {
        "name": "submit_document",
        "description": (
            "Submit a Draft document in ERPNext (changes docstatus from 0 to 1). "
            "Use this when the user asks to submit, finalize, or confirm a Draft invoice or other document. "
            "A Sales Invoice must be submitted before payments can be recorded against it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "doctype": {
                    "type": "string",
                    "description": "Document type: Sales Invoice, Purchase Invoice, etc.",
                },
                "name": {
                    "type": "string",
                    "description": "The document ID, e.g. ACC-SINV-2026-00001.",
                },
                "confirmed": {
                    "type": "boolean",
                    "description": "Only set true after the user has explicitly confirmed.",
                    "default": False,
                },
            },
            "required": ["doctype", "name"],
        },
    },
    {
        "name": "cancel_document",
        "description": (
            "Cancel a submitted document in ERPNext (changes docstatus from 1 to 2). "
            "Use when the user asks to cancel a submitted invoice or other document. "
            "Cancelled documents cannot be edited — use amend_document to create a corrected copy."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "doctype": {
                    "type": "string",
                    "description": "Document type: Sales Invoice, Payment Entry, etc.",
                },
                "name": {
                    "type": "string",
                    "description": "The document ID, e.g. ACC-SINV-2026-00001.",
                },
                "confirmed": {
                    "type": "boolean",
                    "description": "Only set true after the user has explicitly confirmed.",
                    "default": False,
                },
            },
            "required": ["doctype", "name"],
        },
    },
    {
        "name": "amend_document",
        "description": (
            "Amend a cancelled document in ERPNext — creates a new draft copy that can be edited and resubmitted. "
            "Use when the user wants to correct a cancelled invoice or document. "
            "The document must be cancelled first (docstatus=2) before it can be amended."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "doctype": {
                    "type": "string",
                    "description": "Document type: Sales Invoice, Payment Entry, etc.",
                },
                "name": {
                    "type": "string",
                    "description": "The cancelled document ID, e.g. ACC-SINV-2026-00001.",
                },
                "confirmed": {
                    "type": "boolean",
                    "description": "Only set true after the user has explicitly confirmed.",
                    "default": False,
                },
            },
            "required": ["doctype", "name"],
        },
    },
    {
        "name": "navigate_to_page",
        "description": (
            "Navigate the user to a page in the app. Use this when the user says "
            "'show me', 'open', 'list', or asks to see invoices, customers, or a specific record. "
            "ALWAYS prefer navigation over dumping data into chat for list/browse requests."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "page": {
                    "type": "string",
                    "enum": ["invoices", "customers", "invoice-detail", "customer-detail"],
                    "description": "Which page to navigate to.",
                },
                "filter": {
                    "type": "string",
                    "description": "Optional filter: 'unpaid', 'overdue', 'paid' for invoices list.",
                },
                "id": {
                    "type": "string",
                    "description": "Document name/ID for detail pages (e.g. ACC-SINV-2026-00001 or Priya Patel).",
                },
                "description": {
                    "type": "string",
                    "description": "Short description of what the user will see.",
                },
            },
            "required": ["page"],
        },
    },
]


SYSTEM_PROMPT = """You are Navi, an AI invoicing assistant for small businesses.
Your job is to help users manage invoicing — create invoices, record payments, track receivables, and manage customers and items — entirely through chat.

## Invoice creation — STRICT RULES
When the user asks to create an invoice, you need exactly THREE things: customer name, item(s) with quantity, and rate.
- If the user gives all three in one message → call create_sales_invoice IMMEDIATELY. Do not ask anything else.
- If only customer is missing → ask ONLY for customer name.
- If only items are missing → ask ONLY for items with quantity and rate.
- Once you have customer + items + rates, ask: "Any due date? Or should I go ahead and create it?" This is the ONLY optional question you may ask — and only ONCE.
- If the user replies with a date → include it. If they say "no", "go ahead", "create it", or anything that isn't a date → call create_sales_invoice immediately without a due date.
- NEVER ask for customer type, customer group, territory, item group, UOM, or any other field.
- NEVER check if a customer or item exists before creating an invoice. The backend auto-creates missing ones.
- Maximum ONE question per turn. Never ask for two things at once.

## Navigation — STRICT RULES
When the user says "show me", "open", "list", or wants to SEE invoices/customers:
- ALWAYS use navigate_to_page to send them to the page. Do NOT dump data into chat.
- "show me unpaid invoices" → navigate_to_page(page="invoices", filter="unpaid")
- "show me all invoices" → navigate_to_page(page="invoices")
- "show me customers" → navigate_to_page(page="customers")
- "open invoice ACC-SINV-001" → navigate_to_page(page="invoice-detail", id="ACC-SINV-001")
- "show me Priya's details" → navigate_to_page(page="customer-detail", id="Priya Patel")
After navigating, reply with a SHORT one-line confirmation like "Opening unpaid invoices."

For DATA questions (not browsing) like "how many unpaid invoices?" or "what's Rajesh's total outstanding?" → answer in chat using tools, don't navigate.

## Sending invoices — STRICT RULES
After an invoice is created, it is a Draft. The user must explicitly send it before it becomes Unpaid.
- Immediately after create_sales_invoice succeeds, ask: "Draft invoice {ID} created. Should I send it to {customer} on WhatsApp?"
- If the user says yes / send / share it → call send_invoice with the invoice_name.
- If send_invoice returns an error about a missing phone number → ask the user for the customer's WhatsApp number, then call send_invoice again with the phone argument.
- After send_invoice succeeds, reply with a SHORT confirmation like "Ready to send — tap the button below."
- Do NOT describe the WhatsApp link in text; the UI shows a button.

## Payment recording
When the user says someone paid or asks to record a payment:
1. Identify the invoice (search if needed)
2. Confirm the amount (default to full outstanding)
3. Ask for confirmation before recording

## Cancelling and amending
- To cancel a submitted invoice: use cancel_document. This reverses all ledger entries.
- To edit a submitted invoice: first cancel it, then amend it (amend_document creates a new draft copy), then edit the draft, then submit it again.
- Both cancel and amend require user confirmation.
- When the user says "edit this invoice" and it's submitted, explain the cancel → amend → edit → resubmit flow and ask if they want to proceed.

## Rules
- Keep replies SHORT. One or two sentences max.
- Always use tools for factual data. Never invent balances or totals.
- For payment recording and deletion, get explicit confirmation first.
- When a tool result says confirmation is required, show the preview and wait.
- Keep ERP data in English/Latin script even when user speaks Hindi.
- After creating a document, mention the document ID.
- Use ₹ for amounts.
- Minimize questions. If you have enough info to act, act immediately.
"""


def doctype_to_route(doctype: str) -> str:
    return doctype.strip().lower().replace(" ", "-")


def document_path(doctype: str, name: str | None = None) -> str:
    base = f"/app/{doctype_to_route(doctype)}"
    if name:
        return f"{base}/{name}"
    return base


def tool_requires_confirmation(tool_name: str) -> bool:
    # create_sales_invoice handles its own confirmation (resolves items/customers first)
    return tool_name in {"delete_document", "record_payment", "submit_document", "cancel_document", "amend_document"}


def _summarize_line_items(items: list[dict[str, Any]]) -> list[str]:
    lines = []
    for item in items:
        item_code = item.get("item_code", "Unknown Item")
        qty = item.get("qty", 0)
        rate = item.get("rate")
        if rate is None:
            lines.append(f"{qty} x {item_code}")
        else:
            lines.append(f"{qty} x {item_code} @ ₹{rate}")
    return lines


def _item_query_variants(query: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", query.strip().lower())
    if not cleaned:
        return []

    variants: list[str] = []

    def add_variant(value: str) -> None:
        value = value.strip()
        if value and value not in variants:
            variants.append(value)

    add_variant(cleaned)
    add_variant(re.sub(r"^(a|an|the)\s+", "", cleaned))

    words = cleaned.split()
    if words:
        last = words[-1]
        singular_last = last
        if last.endswith("ies") and len(last) > 3:
            singular_last = last[:-3] + "y"
        elif last.endswith("es") and len(last) > 3:
            singular_last = last[:-2]
        elif last.endswith("s") and len(last) > 2:
            singular_last = last[:-1]

        if singular_last != last:
            singular_words = words[:-1] + [singular_last]
            add_variant(" ".join(singular_words))
            add_variant(re.sub(r"^(a|an|the)\s+", "", " ".join(singular_words)))

    compact = cleaned.replace("-", " ")
    add_variant(compact)

    return variants


def resolve_item_code(erp_client, query: str, rate: float = 0, auto_create: bool = True) -> tuple[str, str | None, bool]:
    """Resolve an item name/code to ERPNext's actual item_code.

    Returns (item_code, error_or_none, was_created).
    If auto_create is True and no match is found, creates the item automatically.
    """
    variants = _item_query_variants(query)
    items = erp_client.get_list(
        "Item",
        fields=["name", "item_code", "item_name", "stock_uom"],
        limit=200,
    )

    normalized_variants = [normalize_name(v) for v in variants]

    exact_match = next(
        (
            item
            for item in items
            for nv in normalized_variants
            if nv in {
                normalize_name(str(item.get("name", ""))),
                normalize_name(str(item.get("item_code", ""))),
                normalize_name(str(item.get("item_name", ""))),
            }
        ),
        None,
    )
    if exact_match:
        return exact_match.get("item_code"), None, False

    partial_matches = [
        item
        for item in items
        if any(
            nv in normalize_name(str(item.get("item_code", "")))
            or nv in normalize_name(str(item.get("item_name", "")))
            for nv in normalized_variants
        )
    ]
    if len(partial_matches) == 1:
        return partial_matches[0].get("item_code"), None, False

    if len(partial_matches) > 1:
        match_list = ", ".join(
            f"{item.get('item_code')} ({item.get('item_name')})"
            for item in partial_matches[:5]
        )
        return None, f"Multiple items match '{query}': {match_list}", False

    # Not found — auto-create if allowed
    if auto_create:
        item_name = query.strip().title()
        item_code = re.sub(r"[^a-zA-Z0-9]+", "-", query.strip().upper()).strip("-")
        try:
            result = erp_client.create_document("Item", {
                "item_code": item_code,
                "item_name": item_name,
                "item_group": "Products",
                "stock_uom": "Nos",
                "standard_rate": rate,
                "is_stock_item": 0,
            })
            return result.get("item_code") or item_code, None, True
        except Exception:
            # Might already exist (race condition / duplicate) — return the code anyway
            return item_code, None, True

    return None, f"No items found for '{query}'", False


def normalize_phone(raw: str, default_country_code: str = "91") -> str | None:
    """Normalize a phone number to E.164 digits (no +, no spaces). Returns None if invalid."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", str(raw))
    if not digits:
        return None
    # If it looks like a 10-digit local Indian number, prepend country code
    if len(digits) == 10:
        digits = default_country_code + digits
    # Expect 11-15 digits after normalization
    if len(digits) < 11 or len(digits) > 15:
        return None
    return digits


def resolve_customer(erp_client, customer_name: str) -> tuple[str, bool]:
    """Resolve a customer name. Auto-creates if not found.

    Returns (customer_name_in_erp, was_created).
    """
    normalized_query = normalize_name(customer_name)

    # Exact match
    try:
        doc = erp_client.get_document("Customer", customer_name)
        if doc and doc.get("name"):
            return doc["name"], False
    except Exception:
        pass

    # Search by partial name
    results = erp_client.search("Customer", customer_name, fields=["name", "customer_name"], limit=5)
    if not results:
        results = find_similar_customers(erp_client, customer_name)
    if results:
        # Check for normalized match
        for r in results:
            if (normalize_name(r.get("name", "")) == normalized_query
                    or normalize_name(r.get("customer_name", "")) == normalized_query):
                return r["name"], False
        # If only one result, use it
        if len(results) == 1:
            return results[0]["name"], False

    # Not found — auto-create
    clean_name = customer_name.strip().title()
    try:
        result = erp_client.create_document("Customer", {
            "customer_name": clean_name,
            "customer_type": "Individual",
            "customer_group": "Individual",
            "territory": "India",
        })
        return result.get("name") or clean_name, True
    except Exception:
        # Might already exist (race condition / duplicate) — return the name anyway
        return clean_name, False


def search_item_catalog(erp_client, query: str, limit: int = 10) -> list[dict[str, Any]]:
    variants = _item_query_variants(query)
    items = erp_client.get_list(
        "Item",
        fields=["name", "item_code", "item_name", "stock_uom"],
        limit=200,
    )
    matches = [
        item
        for item in items
        if any(
            variant in str(item.get("item_code", "")).lower()
            or variant in str(item.get("item_name", "")).lower()
            for variant in variants
        )
    ]
    return matches[:limit]


def build_confirmation_preview(tool_name: str, tool_input: dict[str, Any]) -> str:
    if tool_name == "create_sales_invoice":
        lines = _summarize_line_items(tool_input.get("items", []))
        parts = [f"Create Sales Invoice for {tool_input['customer']}"]
        if lines:
            parts.append("Items: " + "; ".join(lines))
        if tool_input.get("due_date"):
            parts.append(f"Due date: {tool_input['due_date']}")
        return ". ".join(parts) + ". Please confirm whether I should create it."

    if tool_name == "record_payment":
        parts = [f"Record payment against invoice {tool_input['invoice_name']}"]
        if tool_input.get("amount"):
            parts.append(f"Amount: ₹{tool_input['amount']}")
        else:
            parts.append("Amount: full outstanding balance")
        parts.append(f"Mode: {tool_input.get('mode_of_payment', 'Cash')}")
        return ". ".join(parts) + ". Please confirm whether I should record this payment."

    if tool_name == "submit_document":
        return (
            f"Submit {tool_input['doctype']} '{tool_input['name']}'. "
            "This will finalize it and it cannot be edited afterwards. Please confirm."
        )

    if tool_name == "cancel_document":
        return (
            f"Cancel {tool_input['doctype']} '{tool_input['name']}'. "
            "This will reverse all ledger entries. Please confirm."
        )

    if tool_name == "amend_document":
        return (
            f"Amend {tool_input['doctype']} '{tool_input['name']}'. "
            "This will create a new draft copy for editing. Please confirm."
        )

    if tool_name == "delete_document":
        return (
            f"Delete {tool_input['doctype']} '{tool_input['name']}'. "
            "Please confirm whether I should delete it."
        )

    return "Please confirm this action."


def find_similar_customers(erp_client, query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Find customers whose customer_name partially matches the query."""
    results = erp_client.get_list(
        "Customer",
        filters=[["customer_name", "like", f"%{query}%"]],
        fields=["name", "customer_name"],
        limit=limit,
    )
    if not results:
        results = erp_client.get_list(
            "Customer",
            filters=[["name", "like", f"%{query}%"]],
            fields=["name", "customer_name"],
            limit=limit,
        )
    return results


def find_similar_items(erp_client, query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Find items whose item_name or item_code partially matches the query."""
    results = erp_client.get_list(
        "Item",
        filters=[["item_name", "like", f"%{query}%"]],
        fields=["name", "item_code", "item_name"],
        limit=limit,
    )
    if not results:
        results = erp_client.get_list(
            "Item",
            filters=[["item_code", "like", f"%{query}%"]],
            fields=["name", "item_code", "item_name"],
            limit=limit,
        )
    return results


def _extract_filter_value(filters: list, field_names: tuple) -> str | None:
    """Extract a filter value from a list of filters by field name."""
    if not filters:
        return None
    for f in filters:
        if len(f) >= 3 and str(f[0]).lower() in field_names and str(f[1]) == "=":
            return str(f[2])
    return None


def execute_tool(tool_name: str, tool_input: dict[str, Any], erp_client) -> dict[str, Any]:
    """Execute a tool call and return a structured result."""
    try:
        if tool_requires_confirmation(tool_name) and not tool_input.get("confirmed"):
            return {
                "status": "confirmation_required",
                "tool_name": tool_name,
                "preview_message": build_confirmation_preview(tool_name, tool_input),
                "pending_input": tool_input,
            }

        if tool_name == "list_documents":
            result = erp_client.get_list(
                tool_input["doctype"],
                filters=tool_input.get("filters") or None,
                fields=tool_input.get("fields") or None,
                limit=tool_input.get("limit", 20),
            )
            if not result:
                customer_query = _extract_filter_value(tool_input.get("filters") or [], ("customer", "customer_name"))
                if customer_query:
                    similar = find_similar_customers(erp_client, customer_query)
                    if similar:
                        return {
                            "status": "success",
                            "data": [],
                            "similar_customers": similar,
                            "note": f"No exact match for customer '{customer_query}'. Similar customers found.",
                        }
                item_query = _extract_filter_value(tool_input.get("filters") or [], ("item", "item_code", "item_name"))
                if item_query:
                    similar = find_similar_items(erp_client, item_query)
                    if similar:
                        return {
                            "status": "success",
                            "data": [],
                            "similar_items": similar,
                            "note": f"No exact match for item '{item_query}'. Similar items found.",
                        }
            return {"status": "success", "data": result}

        if tool_name == "get_document":
            try:
                result = erp_client.get_document(tool_input["doctype"], tool_input["name"])
                return {"status": "success", "data": result}
            except Exception:
                doctype_lower = tool_input["doctype"].strip().lower()
                if doctype_lower == "customer":
                    similar = find_similar_customers(erp_client, tool_input["name"])
                    if similar:
                        return {
                            "status": "not_found",
                            "error": f"No customer named '{tool_input['name']}' found.",
                            "similar_customers": similar,
                        }
                if doctype_lower == "item":
                    similar = find_similar_items(erp_client, tool_input["name"])
                    if similar:
                        return {
                            "status": "not_found",
                            "error": f"No item named '{tool_input['name']}' found.",
                            "similar_items": similar,
                        }
                raise

        if tool_name == "search_documents":
            if tool_input["doctype"].strip().lower() == "item":
                result = search_item_catalog(
                    erp_client,
                    tool_input["query"],
                    limit=tool_input.get("limit", 10),
                )
                return {"status": "success", "data": result}

            if tool_input["doctype"].strip().lower() == "customer":
                result = find_similar_customers(
                    erp_client,
                    tool_input["query"],
                    limit=tool_input.get("limit", 10),
                )
                return {"status": "success", "data": result}

            result = erp_client.search(
                tool_input["doctype"],
                tool_input["query"],
                limit=tool_input.get("limit", 10),
            )
            return {"status": "success", "data": result}

        if tool_name == "create_customer":
            data = {
                "customer_name": tool_input["customer_name"],
                "customer_type": tool_input.get("customer_type", "Individual"),
                "customer_group": tool_input.get("customer_group", "Individual"),
                "territory": tool_input.get("territory", "India"),
            }
            if tool_input.get("email"):
                data["email_id"] = tool_input["email"]
            if tool_input.get("phone"):
                data["mobile_no"] = tool_input["phone"]

            result = erp_client.create_document("Customer", data)
            return {
                "status": "success",
                "customer_name": result.get("customer_name"),
                "name": result.get("name"),
            }

        if tool_name == "create_item":
            data = {
                "item_code": tool_input["item_code"],
                "item_name": tool_input["item_name"],
                "item_group": tool_input.get("item_group", "Products"),
                "stock_uom": tool_input.get("stock_uom", "Nos"),
                "standard_rate": tool_input.get("standard_rate", 0),
            }
            if tool_input.get("description"):
                data["description"] = tool_input["description"]

            result = erp_client.create_document("Item", data)
            return {
                "status": "success",
                "item_code": result.get("item_code"),
                "item_name": result.get("item_name"),
            }

        if tool_name == "create_sales_invoice":
            log.info("create_sales_invoice called | confirmed=%s | keys=%s",
                     tool_input.get("confirmed"), list(tool_input.keys()))

            # ── CONFIRMED: skip resolution, use stored values, create immediately ──
            if tool_input.get("confirmed"):
                final_customer = tool_input.get("_resolved_customer")
                final_items = tool_input.get("_resolved_items")

                if not final_customer or not final_items:
                    log.error("CONFIRMED but missing resolved data! customer=%s items=%s",
                              final_customer, final_items)
                    return {"status": "error", "error": "Internal error: missing resolved data. Please try creating the invoice again."}

                data = {
                    "customer": final_customer,
                    "items": final_items,
                }
                if tool_input.get("due_date"):
                    data["due_date"] = tool_input["due_date"]

                resolved_taxes = tool_input.get("_resolved_taxes")
                if resolved_taxes:
                    data["taxes_and_charges"] = resolved_taxes["template_name"]
                    data["taxes"] = resolved_taxes["taxes"]

                log.info("Creating Sales Invoice: %s", json.dumps(data, default=str))
                created = erp_client.create_document("Sales Invoice", data)
                invoice_name = created.get("name")
                log.info("Created invoice (Draft): %s", invoice_name)

                # Fetch final state for accurate card data. Invoice stays as Draft
                # until user explicitly sends it via send_invoice.
                try:
                    doc = erp_client.get_document("Sales Invoice", invoice_name)
                except Exception:
                    doc = created

                return {
                    "status": "success",
                    "doctype": "Sales Invoice",
                    "invoice_name": invoice_name,
                    "customer": doc.get("customer"),
                    "grand_total": doc.get("grand_total"),
                    "outstanding_amount": doc.get("outstanding_amount"),
                    "posting_date": doc.get("posting_date"),
                    "due_date": doc.get("due_date"),
                    "invoice_status": doc.get("status", "Draft"),
                    "items": doc.get("items", []),
                }

            # ── NOT CONFIRMED: resolve customer/items, then ask for confirmation ──
            auto_created = []

            customer_name, customer_created = resolve_customer(erp_client, tool_input["customer"])
            log.info("Resolved customer '%s' → '%s' (created=%s)",
                     tool_input["customer"], customer_name, customer_created)
            if customer_created:
                auto_created.append(f"New customer '{customer_name}' added")

            resolved_items = []
            for item in tool_input["items"]:
                rate = item.get("rate", 0)
                resolved_code, error, item_created = resolve_item_code(
                    erp_client, item["item_code"], rate=rate, auto_create=True,
                )
                log.info("Resolved item '%s' → '%s' (created=%s, error=%s)",
                         item["item_code"], resolved_code, item_created, error)
                if error:
                    return {"status": "error", "error": error}
                if item_created:
                    auto_created.append(f"New item '{resolved_code}' added")
                resolved_items.append(
                    {
                        "item_code": resolved_code,
                        "qty": item["qty"],
                        "rate": rate,
                    }
                )

            resolved_taxes = None
            tax_template = tool_input.get("tax_template")
            if tax_template:
                template_name = tax_template if tax_template.endswith(" - ND") else f"{tax_template} - ND"
                try:
                    tmpl_doc = erp_client.get_document("Sales Taxes and Charges Template", template_name)
                    resolved_taxes = {
                        "template_name": template_name,
                        "taxes": [
                            {
                                "charge_type": t["charge_type"],
                                "account_head": t["account_head"],
                                "rate": t["rate"],
                                "description": t["description"],
                            }
                            for t in tmpl_doc.get("taxes", [])
                        ],
                    }
                except Exception:
                    return {"status": "error", "error": f"Tax template '{tax_template}' not found."}

            preview = build_confirmation_preview(tool_name, tool_input)
            if auto_created:
                preview = ". ".join(auto_created) + ". " + preview
            if resolved_taxes:
                preview += f" Tax: {tax_template}."

            pending_input = {
                **tool_input,
                "_resolved_customer": customer_name,
                "_resolved_items": resolved_items,
            }
            if resolved_taxes:
                pending_input["_resolved_taxes"] = resolved_taxes

            return {
                "status": "confirmation_required",
                "tool_name": tool_name,
                "preview_message": preview,
                "pending_input": pending_input,
            }

        if tool_name == "send_invoice":
            invoice_name = tool_input["invoice_name"]
            invoice = erp_client.get_document("Sales Invoice", invoice_name)
            if not invoice:
                return {"status": "error", "error": f"Invoice {invoice_name} not found."}

            if int(invoice.get("docstatus", 0)) != 0:
                return {
                    "status": "error",
                    "error": f"Invoice {invoice_name} is not a Draft — it's already been sent.",
                }

            customer_name = invoice.get("customer")
            customer_doc = erp_client.get_document("Customer", customer_name)
            stored_phone = customer_doc.get("mobile_no") or customer_doc.get("phone")
            phone = normalize_phone(tool_input.get("phone") or stored_phone)

            if not phone:
                return {
                    "status": "error",
                    "error": (
                        f"No WhatsApp number on file for {customer_name}. "
                        "Please provide their phone number (with country code) so I can send the invoice."
                    ),
                }

            # If a new phone was provided, save it to the customer record for next time
            if tool_input.get("phone") and phone != normalize_phone(stored_phone):
                try:
                    erp_client.update_document("Customer", customer_name, {"mobile_no": phone})
                except Exception as exc:
                    log.warning("Failed to save phone for %s: %s", customer_name, exc)

            grand_total = invoice.get("grand_total", 0)
            return {
                "status": "success",
                "action_type": "send_invoice",
                "invoice_name": invoice_name,
                "customer": customer_name,
                "phone": phone,
                "grand_total": grand_total,
            }

        if tool_name == "record_payment":
            # Fetch the invoice to get outstanding amount and customer
            invoice = erp_client.get_document("Sales Invoice", tool_input["invoice_name"])
            if not invoice:
                return {"status": "error", "error": f"Invoice {tool_input['invoice_name']} not found."}

            outstanding = float(invoice.get("outstanding_amount", 0))
            if outstanding <= 0:
                return {"status": "error", "error": f"Invoice {tool_input['invoice_name']} is already fully paid."}

            amount = tool_input.get("amount") or outstanding
            if amount > outstanding:
                return {
                    "status": "error",
                    "error": f"Payment amount ₹{amount} exceeds outstanding ₹{outstanding}.",
                }

            customer = invoice.get("customer")
            company = invoice.get("company")
            currency = invoice.get("currency", "INR")

            mode = tool_input.get("mode_of_payment", "Cash")
            available_modes = [
                m["name"] for m in erp_client.get_list("Mode of Payment", fields=["name"], limit=50)
            ]
            if mode not in available_modes:
                mode = "Cash"

            account_type = "Bank" if mode != "Cash" else "Cash"
            accounts = erp_client.get_list(
                "Account",
                filters=[["company", "=", company], ["account_type", "=", account_type], ["is_group", "=", 0]],
                fields=["name"],
                limit=1,
            )
            if not accounts:
                accounts = erp_client.get_list(
                    "Account",
                    filters=[["company", "=", company], ["account_type", "=", "Cash"], ["is_group", "=", 0]],
                    fields=["name"],
                    limit=1,
                )
            paid_to = accounts[0]["name"] if accounts else None

            payment_data = {
                "payment_type": "Receive",
                "party_type": "Customer",
                "party": customer,
                "paid_amount": amount,
                "received_amount": amount,
                "mode_of_payment": mode,
                "source_exchange_rate": 1,
                "target_exchange_rate": 1,
                "paid_to_account_currency": currency,
                "paid_from_account_currency": currency,
                "references": [
                    {
                        "reference_doctype": "Sales Invoice",
                        "reference_name": tool_input["invoice_name"],
                        "allocated_amount": amount,
                    }
                ],
            }
            if paid_to:
                payment_data["paid_to"] = paid_to
            if company:
                payment_data["company"] = company

            result = erp_client.create_document("Payment Entry", payment_data)
            # Submit the payment entry so it actually affects the ledger
            payment_name = result.get("name")
            if payment_name:
                erp_client.submit_document("Payment Entry", payment_name)

            return {
                "status": "success",
                "doctype": "Payment Entry",
                "payment_name": payment_name,
                "invoice_name": tool_input["invoice_name"],
                "customer": customer,
                "amount": amount,
                "outstanding_after": outstanding - amount,
                "mode_of_payment": tool_input.get("mode_of_payment", "Cash"),
            }

        if tool_name == "list_unpaid_sales_invoices":
            result = erp_client.get_list(
                "Sales Invoice",
                filters=[["outstanding_amount", ">", 0]],
                fields=[
                    "name",
                    "customer",
                    "status",
                    "grand_total",
                    "outstanding_amount",
                    "due_date",
                    "posting_date",
                ],
                limit=tool_input.get("limit", 10),
            )
            return {"status": "success", "data": result}

        if tool_name == "update_document":
            result = erp_client.update_document(
                tool_input["doctype"],
                tool_input["name"],
                tool_input["updates"],
            )
            return {
                "status": "success",
                "message": f"Updated {tool_input['doctype']} {tool_input['name']}.",
                "data": result,
            }

        if tool_name == "submit_document":
            doc = erp_client.get_document(tool_input["doctype"], tool_input["name"])
            if int(doc.get("docstatus", 0)) != 0:
                return {
                    "status": "error",
                    "error": f"{tool_input['doctype']} {tool_input['name']} is already submitted.",
                }
            try:
                result = erp_client.submit_document(tool_input["doctype"], tool_input["name"])
            except Exception as exc:
                log.error("submit_document failed: %s", exc)
                return {
                    "status": "error",
                    "error": f"ERPNext rejected the submit: {exc}",
                }
            return {
                "status": "success",
                "message": f"{tool_input['doctype']} {tool_input['name']} has been submitted.",
                "data": result,
            }

        if tool_name == "cancel_document":
            doc = erp_client.get_document(tool_input["doctype"], tool_input["name"])
            if int(doc.get("docstatus", 0)) != 1:
                return {
                    "status": "error",
                    "error": f"{tool_input['doctype']} {tool_input['name']} is not submitted (docstatus={doc.get('docstatus')}). Only submitted documents can be cancelled.",
                }
            try:
                result = erp_client.cancel_document(tool_input["doctype"], tool_input["name"])
            except Exception as exc:
                log.error("cancel_document failed: %s", exc)
                return {
                    "status": "error",
                    "error": f"ERPNext rejected the cancellation: {exc}",
                }
            return {
                "status": "success",
                "message": f"{tool_input['doctype']} {tool_input['name']} has been cancelled.",
                "data": result,
            }

        if tool_name == "amend_document":
            doc = erp_client.get_document(tool_input["doctype"], tool_input["name"])
            if int(doc.get("docstatus", 0)) != 2:
                return {
                    "status": "error",
                    "error": f"{tool_input['doctype']} {tool_input['name']} is not cancelled (docstatus={doc.get('docstatus')}). Only cancelled documents can be amended.",
                }
            try:
                result = erp_client.amend_document(tool_input["doctype"], tool_input["name"])
            except Exception as exc:
                log.error("amend_document failed: %s", exc)
                return {
                    "status": "error",
                    "error": f"ERPNext rejected the amendment: {exc}",
                }
            new_name = result.get("name", "unknown")
            return {
                "status": "success",
                "message": f"Amended copy created: {new_name} (Draft). You can now edit and resubmit it.",
                "new_name": new_name,
                "data": result,
            }

        if tool_name == "delete_document":
            result = erp_client.delete_document(tool_input["doctype"], tool_input["name"])
            return {
                "status": "success",
                "message": result["message"],
            }

        if tool_name == "navigate_to_page":
            page = tool_input["page"]
            doc_id = tool_input.get("id", "")
            filt = tool_input.get("filter", "")

            if page == "invoices":
                path = "/invoices" + (f"?status={filt}" if filt else "")
            elif page == "customers":
                path = "/customers" + (f"?filter={filt}" if filt else "")
            elif page == "invoice-detail" and doc_id:
                path = f"/invoice/{doc_id}"
            elif page == "customer-detail" and doc_id:
                path = f"/customer/{doc_id}"
            else:
                path = "/"

            return {
                "status": "success",
                "action": "navigate",
                "path": path,
                "description": tool_input.get("description", ""),
            }

        return {"status": "error", "error": f"Unknown tool: {tool_name}"}

    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def is_affirmative(text: str) -> bool:
    normalized = text.strip().lower()

    # Check for negative phrases FIRST to avoid "don't do it" matching "do it"
    if is_negative(text):
        return False

    exact_matches = {
        "yes",
        "y",
        "confirm",
        "confirmed",
        "go ahead",
        "do it",
        "please do",
        "create it",
        "delete it",
        "okay",
        "ok",
        "sure",
        "haan",
        "han",
        "ha",
        "ji haan",
        "ji han",
        "haan ji",
        "han ji",
        "theek hai",
        "thik hai",
        "kar do",
        "kardo",
        "bana do",
        "banado",
        "hmm",
        "hm",
        "हाँ",
        "हां",
        "हाँ जी",
        "हां जी",
        "ठीक है",
        "कर दो",
        "बना दो",
    }
    if normalized in exact_matches:
        return True

    phrase_matches = {
        "yes please",
        "yes create",
        "yes, create",
        "yes do it",
        "please create",
        "please do it",
        "go ahead and create",
        "create it please",
        "yes go ahead",
        "haan banado",
        "haan bana do",
        "han bana do",
        "haan kardo",
        "haan kar do",
        "ji haan banado",
        "haan please",
        "हाँ बना दो",
        "हाँ कर दो",
        "हां बना दो",
        "हां कर दो",
    }
    return normalized in phrase_matches


def is_negative(text: str) -> bool:
    normalized = text.strip().lower()
    exact_matches = {
        "no",
        "n",
        "cancel",
        "stop",
        "don't",
        "do not",
        "nope",
        "not now",
        "nahi",
        "mat",
        "mat karo",
        "cancel karo",
        "rehne do",
        "don't do it",
        "don't create",
        "don't delete",
        "do not create",
        "do not delete",
        "नहीं",
        "नही",
        "मत",
        "मत करो",
        "रद्द करो",
        "रहने दो",
    }
    if normalized in exact_matches:
        return True

    phrase_matches = {
        "no thanks",
        "no please",
        "please cancel",
        "cancel it",
        "not now please",
        "I don't want to",
        "नहीं रद्द करो",
        "नहीं मत करो",
        "रद्द कर दो",
    }
    if normalized in phrase_matches:
        return True

    # Check for negation words — these must come before any affirmative substring check
    negation_markers = (
        "no",
        "don't",
        "do not",
        "not ",
        "cancel",
        "stop",
        "nahi",
        "mat",
        "नहीं",
        "नही",
        "मत",
        "रद्द",
        "रहने दो",
    )
    return any(marker in normalized for marker in negation_markers)


def format_confirmed_action_result(result: dict[str, Any]) -> str:
    if result.get("status") != "success":
        return result.get("error", "The action failed.")

    if result.get("invoice_name"):
        return (
            f"Sales Invoice {result['invoice_name']} created for {result.get('customer')}. "
            f"Grand total: ₹{result.get('grand_total')}."
        )

    if result.get("payment_name"):
        return (
            f"Payment of ₹{result.get('amount')} recorded against invoice {result.get('invoice_name')}. "
            f"Remaining outstanding: ₹{result.get('outstanding_after', 0)}."
        )

    if result.get("message"):
        return result["message"]

    if result.get("customer_name"):
        return f"Customer {result['customer_name']} created successfully."

    if result.get("item_code"):
        return f"Item {result['item_code']} created successfully."

    return "Done."


def json_result(result: dict[str, Any]) -> str:
    return json.dumps(result, indent=2)
