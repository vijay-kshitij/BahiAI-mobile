import json
import re
from typing import Any


MODEL_NAME = "claude-sonnet-4-6"


TOOLS = [
    {
        "name": "list_documents",
        "description": (
            "List ERPNext documents with optional filters. Use for customers, items, sales invoices, "
            "suppliers, sales orders, and similar lookups. "
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
                    "description": "ERPNext document type such as Customer, Item, Sales Invoice, Supplier, Sales Order, or Purchase Order.",
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
        "description": "Get a specific ERPNext document by its exact name or ID.",
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
        "description": "Create a new inventory item in ERPNext.",
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
                "update_stock": {
                    "type": "boolean",
                    "description": "Set true only when the user clearly wants the invoice to also reduce stock.",
                    "default": False,
                },
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "item_code": {
                                "type": "string",
                                "description": "ERPNext item code or English/plain-language item name, such as SKU002 or Laptop. Do not send Devanagari item names into ERP records.",
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
        "name": "get_stock_balance",
        "description": "Get stock balances for an item code or plain-language item name, optionally in a specific warehouse.",
        "input_schema": {
            "type": "object",
            "properties": {
                "item_code": {"type": "string"},
                "warehouse": {"type": "string"},
            },
            "required": ["item_code"],
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
        "name": "list_low_stock_items",
        "description": "List inventory bins at or below a stock threshold. Use this for low stock or reorder-style questions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "threshold": {
                    "type": "number",
                    "default": 10,
                },
                "warehouse": {"type": "string"},
                "limit": {
                    "type": "integer",
                    "default": 20,
                },
            },
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
        "name": "navigate_to_page",
        "description": "Navigate the user to an ERPNext page such as a list view, form, dashboard, or settings page.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "ERPNext path starting with /app/. "
                        "For plain list or form views: /app/customer, /app/sales-invoice, /app/item, /app/sales-invoice/ACC-SINV-2026-00001. "
                        "For filtered list views append URL query params. Filter value format rules:\n"
                        "  - Equality: ?field=value  e.g. ?posting_date=2026-04-03  or  ?status=Unpaid\n"
                        "  - LIKE (contains): ?field=like,%value%  e.g. ?customer_name=like,%Priya%  or  ?item_name=like,%Laptop%\n"
                        "  - Comparison: ?field=operator,value  e.g. ?outstanding_amount=>,0  or  ?posting_date=>=,2026-04-01\n"
                        "Always use a comma between operator and value for non-equality filters. "
                        "Do not URL-encode the % signs in LIKE patterns — write them as literal % characters. "
                        "IMPORTANT: Filter values must always be in Latin/English script, never Devanagari. "
                        "If the user typed a name in Hindi/Devanagari (e.g. प्रिया), transliterate it to Latin (Priya) before using it as a filter value. "
                        "ERPNext stores all names in Latin script so Devanagari filter values will never match. "
                        "Only use field names that actually exist on the doctype."
                    ),
                },
                "description": {
                    "type": "string",
                    "description": "Short human description of the destination.",
                },
            },
            "required": ["path", "description"],
        },
    },
]


