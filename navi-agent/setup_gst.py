"""
Setup script — creates GST tax accounts and templates on a fresh ERPNext instance.
Run once after ERPNext setup wizard is complete.

Usage: python3 setup_gst.py http://YOUR_IP:8080 Administrator admin
"""

import sys
import json
import requests

def main():
    if len(sys.argv) < 4:
        print("Usage: python3 setup_gst.py <erpnext_url> <username> <password>")
        sys.exit(1)

    base_url = sys.argv[1].rstrip("/")
    username = sys.argv[2]
    password = sys.argv[3]

    session = requests.Session()

    # Login
    r = session.post(f"{base_url}/api/method/login", json={"usr": username, "pwd": password})
    if r.status_code != 200:
        print(f"Login failed: {r.text}")
        sys.exit(1)
    print("Logged in.")

    # Get company abbreviation
    companies = session.get(f"{base_url}/api/resource/Company", params={"fields": json.dumps(["name", "abbr"])}).json().get("data", [])
    if not companies:
        print("No company found. Complete the setup wizard first.")
        sys.exit(1)

    company = companies[0]["name"]
    abbr = companies[0]["abbr"]
    print(f"Company: {company} ({abbr})")

    # Find parent account "Duties and Taxes"
    parent_accounts = session.get(f"{base_url}/api/resource/Account", params={
        "filters": json.dumps([["account_name", "=", "Duties and Taxes"], ["is_group", "=", 1], ["company", "=", company]]),
        "fields": json.dumps(["name"]),
    }).json().get("data", [])

    if not parent_accounts:
        print("Could not find 'Duties and Taxes' parent account.")
        sys.exit(1)

    parent_account = parent_accounts[0]["name"]
    print(f"Parent account: {parent_account}")

    # Create tax accounts
    tax_accounts = [
        {"account_name": "CGST", "suffix": f"CGST - {abbr}"},
        {"account_name": "SGST", "suffix": f"SGST - {abbr}"},
        {"account_name": "IGST", "suffix": f"IGST - {abbr}"},
    ]

    for acct in tax_accounts:
        existing = session.get(f"{base_url}/api/resource/Account", params={
            "filters": json.dumps([["account_name", "=", acct["account_name"]], ["company", "=", company]]),
            "fields": json.dumps(["name"]),
        }).json().get("data", [])

        if existing:
            print(f"  Account '{acct['suffix']}' already exists, skipping.")
            continue

        r = session.post(f"{base_url}/api/resource/Account", json={
            "account_name": acct["account_name"],
            "parent_account": parent_account,
            "company": company,
            "account_type": "Tax",
            "is_group": 0,
        })
        if r.ok:
            print(f"  Created account: {acct['suffix']}")
        else:
            print(f"  Failed to create {acct['suffix']}: {r.text[:200]}")

    # Create tax templates
    templates = [
        {"title": "GST 5%", "rate": 2.5},
        {"title": "GST 12%", "rate": 6.0},
        {"title": "GST 18%", "rate": 9.0},
        {"title": "GST 28%", "rate": 14.0},
    ]

    for tmpl in templates:
        template_name = f"{tmpl['title']} - {abbr}"
        existing = session.get(f"{base_url}/api/resource/Sales Taxes and Charges Template", params={
            "filters": json.dumps([["name", "=", template_name]]),
            "fields": json.dumps(["name"]),
        }).json().get("data", [])

        if existing:
            print(f"  Template '{template_name}' already exists, skipping.")
            continue

        r = session.post(f"{base_url}/api/resource/Sales Taxes and Charges Template", json={
            "title": tmpl["title"],
            "company": company,
            "taxes": [
                {
                    "charge_type": "On Net Total",
                    "account_head": f"CGST - {abbr}",
                    "rate": tmpl["rate"],
                    "description": f"CGST @ {tmpl['rate']}%",
                },
                {
                    "charge_type": "On Net Total",
                    "account_head": f"SGST - {abbr}",
                    "rate": tmpl["rate"],
                    "description": f"SGST @ {tmpl['rate']}%",
                },
            ],
        })
        if r.ok:
            print(f"  Created template: {template_name}")
        else:
            print(f"  Failed to create {template_name}: {r.text[:200]}")

    print("\nDone! GST tax setup complete.")


if __name__ == "__main__":
    main()
