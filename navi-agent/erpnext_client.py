"""
ERPNext API Client
Handles authentication and all API calls to ERPNext.
"""

import json
from urllib.parse import quote

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
        print("Connected to ERPNext")

    def _resource_url(self, doctype, name=None):
        """Build a properly encoded resource URL."""
        url = f"{self.base_url}/api/resource/{quote(doctype, safe='')}"
        if name:
            url += f"/{quote(str(name), safe='')}"
        return url

    def get_list(self, doctype, filters=None, fields=None, limit=20, order_by=None):
        """List documents of a given type."""
        params = {"limit_page_length": limit}
        if filters:
            params["filters"] = json.dumps(filters)
        if fields:
            params["fields"] = json.dumps(fields)
        if order_by:
            params["order_by"] = order_by

        response = self.session.get(self._resource_url(doctype), params=params)
        response.raise_for_status()
        return response.json().get("data", [])

    def get_document(self, doctype, name):
        """Get a specific document by name."""
        response = self.session.get(self._resource_url(doctype, name))
        response.raise_for_status()
        return response.json().get("data", {})

    def create_document(self, doctype, data):
        """Create a new document."""
        response = self.session.post(self._resource_url(doctype), json=data)
        response.raise_for_status()
        return response.json().get("data", {})

    def update_document(self, doctype, name, data):
        """Update an existing document."""
        response = self.session.put(self._resource_url(doctype, name), json=data)
        response.raise_for_status()
        return response.json().get("data", {})

    def delete_document(self, doctype, name):
        """Delete a document."""
        response = self.session.delete(self._resource_url(doctype, name))
        response.raise_for_status()
        return {"status": "success", "message": f"Deleted {doctype}: {name}"}

    def submit_document(self, doctype, name):
        """Submit a draft document (changes docstatus from 0 to 1)."""
        doc = self.get_document(doctype, name)
        doc["docstatus"] = 1
        if doc.get("posting_date"):
            doc["set_posting_time"] = 1
        response = self.session.post(
            f"{self.base_url}/api/method/frappe.client.submit",
            json={"doc": doc},
        )
        if not response.ok:
            error_msg = response.text
            try:
                error_data = response.json()
                server_messages = error_data.get("_server_messages")
                if server_messages:
                    import json as _json
                    msgs = _json.loads(server_messages)
                    if msgs:
                        inner = _json.loads(msgs[0]) if isinstance(msgs[0], str) else msgs[0]
                        error_msg = inner.get("message", error_msg)
            except Exception:
                pass
            raise Exception(f"Submit failed: {error_msg}")
        return response.json().get("data", response.json().get("message", {}))

    def cancel_document(self, doctype, name):
        """Cancel a submitted document (changes docstatus from 1 to 2)."""
        doc = self.get_document(doctype, name)
        doc["docstatus"] = 2
        response = self.session.post(
            f"{self.base_url}/api/method/frappe.client.cancel",
            json={"doctype": doctype, "name": name},
        )
        if not response.ok:
            error_msg = response.text
            try:
                error_data = response.json()
                server_messages = error_data.get("_server_messages")
                if server_messages:
                    import json as _json
                    msgs = _json.loads(server_messages)
                    if msgs:
                        inner = _json.loads(msgs[0]) if isinstance(msgs[0], str) else msgs[0]
                        error_msg = inner.get("message", error_msg)
            except Exception:
                pass
            raise Exception(f"Cancel failed: {error_msg}")
        return response.json().get("data", response.json().get("message", {}))

    def amend_document(self, doctype, name):
        """Amend a cancelled document — creates a new draft copy."""
        doc = self.get_document(doctype, name)
        doc["docstatus"] = 0
        doc["amended_from"] = name
        doc.pop("name", None)
        if doc.get("posting_date"):
            doc["set_posting_time"] = 1
        response = self.session.post(
            self._resource_url(doctype),
            json=doc,
        )
        if not response.ok:
            error_msg = response.text
            try:
                error_data = response.json()
                server_messages = error_data.get("_server_messages")
                if server_messages:
                    import json as _json
                    msgs = _json.loads(server_messages)
                    if msgs:
                        inner = _json.loads(msgs[0]) if isinstance(msgs[0], str) else msgs[0]
                        error_msg = inner.get("message", error_msg)
            except Exception:
                pass
            raise Exception(f"Amend failed: {error_msg}")
        return response.json().get("data", {})

    def search(self, doctype, query, fields=None, limit=10):
        """Search for documents by partial name."""
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
