import base64
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def encode(value):
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def decode(value):
    return base64.b64decode(value).decode("utf-8")


class EtcdStore:
    def __init__(self, endpoint):
        self.endpoint = endpoint.rstrip("/")

    def call(self, path, data):
        request = Request(
            self.endpoint + path,
            data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urlopen(request, timeout=5) as response:
                result = json.load(response)
        except (HTTPError, URLError, OSError, ValueError) as error:
            raise RuntimeError(
                "Database request failed; a write outcome may be unknown"
            ) from error

        if "error" in result:
            raise RuntimeError(f"Database error: {result['error']}")

        return result

    def get(self, key):
        result = self.call(
            "/v3/kv/range",
            {
                "key": encode(key),
                "serializable": False,
            },
        )

        items = result.get("kvs", [])

        if not items:
            return None

        item = items[0]

        return {
            "value": decode(item["value"]),
            "revision": int(item["mod_revision"]),
        }

    @staticmethod
    def missing(key):
        return {
            "key": encode(key),
            "target": "VERSION",
            "result": "EQUAL",
            "version": "0",
        }

    @staticmethod
    def unchanged(key, revision):
        return {
            "key": encode(key),
            "target": "MOD",
            "result": "EQUAL",
            "mod_revision": str(revision),
        }

    @staticmethod
    def put(key, value):
        return {
            "request_put": {
                "key": encode(key),
                "value": encode(value),
            }
        }

    def transaction(self, comparisons, operations):
        result = self.call(
            "/v3/kv/txn",
            {
                "compare": comparisons,
                "success": operations,
                "failure": [],
            },
        )

        return result.get("succeeded", False)
    def grant_lease(self, ttl):
        result = self.call("/v3/lease/grant", {"TTL": str(ttl)})

        if "ID" not in result:
            raise RuntimeError("Database did not return a lease ID")

        return result["ID"]

    @staticmethod
    def equals(key, value):
        return {
            "key": encode(key),
            "target": "VALUE",
            "result": "EQUAL",
            "value": encode(value),
        }

    @staticmethod
    def put_with_lease(key, value, lease_id):
        operation = EtcdStore.put(key, value)
        operation["request_put"]["lease"] = str(lease_id)
        return operation
