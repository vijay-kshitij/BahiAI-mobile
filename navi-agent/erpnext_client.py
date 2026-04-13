"""
ERPNext API Client
Handles authentication and all API calls to ERPNext.
This is what your AI agent uses to actually DO things in ERPNext.
"""

import json

import requests


class ERPNextClient:
    def __init__(self, base_url, username, password):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.session = requests.Session()
        self._login()

    def _login(self):
        """Login to ERPNext and store session cookies."""
        response = self.session.post(
            f"{self.base_url}/api/method/login",
            json={"usr": self.username, "pwd": self.password},
        )
        if response.status_code != 200:
            raise Exception(f"Failed to login to ERPNext: {response.text}")
        print("✅ Connected to ERPNext")

    def get_list(self, doctype, filters=None, fields=None, limit=20):
        """
        List documents of a given type.
        Example: get_list("Customer") returns all customers
        """
        params = {"limit_page_length": limit}
        if filters:
            params["filters"] = json.dumps(filters)
        if fields:
            params["fields"] = json.dumps(fields)

        response = self.session.get(
            f"{self.base_url}/api/resource/{doctype}",
            params=params,
        )
        response.raise_for_status()
        return response.json().get("data", [])

    def get_document(self, doctype, name):
        """
        Get a specific document by name.
        Example: get_document("Customer", "Rajesh Sharma")
        """
        response = self.session.get(
            f"{self.base_url}/api/resource/{doctype}/{name}",
        )
        response.raise_for_status()
        return response.json().get("data", {})

    def create_document(self, doctype, data):
        """
        Create a new document.
        Example: create_document("Customer", {"customer_name": "Rajesh Sharma", ...})
        """
        response = self.session.post(
            f"{self.base_url}/api/resource/{doctype}",
            json=data,
        )
        response.raise_for_status()
        return response.json().get("data", {})

    def update_document(self, doctype, name, data):
        """
        Update an existing document.
        Example: update_document("Customer", "Rajesh Sharma", {"customer_group": "Commercial"})
        """
        response = self.session.put(
            f"{self.base_url}/api/resource/{doctype}/{name}",
            json=data,
        )
        response.raise_for_status()
        return response.json().get("data", {})

    def delete_document(self, doctype, name):
        """
        Delete a document.
        Example: delete_document("Customer", "Rajesh Sharma")
        """
        response = self.session.delete(
            f"{self.base_url}/api/resource/{doctype}/{name}",
        )
        response.raise_for_status()
        return {"status": "success", "message": f"Deleted {doctype}: {name}"}

    def search(self, doctype, query, fields=None, limit=10):
        """
        Search for documents.
        Example: search("Customer", "Rajesh")
        """
        response = self.session.get(
            f"{self.base_url}/api/method/frappe.client.get_list",
            params={
                "doctype": doctype,
                "filters": json.dumps([["name", "like", f"%{query}%"]]),
                "fields": json.dumps(fields) if fields else '["name"]',
                "limit_page_length": limit,
            },
        )
        response.raise_for_status()
        return response.json().get("message", [])

    def get_stock_balance(self, item_code, warehouse=None, limit=20):
        """Return stock balances from Bin for a given item code."""
        filters = [["item_code", "=", item_code]]
        if warehouse:
            filters.append(["warehouse", "=", warehouse])

        return self.get_list(
            "Bin",
            filters=filters,
            fields=[
                "item_code",
                "warehouse",
                "actual_qty",
                "projected_qty",
                "reserved_qty",
                "ordered_qty",
                "planned_qty",
            ],
            limit=limit,
        )

    def get_low_stock_items(self, threshold=10, warehouse=None, limit=20):
        """Return bins at or below a threshold."""
        filters = [["actual_qty", "<=", threshold]]
        if warehouse:
            filters.append(["warehouse", "=", warehouse])

        return self.get_list(
            "Bin",
            filters=filters,
            fields=[
                "item_code",
                "warehouse",
                "actual_qty",
                "projected_qty",
                "ordered_qty",
            ],
            limit=limit,
        )
