"""Small asynchronous client for the Tuya Cloud OpenAPI."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode

import aiohttp

from .const import SHARED_DEVICE_PAGE_SIZE
from .models import TuyaSharedDevice


class TuyaCloudError(Exception):
    """Base exception for Tuya Cloud failures."""


class TuyaCloudAuthenticationError(TuyaCloudError):
    """Raised when Tuya rejects the project credentials or token."""


class TuyaCloudConnectionError(TuyaCloudError):
    """Raised when Tuya Cloud cannot be reached."""


class TuyaMQConfigurationError(TuyaCloudError):
    """Raised when Tuya does not return usable OpenMQ credentials."""


class TuyaMQPermissionError(TuyaMQConfigurationError):
    """Raised when the cloud project lacks device-status notification access."""


AUTH_ERROR_CODES = {"1004", "1010", "1011", "1012", "1109"}
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


class TuyaCloudClient:
    """Authenticated Tuya Cloud OpenAPI client."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        endpoint: str,
        access_id: str,
        access_secret: str,
    ) -> None:
        """Initialize the API client."""
        self._session = session
        self._endpoint = endpoint.rstrip("/")
        self._access_id = access_id
        self._access_secret = access_secret
        self._access_token: str | None = None
        self._token_valid_until = 0.0
        self._token_lock = asyncio.Lock()

    @staticmethod
    def build_string_to_sign(
        method: str, path_with_query: str, body: bytes = b""
    ) -> str:
        """Build Tuya's canonical request string."""
        content_hash = hashlib.sha256(body).hexdigest() if body else EMPTY_SHA256
        return f"{method.upper()}\n{content_hash}\n\n{path_with_query}"

    def build_signature(
        self,
        method: str,
        path_with_query: str,
        timestamp: str,
        body: bytes = b"",
        access_token: str | None = None,
    ) -> str:
        """Build an uppercase HMAC-SHA256 Tuya signature."""
        canonical = self.build_string_to_sign(method, path_with_query, body)
        payload = f"{self._access_id}{access_token or ''}{timestamp}{canonical}"
        return (
            hmac.new(self._access_secret.encode(), payload.encode(), hashlib.sha256)
            .hexdigest()
            .upper()
        )

    async def async_get_shared_devices(self, uid: str) -> list[TuyaSharedDevice]:
        """Return only devices received through Tuya individual sharing."""
        devices: list[TuyaSharedDevice] = []
        seen_device_ids: set[str] = set()
        page = 1
        while True:
            result = await self._async_request(
                "GET",
                f"/v1.0/users/{uid}/devices",
                params={
                    "from": "sharing",
                    "page_no": page,
                    "page_size": SHARED_DEVICE_PAGE_SIZE,
                },
            )
            if isinstance(result, list):
                raw_devices = result
            elif isinstance(result, dict):
                raw_devices = result.get("list") or result.get("devices") or []
            else:
                raise TuyaCloudError("Tuya returned an invalid shared-device list")

            page_devices = [
                TuyaSharedDevice.from_api(item)
                for item in raw_devices
                if isinstance(item, dict) and item.get("id")
            ]
            new_devices = [
                device
                for device in page_devices
                if device.device_id not in seen_device_ids
            ]
            devices.extend(new_devices)
            seen_device_ids.update(device.device_id for device in new_devices)
            if len(raw_devices) < SHARED_DEVICE_PAGE_SIZE or not new_devices:
                break
            page += 1
        return devices

    async def async_get_functions(self, device_id: str) -> dict[str, Any]:
        """Return the device category and writable function definitions."""
        result = await self._async_request(
            "GET", f"/v1.0/iot-03/devices/{device_id}/functions"
        )
        if not isinstance(result, dict):
            raise TuyaCloudError("Tuya returned an invalid function definition")
        return result

    async def async_get_status(self, device_id: str) -> dict[str, Any]:
        """Return the latest datapoint values indexed by code."""
        result = await self._async_request(
            "GET", f"/v1.0/iot-03/devices/{device_id}/status"
        )
        if not isinstance(result, list):
            raise TuyaCloudError("Tuya returned an invalid status payload")
        return {
            item["code"]: item.get("value")
            for item in result
            if isinstance(item, dict) and isinstance(item.get("code"), str)
        }

    async def async_get_mq_config(self, uid: str, link_id: str) -> dict[str, Any]:
        """Return short-lived MQTT credentials for device push reports.

        This is the Smart Home Open Hub endpoint used by Tuya's official IoT
        Python SDK. The credentials are kept only in memory.
        """
        try:
            result = await self._async_request(
                "POST",
                "/v1.0/open-hub/access/config",
                json_body={
                    "uid": uid,
                    "link_id": link_id,
                    "link_type": "mqtt",
                    "topics": "device",
                    "msg_encrypted_version": "1.0",
                },
            )
        except TuyaCloudError as err:
            if str(err).split(":", 1)[0] in {
                "1106",
                "28841101",
                "28841102",
                "28841105",
                "28841106",
            }:
                raise TuyaMQPermissionError(
                    "Tuya Smart Home OpenMQ is not authorized for this "
                    "project and UID; verify the linked app account, project "
                    "region, and Device Status Notification authorization"
                ) from err
            raise
        required = {"url", "client_id", "username", "password", "source_topic"}
        if not isinstance(result, dict) or not required.issubset(result):
            raise TuyaMQConfigurationError(
                "Tuya returned an invalid OpenMQ configuration"
            )
        config = dict(result)
        config["_msg_encrypted_version"] = "1.0"
        return config

    async def async_send_command(self, device_id: str, code: str, value: Any) -> None:
        """Send one standard instruction to a shared device."""
        await self._async_request(
            "POST",
            f"/v1.0/iot-03/devices/{device_id}/commands",
            json_body={"commands": [{"code": code, "value": value}]},
        )

    async def _async_ensure_token(self) -> str:
        """Obtain a token when none exists or the current token is expiring."""
        if self._access_token and time.monotonic() < self._token_valid_until:
            return self._access_token

        async with self._token_lock:
            if self._access_token and time.monotonic() < self._token_valid_until:
                return self._access_token

            result = await self._async_signed_request(
                "GET", "/v1.0/token", params={"grant_type": 1}, use_token=False
            )
            if not isinstance(result, dict) or not result.get("access_token"):
                raise TuyaCloudAuthenticationError(
                    "Tuya did not return an access token"
                )
            self._access_token = str(result["access_token"])
            expires = int(result.get("expire_time", 7200))
            self._token_valid_until = time.monotonic() + max(60, expires - 120)
            return self._access_token

    async def _async_request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any | None = None,
    ) -> Any:
        """Execute a business request and retry once with a new token."""
        await self._async_ensure_token()
        try:
            return await self._async_signed_request(
                method, path, params=params, json_body=json_body, use_token=True
            )
        except TuyaCloudAuthenticationError:
            self._access_token = None
            self._token_valid_until = 0
            await self._async_ensure_token()
            return await self._async_signed_request(
                method, path, params=params, json_body=json_body, use_token=True
            )

    async def _async_signed_request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any | None = None,
        use_token: bool,
    ) -> Any:
        """Sign, send, and decode one Tuya request."""
        query = urlencode(sorted((params or {}).items()), doseq=True)
        path_with_query = f"{path}?{query}" if query else path
        body = (
            json.dumps(json_body, separators=(",", ":"), ensure_ascii=False).encode()
            if json_body is not None
            else b""
        )
        timestamp = str(int(time.time() * 1000))
        token = self._access_token if use_token else None
        headers = {
            "client_id": self._access_id,
            "sign": self.build_signature(
                method, path_with_query, timestamp, body, token
            ),
            "sign_method": "HMAC-SHA256",
            "t": timestamp,
            "Content-Type": "application/json",
        }
        if token:
            headers["access_token"] = token

        try:
            async with self._session.request(
                method,
                f"{self._endpoint}{path_with_query}",
                data=body or None,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as response:
                response.raise_for_status()
                payload = await response.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            raise TuyaCloudConnectionError(str(err)) from err

        if not isinstance(payload, dict):
            raise TuyaCloudError("Tuya returned a malformed response")
        if payload.get("success") is not True:
            code = str(payload.get("code", "unknown"))
            message = str(payload.get("msg", "Tuya request failed"))
            if code in AUTH_ERROR_CODES:
                raise TuyaCloudAuthenticationError(f"{code}: {message}")
            raise TuyaCloudError(f"{code}: {message}")
        return payload.get("result")
