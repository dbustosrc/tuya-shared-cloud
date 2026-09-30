"""Standalone OpenMQ tests without Home Assistant or a real broker."""

from __future__ import annotations

import asyncio
import base64
import importlib.util
import json
import sys
import threading
import types
import unittest
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = Path(__file__).parents[1]
COMPONENT = ROOT / "custom_components" / "tuya_shared_cloud"
PACKAGE = "tuya_shared_cloud_push_tests"


class _ClientError(Exception):
    pass


aiohttp_stub = types.ModuleType("aiohttp")
aiohttp_stub.ClientSession = object
aiohttp_stub.ClientError = _ClientError
aiohttp_stub.ClientTimeout = object
sys.modules.setdefault("aiohttp", aiohttp_stub)


class _FakeReason:
    def __init__(self, value=0, is_failure=False):
        self.value = value
        self.is_failure = is_failure


class _FakeMQTTClient:
    instances: ClassVar[list] = []

    def __init__(self, callback_version, client_id, protocol):
        self.callback_version = callback_version
        self.client_id = client_id
        self.protocol = protocol
        self.subscriptions = []
        self.stopped = False
        self.on_connect = None
        self.on_disconnect = None
        self.on_message = None
        self.on_subscribe = None
        self._next_mid = 1
        type(self).instances.append(self)

    def username_pw_set(self, username, password):
        self.username = username
        self.password = password

    def reconnect_delay_set(self, **kwargs):
        self.reconnect_delay = kwargs

    def tls_set(self):
        self.tls = True
        self.tls_thread_id = threading.get_ident()

    def connect_async(self, host, port, keepalive):
        self.connection = (host, port, keepalive)

    def subscribe(self, topic):
        mid = self._next_mid
        self._next_mid += 1
        self.subscriptions.append((topic, mid))
        return 0, mid

    def loop_start(self):
        self.on_connect(self, None, None, _FakeReason(), None)
        for _, mid in self.subscriptions:
            self.on_subscribe(self, None, mid, [_FakeReason()], None)

    def disconnect(self):
        return None

    def loop_stop(self):
        self.stopped = True


paho_stub = types.ModuleType("paho")
paho_mqtt_stub = types.ModuleType("paho.mqtt")
paho_client_stub = types.ModuleType("paho.mqtt.client")
paho_client_stub.CallbackAPIVersion = types.SimpleNamespace(VERSION2=2)
paho_client_stub.MQTTv311 = 4
paho_client_stub.MQTT_ERR_SUCCESS = 0
paho_client_stub.Client = _FakeMQTTClient
paho_mqtt_stub.client = paho_client_stub
paho_stub.mqtt = paho_mqtt_stub
sys.modules.setdefault("paho", paho_stub)
sys.modules.setdefault("paho.mqtt", paho_mqtt_stub)
sys.modules.setdefault("paho.mqtt.client", paho_client_stub)

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
push = _load("push")


class _FakeAPI:
    def __init__(self):
        self.calls = []

    async def async_get_mq_config(self, uid, link_id):
        self.calls.append((uid, link_id))
        return {
            "url": "ssl://mqtt.example.test:8883",
            "client_id": "client",
            "username": "user",
            "password": "12345678" + "abcdefghijklmnop" + "87654321",
            "source_topic": {"device": "cloud/device/report"},
            "expire_time": 300,
            "_msg_encrypted_version": "1.0",
        }


