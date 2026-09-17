"""Tuya Shared Cloud integration."""

from __future__ import annotations

import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    TuyaCloudAuthenticationError,
    TuyaCloudClient,
    TuyaCloudConnectionError,
    TuyaCloudError,
)
from .const import (
    CONF_ACCESS_ID,
    CONF_ACCESS_SECRET,
    CONF_REGION,
    CONF_SCAN_INTERVAL,
    CONF_UID,
    DEFAULT_SCAN_INTERVAL,
    REGION_ENDPOINTS,
)
from .coordinator import TuyaSharedCoordinator
from .garage import build_garage_profiles
from .models import TuyaFunction, TuyaSharedRuntimeData
from .push import TuyaOpenMQClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.COVER,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

type TuyaSharedConfigEntry = ConfigEntry[TuyaSharedRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: TuyaSharedConfigEntry) -> bool:
    """Set up an account containing only individually shared devices."""
    client = TuyaCloudClient(
        async_get_clientsession(hass),
        REGION_ENDPOINTS[entry.data[CONF_REGION]],
        entry.data[CONF_ACCESS_ID],
        entry.data[CONF_ACCESS_SECRET],
    )
    try:
        devices = await client.async_get_shared_devices(entry.data[CONF_UID])
        definitions = await asyncio.gather(
            *(client.async_get_functions(device.device_id) for device in devices)
        )
    except TuyaCloudAuthenticationError as err:
        raise ConfigEntryAuthFailed from err
    except (TuyaCloudConnectionError, TuyaCloudError) as err:
        raise ConfigEntryNotReady(str(err)) from err

    functions: dict[str, dict[str, TuyaFunction]] = {}
    for device, definition in zip(devices, definitions, strict=True):
        if not device.category:
            device.category = str(definition.get("category", ""))
        functions[device.device_id] = {
            function.code: function
            for raw in definition.get("functions", [])
            if isinstance(raw, dict) and raw.get("code")
            for function in [TuyaFunction.from_api(raw)]
        }

    garage_profiles = build_garage_profiles(devices, functions, entry.options)

    coordinator = TuyaSharedCoordinator(
        hass,
        entry,
        client,
        entry.data[CONF_UID],
        int(entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
        devices,
        garage_profiles,
    )
    await coordinator.async_config_entry_first_refresh()
    push_client = TuyaOpenMQClient(
        client,
        entry.data[CONF_UID],
        coordinator.async_handle_push_payload,
        coordinator.async_handle_push_state,
        metrics=coordinator.push_metrics,
    )
    coordinator.attach_push_client(push_client)
    entry.runtime_data = TuyaSharedRuntimeData(
        coordinator=coordinator,
        functions=functions,
        garage_profiles=garage_profiles,
        push_client=push_client,
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    try:
        await push_client.async_start()
    except Exception:
        # Keep the integration usable while the self-healing retry task restores
        # push. The slow coordinator remains a correctness backstop.
        _LOGGER.exception(
            "Tuya OpenMQ could not start; REST reconciliation is active while retrying"
        )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TuyaSharedConfigEntry) -> bool:
    """Unload a Tuya Shared Cloud config entry."""
    await entry.runtime_data.push_client.async_stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
