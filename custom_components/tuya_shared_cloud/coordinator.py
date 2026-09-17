"""Centralized discovery, polling, and command handling."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    TuyaCloudAuthenticationError,
    TuyaCloudClient,
    TuyaCloudConnectionError,
    TuyaCloudError,
)
from .const import DOOR_CLOSE, DOOR_OPEN, DP_DOOR_CONTACT, PENDING_COMMAND_TIMEOUT
from .garage import GarageDoorProfile
from .models import TuyaSharedDevice
from .push import (
    TuyaOpenMQClient,
    TuyaPushMetrics,
    parse_push_update,
    preserve_newer_push_values,
)

_LOGGER = logging.getLogger(__name__)


class TuyaSharedCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Apply push reports and periodically reconcile the shared inventory."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        client: TuyaCloudClient,
        uid: str,
        scan_interval: int,
        devices: list[TuyaSharedDevice],
        garage_profiles: dict[str, GarageDoorProfile],
    ) -> None:
        """Initialize the account coordinator."""
        super().__init__(
            hass,
            logger=_LOGGER,
            name="Tuya Shared Cloud",
            update_interval=timedelta(seconds=scan_interval),
            config_entry=config_entry,
        )
        self.client = client
        self.uid = uid
        self.devices = {device.device_id: device for device in devices}
        self.garage_profiles = garage_profiles
        self.pending_door_commands: dict[str, tuple[str, float]] = {}
        self._reload_requested = False
        self._baseline_loaded = False
        self._suppress_reconciliation_metric_once = False
        self._last_push_by_datapoint: dict[tuple[str, str], float] = {}
        self.push_client: TuyaOpenMQClient | None = None
        self.push_metrics: TuyaPushMetrics | None = None

    def attach_push_client(self, push_client: TuyaOpenMQClient) -> None:
        """Attach the primary cloud-push transport."""
        self.push_client = push_client
        self.push_metrics = push_client.metrics

    def async_handle_push_payload(self, payload: dict[str, Any]) -> None:
        """Apply one OpenMQ report immediately on Home Assistant's event loop."""
        metrics = self.push_metrics
        update = parse_push_update(payload, self.devices.keys())
        if update is None:
            if metrics is not None:
                metrics.ignored_messages += 1
            return

        device = self.devices.get(update.device_id)
        if device is None:
            if metrics is not None:
                metrics.ignored_messages += 1
            return
        if update.online is not None:
            device.online = update.online

        current = {key: dict(status) for key, status in (self.data or {}).items()}
        device_status = current.setdefault(update.device_id, {})
        changed = sum(
            device_status.get(code) != value for code, value in update.status.items()
        )
        device_status.update(update.status)
        device.status.update(update.status)
        received_at = time.monotonic()
        for code in update.status:
            self._last_push_by_datapoint[(update.device_id, code)] = received_at
        if metrics is not None:
            metrics.reports_applied += 1
            metrics.datapoints_applied += changed
        self._resolve_pending_door_commands(current)
        self.async_set_updated_data(current)

    def async_handle_push_state(self, connected: bool, subscribed: bool) -> None:
        """Log push health transitions without making device entities unavailable."""
        if subscribed:
            _LOGGER.info("Tuya OpenMQ subscribed; cloud push is active")
        elif connected:
            # This is the normal interval between CONNACK and SUBACK.
            _LOGGER.debug("Tuya OpenMQ connected; waiting for subscription ack")
        else:
            _LOGGER.warning(
                "Tuya OpenMQ is disconnected; slow REST reconciliation remains active"
            )
        self.async_update_listeners()

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        """Reconcile shared inventory and authoritative per-device statuses."""
        poll_started = time.monotonic()
        try:
            devices = await self.client.async_get_shared_devices(self.uid)
            statuses = await asyncio.gather(
                *(self.client.async_get_status(device.device_id) for device in devices)
            )
            for device, status in zip(devices, statuses, strict=True):
                device.status = status
        except TuyaCloudAuthenticationError as err:
            raise ConfigEntryAuthFailed from err
        except (TuyaCloudConnectionError, TuyaCloudError) as err:
            raise UpdateFailed(str(err)) from err

        updated = {device.device_id: device for device in devices}
        if set(updated) != set(self.devices) and not self._reload_requested:
            self._reload_requested = True
            self.hass.async_create_task(
                self.hass.config_entries.async_reload(self.config_entry.entry_id),
                "Reload Tuya Shared Cloud after sharing inventory changed",
            )
        self.devices = updated
        data = {device.device_id: device.status for device in devices}
        # A push report can arrive while REST requests are in flight. Keep the
        # newer push value instead of overwriting it with an older response.
        preserve_newer_push_values(
            data,
            self.data or {},
            self._last_push_by_datapoint,
            poll_started,
        )
        metrics = self.push_metrics
        if metrics is not None:
            metrics.reconciliation_runs += 1
            if self._baseline_loaded and not self._suppress_reconciliation_metric_once:
                previous = self.data or {}
                corrections = sum(
                    previous.get(device_id, {}).get(code) != value
                    for device_id, status in data.items()
                    for code, value in status.items()
                )
                metrics.reconciliation_corrections += corrections
                if corrections:
                    _LOGGER.warning(
                        "REST reconciliation corrected %s Tuya datapoint(s); "
                        "OpenMQ connected=%s subscribed=%s push_ratio=%s",
                        corrections,
                        metrics.connected,
                        metrics.subscribed,
                        metrics.push_delivery_ratio,
                    )
        self._suppress_reconciliation_metric_once = False
        self._baseline_loaded = True
        self._resolve_pending_door_commands(data)
        return data

    async def async_send_command(
        self,
        device_id: str,
        code: str,
        value: Any,
        *,
        door_command: str | None = None,
    ) -> None:
        """Send a command, surface errors, and refresh from Cloud."""
        try:
            await self.client.async_send_command(device_id, code, value)
        except TuyaCloudAuthenticationError as err:
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                "Tuya Cloud authentication failed; reauthentication is required"
            ) from err
        except (TuyaCloudConnectionError, TuyaCloudError) as err:
            raise HomeAssistantError(f"Tuya Cloud command failed: {err}") from err

        profile = self.garage_profiles.get(device_id)
        if door_command and (profile is None or profile.trust_status):
            self.pending_door_commands[device_id] = (
                door_command,
                time.monotonic(),
            )
        # Never claim success from the command acknowledgement alone. Tuya can
        # accept a command that the actuator ignores; push or REST must confirm
        # every resulting state change.
        self._suppress_reconciliation_metric_once = True
        await self.async_request_refresh()

    def pending_door_command(self, device_id: str) -> str | None:
        """Return the pending door command for a device."""
        pending = self.pending_door_commands.get(device_id)
        return pending[0] if pending else None

    def _resolve_pending_door_commands(self, data: dict[str, dict[str, Any]]) -> None:
        """Clear motion when the contact reaches target or times out."""
        now = time.monotonic()
        for device_id, (command, started) in list(self.pending_door_commands.items()):
            contact = data.get(device_id, {}).get(DP_DOOR_CONTACT)
            profile = self.garage_profiles.get(device_id)
            closed = (
                profile.contact_is_closed(contact)
                if profile is not None
                else (not contact if isinstance(contact, bool) else None)
            )
            reached_target = (command == DOOR_OPEN and closed is False) or (
                command == DOOR_CLOSE and closed is True
            )
            if reached_target or now - started > PENDING_COMMAND_TIMEOUT:
                self.pending_door_commands.pop(device_id, None)
