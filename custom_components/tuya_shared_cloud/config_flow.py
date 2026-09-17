"""Config flow for Tuya Shared Cloud."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    TuyaCloudAuthenticationError,
    TuyaCloudClient,
    TuyaCloudConnectionError,
    TuyaCloudError,
    TuyaMQPermissionError,
)
from .const import (
    CONF_ACCESS_ID,
    CONF_ACCESS_SECRET,
    CONF_REGION,
    CONF_SCAN_INTERVAL,
    CONF_UID,
    DEFAULT_REGION,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    REGION_ENDPOINTS,
)


def _account_unique_id(uid: str) -> str:
    """Return a stable, non-secret identifier for one linked app account."""
    return hashlib.sha256(uid.encode()).hexdigest()[:24]


def _credentials_schema(defaults: Mapping[str, Any] | None = None) -> vol.Schema:
    """Return the account credentials form schema."""
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_REGION, default=defaults.get(CONF_REGION, DEFAULT_REGION)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value="us", label="United States"),
                        selector.SelectOptionDict(value="eu", label="Europe"),
                        selector.SelectOptionDict(value="cn", label="China"),
                        selector.SelectOptionDict(value="in", label="India"),
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(CONF_ACCESS_ID, default=defaults.get(CONF_ACCESS_ID, "")): str,
            vol.Required(
                CONF_ACCESS_SECRET, default=defaults.get(CONF_ACCESS_SECRET, "")
            ): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
            vol.Required(CONF_UID, default=defaults.get(CONF_UID, "")): str,
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): vol.All(
                vol.Coerce(int),
                vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
            ),
        }
    )


def _reauth_schema(entry_data: Mapping[str, Any]) -> vol.Schema:
    """Ask only for credentials during automatic reauthentication."""
    return vol.Schema(
        {
            vol.Required(
                CONF_ACCESS_ID, default=entry_data.get(CONF_ACCESS_ID, "")
            ): str,
            vol.Required(CONF_ACCESS_SECRET): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
        }
    )


class TuyaSharedCloudConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure one Tuya account's individually shared devices."""

    VERSION = 1

    async def _validate(self, data: Mapping[str, Any]) -> int:
        client = TuyaCloudClient(
            async_get_clientsession(self.hass),
            REGION_ENDPOINTS[data[CONF_REGION]],
            data[CONF_ACCESS_ID],
            data[CONF_ACCESS_SECRET],
        )
        devices = await client.async_get_shared_devices(data[CONF_UID])
        await client.async_get_mq_config(data[CONF_UID], f"tsc-check.{uuid.uuid4()}")
        return len(devices)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle initial UI setup."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                device_count = await self._validate(user_input)
            except TuyaCloudAuthenticationError:
                errors["base"] = "invalid_auth"
            except TuyaMQPermissionError:
                errors["base"] = "push_not_authorized"
            except TuyaCloudConnectionError:
                errors["base"] = "cannot_connect"
            except TuyaCloudError:
                errors["base"] = "api_error"
            else:
                if device_count == 0:
                    errors["base"] = "no_shared_devices"
                else:
                    await self.async_set_unique_id(
                        _account_unique_id(user_input[CONF_UID])
                    )
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title="Tuya Shared Cloud", data=user_input
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=_credentials_schema(user_input),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication after Tuya rejects credentials."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate and save replacement project credentials."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            updated = {**entry.data, **user_input}
            try:
                await self._validate(updated)
            except TuyaCloudAuthenticationError:
                errors["base"] = "invalid_auth"
            except TuyaMQPermissionError:
                errors["base"] = "push_not_authorized"
            except TuyaCloudConnectionError:
                errors["base"] = "cannot_connect"
            except TuyaCloudError:
                errors["base"] = "api_error"
            else:
                await self.async_set_unique_id(_account_unique_id(updated[CONF_UID]))
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_ACCESS_ID: updated[CONF_ACCESS_ID],
                        CONF_ACCESS_SECRET: updated[CONF_ACCESS_SECRET],
                    },
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_reauth_schema(entry.data),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow deliberate changes to account and polling settings."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                device_count = await self._validate(user_input)
            except TuyaCloudAuthenticationError:
                errors["base"] = "invalid_auth"
            except TuyaMQPermissionError:
                errors["base"] = "push_not_authorized"
            except TuyaCloudConnectionError:
                errors["base"] = "cannot_connect"
            except TuyaCloudError:
                errors["base"] = "api_error"
            else:
                if device_count == 0:
                    errors["base"] = "no_shared_devices"
                else:
                    await self.async_set_unique_id(
                        _account_unique_id(user_input[CONF_UID])
                    )
                    self._abort_if_unique_id_mismatch()
                    return self.async_update_reload_and_abort(
                        entry, data_updates=user_input
                    )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_credentials_schema(user_input or entry.data),
            errors=errors,
        )
