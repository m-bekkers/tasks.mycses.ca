import json
import os
import unittest
from unittest.mock import patch

import httpx

from backend.openproject import OpenProjectClient, OpenProjectError


class OpenProjectClientTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(
            os.environ,
            {
                "OPENPROJECT_API_URL": "https://tasks.example/openproject/api/v3",
                "OPENPROJECT_API_KEY": "test-token",
                "OPENPROJECT_PROJECT_ID": "12",
                "OPENPROJECT_TYPE_ID": "4",
            },
            clear=False,
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def make_work_package(self, **overrides):
        item = {
            "id": 81,
            "subject": "CSCE - Technical support",
            "description": {"raw": "Please help"},
            "lockVersion": 3,
            "_links": {
                "self": {"href": "/api/v3/work_packages/81"},
                "status": {"href": "/api/v3/statuses/1", "title": "New"},
                "priority": {"href": "/api/v3/priorities/2", "title": "Normal"},
                "assignee": {"href": "/api/v3/users/7", "title": "Admin User"},
            },
        }
        item.update(overrides)
        return item

    def test_create_sets_project_and_type_and_authenticates_with_api_key(self):
        def handle(request):
            self.assertEqual(request.headers["accept"], "application/hal+json")
            self.assertEqual(request.headers["authorization"], "Basic YXBpa2V5OnRlc3QtdG9rZW4=")
            self.assertEqual(
                request.url.path,
                "/openproject/api/v3/projects/12/work_packages",
            )
            payload = json.loads(request.content)
            self.assertEqual(payload["subject"], "CSCE - Technical support")
            self.assertEqual(
                payload["_links"],
                {
                    "project": {"href": "/api/v3/projects/12"},
                    "type": {"href": "/api/v3/types/4"},
                },
            )
            return httpx.Response(201, json=self.make_work_package())

        client = OpenProjectClient(transport=httpx.MockTransport(handle))
        result = client.create_request(
            subject="CSCE - Technical support",
            description="Please help",
        )

        self.assertEqual(result["id"], 81)
        self.assertEqual(result["status"], "New")
        self.assertEqual(result["url"], "https://tasks.example/openproject/work_packages/81")

    def test_open_work_package_list_and_options(self):
        def handle(request):
            if request.url.path.endswith("/projects/12/work_packages"):
                filters = json.loads(request.url.params["filters"])
                self.assertEqual(filters, [{"status": {"operator": "o", "values": []}}])
                return httpx.Response(
                    200,
                    json={"_embedded": {"elements": [self.make_work_package()]}},
                )
            if request.url.path.endswith("/statuses"):
                return httpx.Response(200, json={"_embedded": {"elements": [{"id": 1, "name": "New"}]}})
            if request.url.path.endswith("/priorities"):
                return httpx.Response(200, json={"_embedded": {"elements": [{"id": 2, "name": "Normal"}]}})
            if request.url.path.endswith("/available_assignees"):
                return httpx.Response(200, json={"_embedded": {"elements": [{"id": 7, "name": "Admin User"}]}})
            self.fail(f"Unexpected OpenProject API path: {request.url.path}")

        client = OpenProjectClient(transport=httpx.MockTransport(handle))
        result = client.list_open_work_packages()

        self.assertEqual([item["id"] for item in result["items"]], [81])
        self.assertEqual(result["statuses"], [{"id": 1, "name": "New"}])
        self.assertEqual(result["priorities"], [{"id": 2, "name": "Normal"}])
        self.assertEqual(result["assignees"], [{"id": 7, "name": "Admin User"}])

    def test_update_sends_lock_version_and_link_changes(self):
        def handle(request):
            self.assertEqual(request.method, "PATCH")
            self.assertEqual(request.url.path, "/openproject/api/v3/work_packages/81")
            payload = json.loads(request.content)
            self.assertEqual(payload["lockVersion"], 3)
            self.assertEqual(payload["subject"], "Updated subject")
            self.assertEqual(payload["_links"]["status"]["href"], "/api/v3/statuses/5")
            self.assertEqual(payload["_links"]["priority"]["href"], "/api/v3/priorities/2")
            self.assertIsNone(payload["_links"]["assignee"]["href"])
            return httpx.Response(200, json=self.make_work_package(subject="Updated subject"))

        client = OpenProjectClient(transport=httpx.MockTransport(handle))
        result = client.update_work_package(
            81,
            {
                "lock_version": 3,
                "subject": "Updated subject",
                "status_id": 5,
                "priority_id": 2,
                "assignee_id": None,
            },
        )

        self.assertEqual(result["subject"], "Updated subject")

    def test_missing_configuration_fails_closed(self):
        with patch.dict(os.environ, {"OPENPROJECT_API_KEY": "", "OPENPROJECT_PROJECT_ID": ""}):
            with self.assertRaises(OpenProjectError) as raised:
                OpenProjectClient().list_open_work_packages()
        self.assertEqual(raised.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