SYSTEM_PROMPT = """You are Navi, an AI copilot for SMB teams using ERPNext.
Your job is to help users complete invoicing and inventory work through chat.

You are especially good at:
- creating sales invoices
- answering stock questions
- finding customers, items, and invoices
- flagging low-stock items
- navigating users to the right ERPNext screen

## Navigation rule (highest priority)
Whenever the user says "show me", "open", "take me to", "go to", "list", or asks to see any
ERPNext list or page — ALWAYS call navigate_to_page immediately to take them there.
Do NOT just fetch and display results in the chat. Navigate first, then give a one-line
confirmation in chat (e.g. "Opening the customer list now.").

Examples that must trigger navigate_to_page:
- "show me the customer list" → navigate to /app/customer
- "open sales invoices" → navigate to /app/sales-invoice
- "show me unpaid invoices" → navigate to /app/sales-invoice?outstanding_amount=>,0
- "show me invoices from yesterday" → navigate to /app/sales-invoice?posting_date=<yesterday's date>
- "show me Priya Patel's invoices" → navigate to /app/sales-invoice?customer=Priya%20Patel
- "take me to the item list" → navigate to /app/item

For date-filtered navigation, always calculate the actual YYYY-MM-DD date from the
relative phrase before building the path.

For data questions that are NOT about seeing a list (e.g. "what is the stock balance for Laptop?",
"how many unpaid invoices do we have?", "what is the total of invoice ACC-001?") — answer in chat
using the appropriate tool without navigating.

## Other rules
- Keep replies short, practical, and business-friendly.
- Always use tools for factual ERPNext data. Never invent customers, items, balances, or invoices.
- For invoice creation and deletion, always get an explicit confirmation before the final action.
- When a tool result says confirmation is required, ask for confirmation in the user's current language and wait.
- Keep ERPNext master data and transaction fields in English/Latin script even when the user is speaking Hindi.
- If a user asks in Hindi, you may reply in Hindi, but customers, items, and created ERP records must use English/transliterated names, not Devanagari.
- Treat item references from users as human-friendly labels. The backend can resolve names like Laptop to real ERPNext item codes such as SKU002.
- After creating a document, navigate to it automatically and mention the document ID.
- If a request is ambiguous, ask only for the missing business detail.
"""


def doctype_to_route(doctype: str) -> str:
    return doctype.strip().lower().replace(" ", "-")


def document_path(doctype: str, name: str | None = None) -> str:
    base = f"/app/{doctype_to_route(doctype)}"
    if name:
        return f"{base}/{name}"
    return base


def tool_requires_confirmation(tool_name: str) -> bool:
    return tool_name in {"create_sales_invoice", "delete_document"}


def _summarize_line_items(items: list[dict[str, Any]]) -> list[str]:
    lines = []
    for item in items:
        item_code = item.get("item_code", "Unknown Item")
        qty = item.get("qty", 0)
        rate = item.get("rate")
        if rate is None:
            lines.append(f"{qty} x {item_code}")
        else:
            lines.append(f"{qty} x {item_code} @ {rate}")
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


