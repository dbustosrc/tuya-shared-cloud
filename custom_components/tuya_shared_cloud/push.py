"""Tuya OpenMQ cloud-push transport.

The transport is deliberately isolated from Home Assistant and from Tuya's
legacy Python SDK. It implements the documented OpenMQ flow without patching
the official Tuya integration or importing its runtime internals.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import time
import uuid
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from paho.mqtt import client as mqtt

from .api import TuyaCloudClient
from .const import (
    PUSH_BIZCODE_OFFLINE,
    PUSH_BIZCODE_ONLINE,
    PUSH_CONFIG_RENEW_MARGIN,
    PUSH_CONNECT_TIMEOUT,
    PUSH_PROTOCOL_DEVICE_REPORT,
    PUSH_PROTOCOL_OTHER,
    PUSH_RETRY_MAX,
    PUSH_RETRY_MIN,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TuyaPushUpdate:
    """One device update decoded from Tuya OpenMQ."""

    device_id: str
    status: dict[str, Any]
    online: bool | None = None


@dataclass(slots=True)
class TuyaPushMetrics:
    """Runtime evidence that push, rather than reconciliation, is updating state."""

    connected: bool = False
    subscribed: bool = False
    messages_received: int = 0
    reports_applied: int = 0
    datapoints_applied: int = 0
    ignored_messages: int = 0
    reconciliation_runs: int = 0
    reconciliation_corrections: int = 0
    reconciliation_failures: int = 0
    last_message_monotonic: float | None = None
    last_message_at: datetime | None = None
    last_reconciliation_attempt_at: datetime | None = None
    last_reconciliation_success_at: datetime | None = None
    last_reconciliation_failure_at: datetime | None = None
    last_reconciliation_duration_seconds: float | None = None

    @property
    def push_delivery_ratio(self) -> float | None:
        """Return the share of observed changes delivered through push."""
        total = self.datapoints_applied + self.reconciliation_corrections
        return None if total == 0 else self.datapoints_applied / total


def parse_push_update(
    payload: dict[str, Any], allowed_device_ids: Collection[str]
) -> TuyaPushUpdate | None:
    """Extract a device report and reject every device outside sharing scope."""
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    device_id = data.get("devId")
    if not isinstance(device_id, str) or device_id not in allowed_device_ids:
        return None

    protocol = payload.get("protocol")
    if protocol == PUSH_PROTOCOL_DEVICE_REPORT:
        raw_status = data.get("status")
        if not isinstance(raw_status, list):
            return None
        status = {
            item["code"]: item.get("value")
            for item in raw_status
            if isinstance(item, dict) and isinstance(item.get("code"), str)
        }
        return TuyaPushUpdate(device_id=device_id, status=status) if status else None

    if protocol == PUSH_PROTOCOL_OTHER:
        biz_code = data.get("bizCode")
        if biz_code == PUSH_BIZCODE_ONLINE:
            return TuyaPushUpdate(device_id=device_id, status={}, online=True)
        if biz_code == PUSH_BIZCODE_OFFLINE:
            return TuyaPushUpdate(device_id=device_id, status={}, online=False)
    return None


def preserve_newer_push_values(
    polled: dict[str, dict[str, Any]],
    current: Mapping[str, Mapping[str, Any]],
    last_push_by_datapoint: Mapping[tuple[str, str], float],
    poll_started: float,
) -> dict[str, dict[str, Any]]:
    """Prevent an in-flight REST response from replacing a newer push value."""
    for device_id, status in polled.items():
        for code in tuple(status):
            if last_push_by_datapoint.get(
                (device_id, code), 0
            ) > poll_started and code in current.get(device_id, {}):
                status[code] = current[device_id][code]
    return polled


def decode_openmq_message(
    payload: bytes, password: str, encrypted_version: str = "1.0"
) -> dict[str, Any]:
    """Decode Tuya Smart Home OpenMQ encrypted-message formats."""
    envelope = json.loads(payload.decode("utf-8"))
    if not isinstance(envelope, dict):
        raise TypeError("OpenMQ envelope is not an object")
    encrypted = envelope.get("data")
    timestamp = envelope.get("t")
    if isinstance(encrypted, dict):
        return envelope
    if not isinstance(encrypted, str) or timestamp is None:
        raise ValueError("OpenMQ envelope is missing encrypted data")

    key = password[8:24].encode("utf-8")
    if len(key) != 16:
        raise ValueError("OpenMQ password cannot produce a 128-bit key")

    buffer = base64.b64decode(encrypted, validate=True)
    if encrypted_version == "1.0":
        if not buffer or len(buffer) % 16:
            raise ValueError("OpenMQ AES-ECB payload has an invalid length")
        decryptor = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
        padded = decryptor.update(buffer) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        plaintext = unpadder.update(padded) + unpadder.finalize()
    elif encrypted_version == "2.0":
        if len(buffer) < 4 + 1 + 16:
            raise ValueError("OpenMQ encrypted payload is too short")
        iv_length = int.from_bytes(buffer[:4], byteorder="big")
        if iv_length < 1 or len(buffer) <= 4 + iv_length + 16:
            raise ValueError("OpenMQ payload has an invalid IV length")
        iv = buffer[4 : 4 + iv_length]
        plaintext = AESGCM(key).decrypt(
            iv,
            buffer[4 + iv_length :],
            str(timestamp).encode("utf-8"),
        )
    else:
        raise ValueError(f"Unsupported OpenMQ encryption version: {encrypted_version}")
    decoded = json.loads(plaintext.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise TypeError("OpenMQ decrypted payload is not an object")
    envelope["data"] = decoded
    return envelope


class TuyaOpenMQClient:
    """Maintain Tuya's short-lived MQTT subscription and renew it safely."""

    def __init__(
        self,
        api: TuyaCloudClient,
        uid: str,
        on_message: Callable[[dict[str, Any]], None],
        on_state: Callable[[bool, bool], None],
        *,
        mqtt_factory: Callable[..., Any] | None = None,
        metrics: TuyaPushMetrics | None = None,
    ) -> None:
        """Initialize the OpenMQ transport."""
        self._api = api
        self._uid = uid
        self._on_message_callback = on_message
        self._on_state_callback = on_state
        self._mqtt_factory = mqtt_factory or mqtt.Client
        self._loop: asyncio.AbstractEventLoop | None = None
        self._mqtt_client: Any | None = None
        self._password = ""
        self._encrypted_version = "1.0"
        self._topics: tuple[str, ...] = ()
        self._pending_subscriptions: set[int] = set()
        self._ready_event = asyncio.Event()
        self._running = False
        self._renew_task: asyncio.Task | None = None
        self._retry_task: asyncio.Task | None = None
        self._restart_lock = asyncio.Lock()
        self.metrics = metrics or TuyaPushMetrics()
        self.link_id = f"tuya-shared-cloud.{uuid.uuid4()}"

    async def async_start(self) -> None:
        """Start OpenMQ and wait until the broker confirms subscriptions."""
        self._loop = asyncio.get_running_loop()
        self._running = True
        try:
            await self._async_connect_new()
        except Exception:
            self._schedule_retry()
            raise

    async def async_stop(self) -> None:
        """Stop MQTT and all renewal/retry work."""
        self._running = False
        tasks = [
            task
            for task in (self._renew_task, self._retry_task)
            if task is not None and task is not asyncio.current_task()
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._renew_task = None
        self._retry_task = None
        client, self._mqtt_client = self._mqtt_client, None
        if client is not None:
            await asyncio.to_thread(self._stop_client, client)
        self._set_state(False, False)

    async def async_restart(self) -> None:
        """Replace expiring OpenMQ credentials and connection."""
        async with self._restart_lock:
            if not self._running:
                return
            await self._async_connect_new()

    async def _async_connect_new(self) -> None:
        config = await self._api.async_get_mq_config(self._uid, self.link_id)
        topics = self._extract_topics(config["source_topic"])
        if not topics:
            raise ValueError("Tuya OpenMQ returned no source topics")
        parsed = urlsplit(str(config["url"]))
        if not parsed.hostname:
            raise ValueError("Tuya OpenMQ returned an invalid broker URL")

        old_client, self._mqtt_client = self._mqtt_client, None
        if old_client is not None:
            await asyncio.to_thread(self._stop_client, old_client)

        self._password = str(config["password"])
        self._encrypted_version = str(config.get("_msg_encrypted_version", "1.0"))
        self._topics = topics
        self._pending_subscriptions.clear()
        self._ready_event.clear()
        self._set_state(False, False)

        client = self._mqtt_factory(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=str(config["client_id"]),
            protocol=mqtt.MQTTv311,
        )
        client.username_pw_set(str(config["username"]), self._password)
        client.reconnect_delay_set(min_delay=1, max_delay=60)
        client.on_connect = self._mqtt_on_connect
        client.on_disconnect = self._mqtt_on_disconnect
        client.on_message = self._mqtt_on_message
        client.on_subscribe = self._mqtt_on_subscribe
        if parsed.scheme in {"ssl", "mqtts", "tls"}:
            # paho loads the operating system certificate store here. Keep that
            # blocking filesystem work off Home Assistant's event loop.
            await asyncio.to_thread(client.tls_set)
        self._mqtt_client = client
        port = parsed.port or (
            8883 if parsed.scheme in {"ssl", "mqtts", "tls"} else 1883
        )
        try:
            client.connect_async(parsed.hostname, port, keepalive=60)
            client.loop_start()
            await asyncio.wait_for(
                self._ready_event.wait(), timeout=PUSH_CONNECT_TIMEOUT
            )
        except BaseException:
            if self._mqtt_client is client:
                self._mqtt_client = None
            await asyncio.to_thread(self._stop_client, client)
            raise

        expire_seconds = max(300, int(config.get("expire_time", 7200)))
        delay = max(60, expire_seconds - PUSH_CONFIG_RENEW_MARGIN)
        current_task = asyncio.current_task()
        if self._renew_task is not None and self._renew_task is not current_task:
            self._renew_task.cancel()
        self._renew_task = asyncio.create_task(
            self._async_renew_after(delay), name="Renew Tuya Shared Cloud OpenMQ"
        )

    async def _async_renew_after(self, delay: int) -> None:
        try:
            await asyncio.sleep(delay)
            await self.async_restart()
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("Unable to renew Tuya OpenMQ credentials")
            self._schedule_retry()

    def _schedule_retry(self) -> None:
        if not self._running or (self._retry_task and not self._retry_task.done()):
            return
        self._retry_task = asyncio.create_task(
            self._async_retry_loop(), name="Retry Tuya Shared Cloud OpenMQ"
        )

    async def _async_retry_loop(self) -> None:
        delay = PUSH_RETRY_MIN
        while self._running and not self.metrics.subscribed:
            await asyncio.sleep(delay)
            try:
                await self.async_restart()
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.exception("Unable to connect Tuya OpenMQ; retrying")
                delay = min(delay * 2, PUSH_RETRY_MAX)
            else:
                return

    def _mqtt_on_connect(
        self, client, userdata, flags, reason_code, properties
    ) -> None:
        if client is not self._mqtt_client:
            return
        if self._reason_code_value(reason_code) != 0:
            self._call_soon(self._set_state, False, False)
            return
        self._call_soon(self._set_state, True, False)
        self._pending_subscriptions.clear()
        for topic in self._topics:
            result, mid = client.subscribe(topic)
            if result == mqtt.MQTT_ERR_SUCCESS:
                self._pending_subscriptions.add(mid)

    def _mqtt_on_subscribe(
        self, client, userdata, mid, reason_code_list, properties
    ) -> None:
        if client is not self._mqtt_client:
            return
        failed = any(
            bool(getattr(reason, "is_failure", False)) for reason in reason_code_list
        )
        if failed:
            self._call_soon(self._set_state, True, False)
            return
        self._pending_subscriptions.discard(mid)
        if not self._pending_subscriptions:
            self._call_soon(self._mark_ready)

    def _mqtt_on_disconnect(
        self, client, userdata, disconnect_flags, reason_code, properties
    ) -> None:
        if client is not self._mqtt_client:
            return
        self._call_soon(self._set_state, False, False)

    def _mqtt_on_message(self, client, userdata, message) -> None:
        if client is not self._mqtt_client:
            return
        try:
            payload = decode_openmq_message(
                message.payload, self._password, self._encrypted_version
            )
        except (
            ValueError,
            TypeError,
            json.JSONDecodeError,
            binascii.Error,
            InvalidTag,
        ):
            _LOGGER.exception("Unable to decode a Tuya OpenMQ message")
            return
        self._call_soon(self._dispatch_message, payload)

    def _dispatch_message(self, payload: dict[str, Any]) -> None:
        self.metrics.messages_received += 1
        self.metrics.last_message_monotonic = time.monotonic()
        self.metrics.last_message_at = datetime.now(UTC)
        self._on_message_callback(payload)

    def _mark_ready(self) -> None:
        self._set_state(True, True)
        self._ready_event.set()

    def _set_state(self, connected: bool, subscribed: bool) -> None:
        changed = (
            connected != self.metrics.connected or subscribed != self.metrics.subscribed
        )
        self.metrics.connected = connected
        self.metrics.subscribed = subscribed
        if changed:
            self._on_state_callback(connected, subscribed)

    def _call_soon(self, callback: Callable, *args: Any) -> None:
        if self._loop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(callback, *args)

    @staticmethod
    def _extract_topics(value: Any) -> tuple[str, ...]:
        if isinstance(value, str):
            return (value,)
        if isinstance(value, dict):
            return tuple(topic for topic in value.values() if isinstance(topic, str))
        if isinstance(value, list):
            return tuple(topic for topic in value if isinstance(topic, str))
        return ()

    @staticmethod
    def _reason_code_value(reason_code: Any) -> int:
        return int(getattr(reason_code, "value", reason_code))

    @staticmethod
    def _stop_client(client: Any) -> None:
        try:
            client.disconnect()
        finally:
            client.loop_stop()
