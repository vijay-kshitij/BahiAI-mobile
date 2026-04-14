"""
Seed script — populates ERPNext with demo data for the Navi invoicing MVP.
Run once after a fresh ERPNext setup:

    source venv/bin/activate
    python seed.py
"""

import os
import sys
import time

from dotenv import load_dotenv

from erpnext_client import ERPNextClient

load_dotenv()


def main():
    client = ERPNextClient(
        base_url=os.getenv("ERPNEXT_URL", "http://localhost:8080"),
        username=os.getenv("ERPNEXT_USERNAME", "Administrator"),
        password=os.getenv("ERPNEXT_PASSWORD", "admin"),
    )

    # ── Customers ──
    customers = [
        {"customer_name": "Priya Patel", "customer_type": "Individual", "mobile_no": "9876543210"},
        {"customer_name": "Rajesh Sharma", "customer_type": "Individual", "mobile_no": "9876543211"},
        {"customer_name": "Grant Plastics Ltd", "customer_type": "Company"},
        {"customer_name": "Amit Shah", "customer_type": "Individual", "mobile_no": "9876543212"},
        {"customer_name": "Sunita Verma", "customer_type": "Individual", "mobile_no": "9876543213"},
        {"customer_name": "TechVista Solutions", "customer_type": "Company"},
    ]

    print("Creating customers...")
    for c in customers:
        data = {
            "customer_name": c["customer_name"],
            "customer_type": c["customer_type"],
            "customer_group": "Individual" if c["customer_type"] == "Individual" else "Commercial",
            "territory": "India",
        }
        if c.get("mobile_no"):
            data["mobile_no"] = c["mobile_no"]
        try:
            client.create_document("Customer", data)
            print(f"  + {c['customer_name']}")
        except Exception as e:
            if "DuplicateEntryError" in str(e) or "already exists" in str(e).lower():
                print(f"  = {c['customer_name']} (already exists)")
            else:
                print(f"  ! {c['customer_name']}: {e}")

    # ── Items ──
    items = [
        {"item_code": "LAPTOP", "item_name": "Laptop", "standard_rate": 75000},
        {"item_code": "MOUSE", "item_name": "Wireless Mouse", "standard_rate": 500},
        {"item_code": "KEYBOARD", "item_name": "Mechanical Keyboard", "standard_rate": 3500},
        {"item_code": "MONITOR", "item_name": "27-inch Monitor", "standard_rate": 22000},
        {"item_code": "HEADSET", "item_name": "Wireless Headset", "standard_rate": 4500},
        {"item_code": "WEBCAM", "item_name": "HD Webcam", "standard_rate": 2500},
        {"item_code": "CHARGER", "item_name": "USB-C Charger", "standard_rate": 1500},
        {"item_code": "CABLE-HDMI", "item_name": "HDMI Cable", "standard_rate": 350},
    ]

    print("\nCreating items...")
    for item in items:
        data = {
            "item_code": item["item_code"],
            "item_name": item["item_name"],
            "item_group": "Products",
            "stock_uom": "Nos",
            "standard_rate": item["standard_rate"],
            "is_stock_item": 0,  # service items for invoicing demo
        }
        try:
            client.create_document("Item", data)
            print(f"  + {item['item_code']} ({item['item_name']}) @ {item['standard_rate']}")
        except Exception as e:
            if "DuplicateEntryError" in str(e) or "already exists" in str(e).lower():
                print(f"  = {item['item_code']} (already exists)")
            else:
                print(f"  ! {item['item_code']}: {e}")

    # ── Sales Invoices ──
    from datetime import date, timedelta
    today = date.today()

    invoices = [
        {
            "customer": "Priya Patel",
            "posting_date": (today - timedelta(days=5)).isoformat(),
            "due_date": (today + timedelta(days=25)).isoformat(),
            "items": [
                {"item_code": "LAPTOP", "qty": 2, "rate": 75000},
                {"item_code": "MOUSE", "qty": 2, "rate": 500},
            ],
        },
        {
            "customer": "Rajesh Sharma",
            "posting_date": (today - timedelta(days=10)).isoformat(),
            "due_date": (today - timedelta(days=2)).isoformat(),  # overdue
            "items": [
                {"item_code": "MONITOR", "qty": 1, "rate": 22000},
                {"item_code": "KEYBOARD", "qty": 1, "rate": 3500},
            ],
        },
        {
            "customer": "Grant Plastics Ltd",
            "posting_date": (today - timedelta(days=3)).isoformat(),
            "due_date": (today + timedelta(days=27)).isoformat(),
            "items": [
                {"item_code": "LAPTOP", "qty": 5, "rate": 72000},
                {"item_code": "HEADSET", "qty": 5, "rate": 4500},
                {"item_code": "WEBCAM", "qty": 5, "rate": 2500},
            ],
        },
        {
            "customer": "Amit Shah",
            "posting_date": (today - timedelta(days=1)).isoformat(),
            "due_date": (today + timedelta(days=29)).isoformat(),
            "items": [
                {"item_code": "CHARGER", "qty": 3, "rate": 1500},
                {"item_code": "CABLE-HDMI", "qty": 3, "rate": 350},
            ],
        },
    ]

    print("\nCreating sales invoices...")
    created_invoices = []
    for inv in invoices:
        try:
            result = client.create_document("Sales Invoice", inv)
            name = result.get("name")
            print(f"  + {name} for {inv['customer']}")
            # Submit the invoice so it posts to the ledger
            if name:
                client.submit_document("Sales Invoice", name)
                print(f"    Submitted {name}")
                created_invoices.append({"name": name, "customer": inv["customer"]})
        except Exception as e:
            print(f"  ! Invoice for {inv['customer']}: {e}")

    # ── Record a payment for the first invoice (Priya's) to show mixed statuses ──
    if created_invoices:
        time.sleep(1)  # give ERPNext a moment to process
        first = created_invoices[0]
        print(f"\nRecording partial payment for {first['name']}...")
        try:
            inv_doc = client.get_document("Sales Invoice", first["name"])
            outstanding = float(inv_doc.get("outstanding_amount", 0))
            partial = round(outstanding * 0.5)
            if partial > 0:
                pe = client.create_document("Payment Entry", {
                    "payment_type": "Receive",
                    "party_type": "Customer",
                    "party": first["customer"],
                    "paid_amount": partial,
                    "received_amount": partial,
                    "mode_of_payment": "Cash",
                    "company": inv_doc.get("company"),
                    "references": [
                        {
                            "reference_doctype": "Sales Invoice",
                            "reference_name": first["name"],
                            "allocated_amount": partial,
                        }
                    ],
                })
                pe_name = pe.get("name")
                if pe_name:
                    client.submit_document("Payment Entry", pe_name)
                    print(f"  + Payment {pe_name}: {partial} against {first['name']}")
        except Exception as e:
            print(f"  ! Payment failed: {e}")

    print("\nDone! Your ERPNext now has demo data for the Navi invoicing demo.")
    print("  - 6 customers")
    print("  - 8 items")
    print(f"  - {len(created_invoices)} invoices (1 partly paid, 1 overdue)")


if __name__ == "__main__":
    main()
