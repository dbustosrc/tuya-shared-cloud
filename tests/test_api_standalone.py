"""Standalone tests for the Tuya API layer without Home Assistant installed."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
COMPONENT = ROOT / "custom_components" / "tuya_shared_cloud"
PACKAGE = "tuya_shared_cloud_standalone"


class _ClientError(Exception):
    pass


class _ClientTimeout:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


aiohttp_stub = types.ModuleType("aiohttp")
aiohttp_stub.ClientSession = object
aiohttp_stub.ClientError = _ClientError
aiohttp_stub.ClientTimeout = _ClientTimeout
sys.modules.setdefault("aiohttp", aiohttp_stub)

package = types.ModuleType(PACKAGE)
package.__path__ = [str(COMPONENT)]
sys.modules[PACKAGE] = package


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"{PACKAGE}.{name}", COMPONENT / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


const = _load("const")
models = _load("models")
api = _load("api")


class _Response:
    def __init__(self, payload):
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        return None

    async def json(self, content_type=None):
        return self.payload


class _Session:
    def __init__(self):
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        if "/v1.0/token?" in url:
            return _Response(
                {
                    "success": True,
                    "result": {"access_token": "temporary", "expire_time": 7200},
                }
            )
        if "from=sharing" in url:
            return _Response(
                {
                    "success": True,
                    "result": [
                        {
                            "id": "shared-device",
                            "name": "Shared garage",
                            "category": "ckmkzq",
                            "online": True,
                            "status": [{"code": "doorcontact_state", "value": True}],
                        }
                    ],
                }
            )
        if url.endswith("/v1.0/open-hub/access/config"):
            return _Response(
                {
                    "success": True,
                    "result": {
                        "url": "ssl://mqtt.example.test:8883",
                        "client_id": "mqtt-client",
                        "username": "mqtt-user",
                        "password": "12345678" + "abcdefghijklmnop" + "87654321",
                        "source_topic": {"device": "cloud/device/report"},
                    },
                }
            )
        raise AssertionError(f"Unexpected URL: {url}")


class ApiTests(unittest.TestCase):
    def test_canonical_empty_get(self):
        self.assertEqual(
            api.TuyaCloudClient.build_string_to_sign("GET", "/v1.0/test"),
            "GET\n"
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
            "\n\n/v1.0/test",
        )

    def test_function_values_are_decoded(self):
        function = models.TuyaFunction.from_api(
            {
                "code": "door_control_1",
                "name": "door control 1",
                "type": "Enum",
                "values": '{"range":["open","close"]}',
            }
        )
        self.assertEqual(function.values["range"], ["open", "close"])

    def test_shared_inventory_only_and_token_reuse(self):
        async def run():
            session = _Session()
            client = api.TuyaCloudClient(
                session, "https://openapi.tuyaus.com", "client", "secret"
            )
            first = await client.async_get_shared_devices("uid")
            second = await client.async_get_shared_devices("uid")
            self.assertEqual(first[0].device_id, "shared-device")
            self.assertTrue(first[0].status["doorcontact_state"])
            self.assertEqual(second[0].name, "Shared garage")
            self.assertEqual(
                sum("/v1.0/token?" in request[1] for request in session.requests),
                1,
            )
            inventory_urls = [
                request[1]
                for request in session.requests
                if "/users/uid/devices" in request[1]
            ]
            self.assertEqual(len(inventory_urls), 2)
            self.assertTrue(all("from=sharing" in url for url in inventory_urls))

        asyncio.run(run())

    def test_openmq_permission_error_is_actionable(self):
        async def run():
            client = api.TuyaCloudClient(
                _Session(), "https://openapi.tuyaus.com", "client", "secret"
            )

            async def denied(*args, **kwargs):
                raise api.TuyaCloudError("1106: permission deny")

            client._async_request = denied
            with self.assertRaises(api.TuyaMQPermissionError) as raised:
                await client.async_get_mq_config("uid", "link")
            self.assertIn("Device Status Notification", str(raised.exception))

        asyncio.run(run())

    def test_openmq_uses_smart_home_endpoint_and_encryption(self):
        async def run():
            session = _Session()
            client = api.TuyaCloudClient(
                session, "https://openapi.tuyaus.com", "client", "secret"
            )
            config = await client.async_get_mq_config("uid", "tscprobe")
            method, url, kwargs = session.requests[-1]
            self.assertEqual(method, "POST")
            self.assertEqual(
                url, "https://openapi.tuyaus.com/v1.0/open-hub/access/config"
            )
            self.assertEqual(
                kwargs["data"],
                b'{"uid":"uid","link_id":"tscprobe","link_type":"mqtt","topics":"device","msg_encrypted_version":"1.0"}',
            )
            self.assertEqual(config["_msg_encrypted_version"], "1.0")

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
