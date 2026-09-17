"""Read-only live probe for Tuya shared inventory and OpenMQ subscription.

This helper never sends a device command. It prints only counts and connection
booleans; credentials, tokens, UIDs, broker URLs, topics, and device IDs are
never printed.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import hmac
import json
import ssl
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from paho.mqtt import client as mqtt

ENDPOINTS = {
    "us": "https://openapi.tuyaus.com",
    "eu": "https://openapi.tuyaeu.com",
    "cn": "https://openapi.tuyacn.com",
    "in": "https://openapi.tuyain.com",
}


def _credentials(path: Path) -> tuple[str, str, str, str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    entries = raw.get("data", {}).get("entries", [])
    matches = [entry for entry in entries if entry.get("domain") == "localtuya"]
    if not matches:
        raise RuntimeError("No LocalTuya config entry was found in the backup")
    data = matches[0].get("data", {})
    return (
        str(data["region"]),
        str(data["client_id"]),
        str(data["client_secret"]),
        str(data["user_id"]),
    )


class _Cloud:
    def __init__(self, endpoint: str, access_id: str, access_secret: str) -> None:
        self.endpoint = endpoint
        self.access_id = access_id
        self.access_secret = access_secret
        self.token = ""

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        use_token: bool = True,
    ) -> Any:
        query = urlencode(sorted((params or {}).items()))
        path_query = f"{path}?{query}" if query else path
        encoded = (
            json.dumps(body, separators=(",", ":")).encode()
            if body is not None
            else b""
        )
        timestamp = str(int(time.time() * 1000))
        canonical = f"{method}\n{hashlib.sha256(encoded).hexdigest()}\n\n{path_query}"
        signed = (
            f"{self.access_id}{self.token if use_token else ''}{timestamp}{canonical}"
        )
        signature = (
            hmac.new(self.access_secret.encode(), signed.encode(), hashlib.sha256)
            .hexdigest()
            .upper()
        )
        headers = {
            "client_id": self.access_id,
            "sign": signature,
            "sign_method": "HMAC-SHA256",
            "t": timestamp,
            "Content-Type": "application/json",
        }
        if use_token:
            headers["access_token"] = self.token
        request = Request(
            self.endpoint + path_query,
            data=encoded or None,
            headers=headers,
            method=method,
        )
        with urlopen(
            request, timeout=20, context=ssl.create_default_context()
        ) as response:
            payload = json.loads(response.read())
        if payload.get("success") is not True:
            raise RuntimeError(f"Tuya API error code {payload.get('code', 'unknown')}")
        return payload.get("result")

    def authenticate(self) -> None:
        result = self.request(
            "GET",
            "/v1.0/token",
            params={"grant_type": 1},
            use_token=False,
        )
        self.token = str(result["access_token"])


def _decode(payload: bytes, password: str) -> dict[str, Any]:
    envelope = json.loads(payload)
    buffer = base64.b64decode(envelope["data"], validate=True)
    decryptor = Cipher(algorithms.AES(password[8:24].encode()), modes.ECB()).decryptor()
    padded = decryptor.update(buffer) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    plaintext = unpadder.update(padded) + unpadder.finalize()
    envelope["data"] = json.loads(plaintext)
    return envelope


def probe(backup: Path, wait_seconds: int) -> dict[str, Any]:
    region, access_id, access_secret, uid = _credentials(backup)
    cloud = _Cloud(ENDPOINTS[region], access_id, access_secret)
    try:
        cloud.authenticate()
    except RuntimeError as err:
        raise RuntimeError(f"token stage failed: {err}") from err
    try:
        devices = cloud.request(
            "GET",
            f"/v1.0/users/{uid}/devices",
            params={"from": "sharing", "page_no": 1, "page_size": 100},
        )
    except RuntimeError as err:
        raise RuntimeError(f"shared inventory stage failed: {err}") from err
    shared_ids = {
        item["id"] for item in devices if isinstance(item, dict) and item.get("id")
    }
    try:
        config = cloud.request(
            "POST",
            "/v1.0/open-hub/access/config",
            body={
                "uid": uid,
                "link_id": f"tuya-shared-cloud.probe.{uuid.uuid4()}",
                "link_type": "mqtt",
                "topics": "device",
                "msg_encrypted_version": "1.0",
            },
        )
    except RuntimeError as err:
        raise RuntimeError(f"OpenMQ configuration stage failed: {err}") from err

    connected = threading.Event()
    subscribed = threading.Event()
    message_count = 0
    shared_report_count = 0
    foreign_report_count = 0
    password = str(config["password"])

    def on_connect(client, userdata, flags, reason_code, properties):
        if int(getattr(reason_code, "value", reason_code)) != 0:
            return
        connected.set()
        topics = config["source_topic"]
        values = topics.values() if isinstance(topics, dict) else topics
        for topic in values if not isinstance(values, str) else [values]:
            client.subscribe(topic)

    def on_subscribe(client, userdata, mid, reasons, properties):
        if not any(bool(getattr(reason, "is_failure", False)) for reason in reasons):
            subscribed.set()

    def on_message(client, userdata, message):
        nonlocal message_count, shared_report_count, foreign_report_count
        message_count += 1
        try:
            decoded = _decode(message.payload, password)
            device_id = decoded.get("data", {}).get("devId")
        except (ValueError, TypeError, KeyError, binascii.Error):
            return
        if device_id in shared_ids:
            shared_report_count += 1
        elif device_id:
            foreign_report_count += 1

    parsed = urlsplit(str(config["url"]))
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=str(config["client_id"]),
        protocol=mqtt.MQTTv311,
    )
    client.username_pw_set(str(config["username"]), password)
    client.on_connect = on_connect
    client.on_subscribe = on_subscribe
    client.on_message = on_message
    if parsed.scheme in {"ssl", "mqtts", "tls"}:
        client.tls_set()
    client.connect(parsed.hostname, parsed.port or 8883, keepalive=60)
    client.loop_start()
    try:
        subscribed.wait(timeout=20)
        if subscribed.is_set() and wait_seconds:
            time.sleep(wait_seconds)
    finally:
        client.disconnect()
        client.loop_stop()

    return {
        "shared_device_count": len(shared_ids),
        "mqtt_configuration_received": True,
        "broker_connected": connected.is_set(),
        "subscription_acknowledged": subscribed.is_set(),
        "messages_received_during_wait": message_count,
        "shared_reports_received_during_wait": shared_report_count,
        "foreign_reports_received_during_wait": foreign_report_count,
        "device_commands_sent": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("backup", type=Path)
    parser.add_argument("--wait", type=int, default=10)
    args = parser.parse_args()
    try:
        result = probe(args.backup, max(0, min(args.wait, 60)))
    except (RuntimeError, KeyError, ValueError, HTTPError, URLError) as err:
        print(json.dumps({"success": False, "error": str(err)}))
        return 1
    print(json.dumps({"success": True, **result}, indent=2))
    return 0 if result["subscription_acknowledged"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
