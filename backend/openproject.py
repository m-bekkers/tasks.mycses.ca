import json
import os
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx


class OpenProjectError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


class OpenProjectClient:
    def __init__(self, transport: httpx.BaseTransport | None = None):
        self.api_url = os.environ.get("OPENPROJECT_API_URL", "").rstrip("/")
        self.api_key = os.environ.get("OPENPROJECT_API_KEY", "")
        self.project_id = os.environ.get("OPENPROJECT_PROJECT_ID", "")
        self.type_id = os.environ.get("OPENPROJECT_TYPE_ID", "")
        self.transport = transport

    def _require_config(self):
        if not self.api_url or not self.api_key or not self.project_id:
            raise OpenProjectError(
                503,
                "OpenProject integration is not configured on the server.",
            )
        if not self.project_id.isdecimal():
            raise OpenProjectError(503, "OPENPROJECT_PROJECT_ID must be numeric.")
        if self.type_id and not self.type_id.isdecimal():
            raise OpenProjectError(503, "OPENPROJECT_TYPE_ID must be numeric.")

    def _request(self, method: str, path: str, **kwargs) -> Any:
        self._require_config()
        url = f"{self.api_url}/{path.lstrip('/')}"
        try:
            with httpx.Client(
                timeout=20.0,
                auth=("apikey", self.api_key),
                headers={"Accept": "application/hal+json"},
                transport=self.transport,
            ) as client:
                response = client.request(method, url, **kwargs)
        except httpx.HTTPError as error:
            raise OpenProjectError(502, "OpenProject API is unavailable.") from error

        if response.is_error:
            raise OpenProjectError(
                502,
                f"OpenProject API returned HTTP {response.status_code}.",
            )
        if response.status_code == 204 or not response.content:
            return {}
        try:
            return response.json()
        except ValueError as error:
            raise OpenProjectError(502, "OpenProject returned an invalid response.") from error

    @staticmethod
    def _elements(collection: dict) -> list[dict]:
        return collection.get("_embedded", {}).get("elements", [])

    @staticmethod
    def _linked_title(work_package: dict, name: str) -> str:
        return work_package.get("_links", {}).get(name, {}).get("title", "")

    @staticmethod
    def _linked_id(work_package: dict, name: str) -> int | None:
        href = work_package.get("_links", {}).get(name, {}).get("href", "")
        if not isinstance(href, str):
            return None
        match = re.search(r"/(\d+)(?:\?.*)?$", href)
        return int(match.group(1)) if match else None

    def _work_package_view(self, work_package: dict) -> dict:
        description = work_package.get("description") or {}
        item_id = work_package.get("id")
        parts = urlsplit(self.api_url)
        web_path = re.sub(r"/api/v3/?$", "", parts.path)
        web_base = urlunsplit((parts.scheme, parts.netloc, web_path, "", "")).rstrip("/")
        return {
            "id": item_id,
            "subject": work_package.get("subject", ""),
            "description": description.get("raw", "") if isinstance(description, dict) else str(description),
            "lock_version": work_package.get("lockVersion", 0),
            "status": self._linked_title(work_package, "status"),
            "status_id": self._linked_id(work_package, "status"),
            "priority": self._linked_title(work_package, "priority"),
            "priority_id": self._linked_id(work_package, "priority"),
            "assignee": self._linked_title(work_package, "assignee"),
            "assignee_id": self._linked_id(work_package, "assignee"),
            "url": f"{web_base}/work_packages/{item_id}",
        }

    def _project_types(self) -> list[dict]:
        response = self._request("GET", f"/projects/{self.project_id}/types")
        return self._elements(response)

    def create_request(self, *, subject: str, description: str) -> dict:
        type_id = self.type_id
        if not type_id:
            types = self._project_types()
            selected = next((item for item in types if item.get("isDefault")), None)
            selected = selected or (types[0] if types else None)
            type_id = str(selected.get("id")) if selected else ""
        if not type_id:
            raise OpenProjectError(
                503,
                "No work-package type is configured for the OpenProject project.",
            )

        created = self._request(
            "POST",
            f"/projects/{self.project_id}/work_packages",
            json={
                "subject": subject[:255],
                "description": {"format": "markdown", "raw": description},
                "_links": {
                    "project": {"href": f"/api/v3/projects/{self.project_id}"},
                    "type": {"href": f"/api/v3/types/{type_id}"},
                },
            },
        )
        return self._work_package_view(created)

    def _list_collection(self, path: str, *, params: dict | None = None) -> list[dict]:
        response = self._request("GET", path, params=params or {})
        return self._elements(response)

    def list_open_work_packages(self) -> dict:
        filters = json.dumps([{"status": {"operator": "o", "values": []}}])
        items = []
        offset = 1
        page_size = 100
        while True:
            page = self._list_collection(
                f"/projects/{self.project_id}/work_packages",
                params={"filters": filters, "offset": offset, "pageSize": page_size},
            )
            items.extend(self._work_package_view(item) for item in page)
            if len(page) < page_size:
                break
            offset += len(page)

        statuses = self._list_collection("/statuses")
        priorities = self._list_collection("/priorities")
        assignees = self._list_collection(
            f"/projects/{self.project_id}/available_assignees"
        )
        return {
            "items": items,
            "statuses": self._option_view(statuses),
            "priorities": self._option_view(priorities),
            "assignees": self._option_view(assignees),
        }

    @staticmethod
    def _option_view(elements: list[dict]) -> list[dict]:
        return [
            {"id": item.get("id"), "name": item.get("name", item.get("title", ""))}
            for item in elements
            if item.get("id") is not None
        ]

    def update_work_package(self, item_id: int, changes: dict) -> dict:
        lock_version = changes.pop("lock_version")
        payload: dict[str, Any] = {"lockVersion": lock_version}
        for field in ("subject", "description"):
            if field in changes:
                payload[field] = changes[field]
        if "status_id" in changes:
            payload.setdefault("_links", {})["status"] = {
                "href": f"/api/v3/statuses/{changes['status_id']}"
            }
        if "priority_id" in changes:
            payload.setdefault("_links", {})["priority"] = {
                "href": f"/api/v3/priorities/{changes['priority_id']}"
            }
        if "assignee_id" in changes:
            assignee_id = changes["assignee_id"]
            payload.setdefault("_links", {})["assignee"] = {
                "href": f"/api/v3/users/{assignee_id}" if assignee_id else None
            }

        updated = self._request("PATCH", f"/work_packages/{item_id}", json=payload)
        return self._work_package_view(updated)