class PushTests(unittest.TestCase):
    def test_failed_renewal_retries_with_old_subscription_still_active(self):
        class FailingAPI(_FakeAPI):
            fail_once = False

            async def async_get_mq_config(self, uid, link_id):
                if self.fail_once:
                    self.fail_once = False
                    raise api.TuyaCloudConnectionError("private URL and credentials")
                return await super().async_get_mq_config(uid, link_id)

        async def run():
            cloud = FailingAPI()
            client = push.TuyaOpenMQClient(
                cloud,
                "uid",
                lambda payload: None,
                lambda *args: None,
                mqtt_factory=_FakeMQTTClient,
            )
            await client.async_start()
            cloud.fail_once = True
            with patch.object(push, "PUSH_RETRY_MIN", 0):
                with self.assertLogs(push._LOGGER, level="WARNING") as captured:
                    await client._async_renew_after(0)
                self.assertTrue(client.metrics.subscribed)
                self.assertTrue(client.metrics.renewing)
                await client._retry_task
            self.assertEqual(client.metrics.renewal_attempts, 2)
            self.assertEqual(client.metrics.renewal_failures, 1)
            self.assertEqual(client.metrics.last_renewal_result, "success")
            self.assertFalse(client.metrics.renewing)
            self.assertNotIn("private URL", repr(captured.output))
            await client.async_stop()

        asyncio.run(run())

    def test_disconnect_retries_and_unload_cancels_background_tasks(self):
        async def run():
            cloud = _FakeAPI()
            client = push.TuyaOpenMQClient(
                cloud,
                "uid",
                lambda payload: None,
                lambda *args: None,
                mqtt_factory=_FakeMQTTClient,
            )
            await client.async_start()
            mqtt_client = client._mqtt_client
            with patch.object(push, "PUSH_RETRY_MIN", 0):
                mqtt_client.on_disconnect(mqtt_client, None, None, _FakeReason(), None)
                await asyncio.sleep(0)
                retry_task = client._retry_task
                self.assertFalse(client.metrics.subscribed)
                await retry_task
            self.assertEqual(len(cloud.calls), 2)
            self.assertTrue(client.metrics.subscribed)
            renewal_task = client._renew_task
            await client.async_stop()
            self.assertTrue(renewal_task.done())
            self.assertFalse(client.running)
            self.assertIsNone(client._retry_task)
            self.assertIsNone(client._mqtt_client)

        asyncio.run(run())

    def test_partial_subscription_failure_never_marks_push_healthy(self):
        class MultiTopicAPI(_FakeAPI):
            async def async_get_mq_config(self, uid, link_id):
                config = await super().async_get_mq_config(uid, link_id)
                config["source_topic"] = ["cloud/accepted", "cloud/rejected"]
                return config

        class RejectedClient(_FakeMQTTClient):
            def subscribe(self, topic):
                if topic == "cloud/rejected":
                    return 1, 0
                return super().subscribe(topic)

        async def run():
            client = push.TuyaOpenMQClient(
                MultiTopicAPI(),
                "uid",
                lambda payload: None,
                lambda *args: None,
                mqtt_factory=RejectedClient,
            )
            with (
                patch.object(push, "PUSH_CONNECT_TIMEOUT", 0.01),
                self.assertRaises(TimeoutError),
            ):
                await client.async_start()
            self.assertFalse(client.metrics.subscribed)
            self.assertEqual(client.metrics.last_error_reason, "subscription")
            await client.async_stop()

        asyncio.run(run())

    def test_reconciliation_is_slow_by_default(self):
        self.assertGreaterEqual(const.DEFAULT_SCAN_INTERVAL, 300)
        manifest = json.loads((COMPONENT / "manifest.json").read_text())
        self.assertEqual(manifest["iot_class"], "cloud_push")

    def test_shared_device_filter_and_status_decode(self):
        payload = {
            "protocol": 4,
            "data": {
                "devId": "shared-device",
                "status": [{"code": "doorcontact_state", "value": True}],
            },
        }
        update = push.parse_push_update(payload, {"shared-device"})
        self.assertIsNotNone(update)
        self.assertTrue(update.status["doorcontact_state"])
        self.assertIsNone(push.parse_push_update(payload, {"owned-device"}))

    def test_online_event_is_supported(self):
        update = push.parse_push_update(
            {
                "protocol": 20,
                "data": {"devId": "shared-device", "bizCode": "offline"},
            },
            {"shared-device"},
        )
        self.assertIs(update.online, False)

    def test_aes_ecb_smart_home_openmq_message_decode(self):
        password = "12345678" + "abcdefghijklmnop" + "87654321"
        inner = {
            "protocol": 4,
            "data": {
                "devId": "shared-device",
                "status": [{"code": "doorcontact_state", "value": False}],
            },
        }
        encoded = json.dumps(inner, separators=(",", ":")).encode()
        padder = padding.PKCS7(128).padder()
        padded = padder.update(encoded) + padder.finalize()
        encryptor = Cipher(
            algorithms.AES(password[8:24].encode()), modes.ECB()
        ).encryptor()
        encrypted = encryptor.update(padded) + encryptor.finalize()
        envelope = json.dumps(
            {"t": 1789598603010, "data": base64.b64encode(encrypted).decode()}
        ).encode()
        decoded = push.decode_openmq_message(envelope, password)
        self.assertEqual(decoded["data"], inner)

    def test_aes_gcm_custom_openmq_message_decode(self):
        password = "12345678" + "abcdefghijklmnop" + "87654321"
        timestamp = 1789598603010
        inner = {
            "protocol": 4,
            "data": {
                "devId": "shared-device",
                "status": [{"code": "doorcontact_state", "value": False}],
            },
        }
        iv = b"123456789012"
        ciphertext_and_tag = AESGCM(password[8:24].encode()).encrypt(
            iv,
            json.dumps(inner, separators=(",", ":")).encode(),
            str(timestamp).encode(),
        )
        encrypted = len(iv).to_bytes(4, "big") + iv + ciphertext_and_tag
        envelope = json.dumps(
            {"t": timestamp, "data": base64.b64encode(encrypted).decode()}
        ).encode()
        decoded = push.decode_openmq_message(envelope, password, "2.0")
        self.assertEqual(decoded["data"], inner)

    def test_delivery_ratio_exposes_polling_fallback_usage(self):
        metrics = push.TuyaPushMetrics(
            datapoints_applied=9, reconciliation_corrections=1
        )
        self.assertEqual(metrics.push_delivery_ratio, 0.9)

    def test_transport_uses_injected_metrics(self):
        metrics = push.TuyaPushMetrics(reconciliation_runs=1)
        client = push.TuyaOpenMQClient(
            _FakeAPI(),
            "uid",
            lambda payload: None,
            lambda connected, subscribed: None,
            mqtt_factory=_FakeMQTTClient,
            metrics=metrics,
        )
        self.assertIs(client.metrics, metrics)
        self.assertEqual(client.metrics.reconciliation_runs, 1)

    def test_new_push_wins_over_in_flight_poll(self):
        polled = {"shared": {"doorcontact_state": False, "switch_1": False}}
        current = {"shared": {"doorcontact_state": True, "switch_1": False}}
        result = push.preserve_newer_push_values(
            polled,
            current,
            {("shared", "doorcontact_state"): 11.0},
            poll_started=10.0,
        )
        self.assertTrue(result["shared"]["doorcontact_state"])
        self.assertFalse(result["shared"]["switch_1"])

    def test_transport_waits_for_broker_subscription_ack(self):
        async def run():
            event_loop_thread_id = threading.get_ident()
            states = []
            messages = []
            client = push.TuyaOpenMQClient(
                _FakeAPI(),
                "uid",
                messages.append,
                lambda connected, subscribed: states.append((connected, subscribed)),
                mqtt_factory=_FakeMQTTClient,
            )
            await client.async_start()
            self.assertTrue(client.metrics.connected)
            self.assertTrue(client.metrics.subscribed)
            self.assertNotEqual(
                _FakeMQTTClient.instances[-1].tls_thread_id,
                event_loop_thread_id,
            )
            self.assertEqual(
                _FakeMQTTClient.instances[-1].subscriptions[0][0],
                "cloud/device/report",
            )
            self.assertIn((True, True), states)
            await client.async_stop()
            self.assertFalse(client.metrics.connected)

        asyncio.run(run())

    def test_transport_restart_replaces_expiring_client(self):
        async def run():
            client = push.TuyaOpenMQClient(
                _FakeAPI(),
                "uid",
                lambda payload: None,
                lambda connected, subscribed: None,
                mqtt_factory=_FakeMQTTClient,
            )
            await client.async_start()
            first = _FakeMQTTClient.instances[-1]
            await client.async_restart()
            second = _FakeMQTTClient.instances[-1]
            self.assertIsNot(first, second)
            self.assertTrue(first.stopped)
            self.assertTrue(client.metrics.subscribed)
            first.on_disconnect(first, None, None, _FakeReason(), None)
            await asyncio.sleep(0)
            self.assertTrue(client.metrics.subscribed)
            await client.async_stop()

        asyncio.run(run())

    def test_received_message_is_dispatched_on_event_loop(self):
        async def run():
            received = []
            client = push.TuyaOpenMQClient(
                _FakeAPI(),
                "uid",
                received.append,
                lambda connected, subscribed: None,
                mqtt_factory=_FakeMQTTClient,
            )
            await client.async_start()
            password = _FakeMQTTClient.instances[-1].password
            timestamp = 1234
            inner = {
                "protocol": 4,
                "data": {
                    "devId": "shared-device",
                    "status": [{"code": "doorcontact_state", "value": True}],
                },
            }
            encoded = json.dumps(inner).encode()
            padder = padding.PKCS7(128).padder()
            padded = padder.update(encoded) + padder.finalize()
            encryptor = Cipher(
                algorithms.AES(password[8:24].encode()), modes.ECB()
            ).encryptor()
            encrypted = encryptor.update(padded) + encryptor.finalize()
            envelope = json.dumps(
                {
                    "t": timestamp,
                    "data": base64.b64encode(encrypted).decode(),
                }
            ).encode()
            message = types.SimpleNamespace(payload=envelope)
            _FakeMQTTClient.instances[-1].on_message(
                _FakeMQTTClient.instances[-1], None, message
            )
            await asyncio.sleep(0)
            self.assertEqual(received[0]["data"], inner)
            self.assertEqual(client.metrics.messages_received, 1)
            self.assertIsNotNone(client.metrics.last_message_at)
            self.assertIsNotNone(client.metrics.last_message_at.tzinfo)
            await client.async_stop()

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