def resolve_item_code(erp_client, query: str) -> tuple[str | None, str | None]:
    """Resolve an item name or code to ERPNext's actual item_code for demo use."""
    variants = _item_query_variants(query)
    items = erp_client.get_list(
        "Item",
        fields=["name", "item_code", "item_name", "stock_uom"],
        limit=200,
    )

    exact_match = next(
        (
            item
            for item in items
            for variant in variants
            if variant in {
                str(item.get("name", "")).lower(),
                str(item.get("item_code", "")).lower(),
                str(item.get("item_name", "")).lower(),
            }
        ),
        None,
    )
    if exact_match:
        return exact_match.get("item_code"), None

    partial_matches = [
        item
        for item in items
        if any(
            variant in str(item.get("item_code", "")).lower()
            or variant in str(item.get("item_name", "")).lower()
            for variant in variants
        )
    ]
    if len(partial_matches) == 1:
        return partial_matches[0].get("item_code"), None

    if len(partial_matches) > 1:
        match_list = ", ".join(
            f"{item.get('item_code')} ({item.get('item_name')})"
            for item in partial_matches[:5]
        )
        return None, f"Multiple items match '{query}': {match_list}"

    return None, f"No items found for '{query}'"


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
        if tool_input.get("update_stock"):
            parts.append("This invoice will also update stock.")
        return ". ".join(parts) + ". Please confirm whether I should create it."

    if tool_name == "delete_document":
        return (
            f"Delete {tool_input['doctype']} '{tool_input['name']}'. "
            "Please confirm whether I should delete it."
        )

    return "Please confirm this action."


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
                limit=tool_input.get("limit", 20),
            )
            return {"status": "success", "data": result}

        if tool_name == "get_document":
            result = erp_client.get_document(tool_input["doctype"], tool_input["name"])
            return {"status": "success", "data": result}

        if tool_name == "search_documents":
            if tool_input["doctype"].strip().lower() == "item":
                result = search_item_catalog(
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
                "path": document_path("Customer", result.get("name")),
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
                "path": document_path("Item", result.get("name")),
            }

        if tool_name == "create_sales_invoice":
            resolved_items = []
            for item in tool_input["items"]:
                resolved_code, error = resolve_item_code(erp_client, item["item_code"])
                if error:
                    return {"status": "error", "error": error}
                resolved_items.append(
                    {
                        "item_code": resolved_code,
                        "qty": item["qty"],
                        "rate": item.get("rate", 0),
                    }
                )

            data = {
                "customer": tool_input["customer"],
                "update_stock": tool_input.get("update_stock", False),
                "items": resolved_items,
            }
            if tool_input.get("due_date"):
                data["due_date"] = tool_input["due_date"]

            result = erp_client.create_document("Sales Invoice", data)
            return {
                "status": "success",
                "invoice_name": result.get("name"),
                "customer": result.get("customer"),
                "grand_total": result.get("grand_total"),
                "outstanding_amount": result.get("outstanding_amount"),
                "path": document_path("Sales Invoice", result.get("name")),
            }

        if tool_name == "get_stock_balance":
            resolved_code, error = resolve_item_code(erp_client, tool_input["item_code"])
            if error:
                return {"status": "error", "error": error}

            result = erp_client.get_stock_balance(
                resolved_code,
                warehouse=tool_input.get("warehouse"),
            )
            return {
                "status": "success",
                "item_code": resolved_code,
                "warehouse": tool_input.get("warehouse"),
                "data": result,
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
                ],
                limit=tool_input.get("limit", 10),
            )
            return {"status": "success", "data": result}

        if tool_name == "list_low_stock_items":
            result = erp_client.get_low_stock_items(
                threshold=tool_input.get("threshold", 10),
                warehouse=tool_input.get("warehouse"),
                limit=tool_input.get("limit", 20),
            )
            return {
                "status": "success",
                "threshold": tool_input.get("threshold", 10),
                "warehouse": tool_input.get("warehouse"),
                "data": result,
            }

        if tool_name == "delete_document":
            result = erp_client.delete_document(tool_input["doctype"], tool_input["name"])
            return {
                "status": "success",
                "message": result["message"],
            }

        if tool_name == "navigate_to_page":
            return {
                "status": "success",
                "action": "navigate",
                "path": tool_input["path"],
                "description": tool_input.get("description", ""),
            }

        return {"status": "error", "error": f"Unknown tool: {tool_name}"}

    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def extract_actions_from_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    if result.get("action") == "navigate" and result.get("path"):
        return [
            {
                "type": "navigate",
                "path": result["path"],
                "description": result.get("description", ""),
            }
        ]
    return []


def is_affirmative(text: str) -> bool:
    normalized = text.strip().lower()
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
    if normalized in phrase_matches:
        return True

    affirmative_tokens = (
        "yes",
        "confirm",
        "confirmed",
        "go ahead",
        "create",
        "do it",
        "please do",
        "okay",
        "ok",
        "sure",
        "haan",
        "han",
        "ji haan",
        "theek hai",
        "thik hai",
        "kar do",
        "kardo",
        "bana do",
        "banado",
        "हाँ",
        "हां",
        "ठीक है",
        "कर दो",
        "बना दो",
    )
    return any(token in normalized for token in affirmative_tokens)


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
        "नहीं",
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
        "don't create",
        "do not create",
        "not now please",
        "नहीं रद्द करो",
        "नहीं मत करो",
        "रद्द कर दो",
    }
    if normalized in phrase_matches:
        return True

    negative_tokens = (
        "no",
        "cancel",
        "stop",
        "don't",
        "do not",
        "not now",
        "nahi",
        "mat",
        "mat karo",
        "cancel karo",
        "rehne do",
        "नहीं",
        "नही",
        "मत",
        "रद्द",
        "रहने दो",
    )
    return any(token in normalized for token in negative_tokens)


def format_confirmed_action_result(result: dict[str, Any]) -> str:
    if result.get("status") != "success":
        return result.get("error", "The action failed.")

    if result.get("invoice_name"):
        return (
            f"Sales Invoice {result['invoice_name']} created for {result.get('customer')}. "
            f"Grand total: {result.get('grand_total')}. "
            "Would you like me to open it in ERPNext?"
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
