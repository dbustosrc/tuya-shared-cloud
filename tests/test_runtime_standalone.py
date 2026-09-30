"""Exercise runtime behavior with the existing transport fixtures and HA doubles."""

from __future__ import annotations

import asyncio
import time
import types
import unittest
from dataclasses import dataclass
from enum import IntFlag
from unittest.mock import patch

import test_push_standalone as transport


class _HAError(Exception):
    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self.translation_key = kwargs.get("translation_key")


class _Coordinator:
    def __class_getitem__(cls, item):
        return cls

    def __init__(self, hass, **kwargs):
        self.hass = hass
        self.config_entry = kwargs["config_entry"]
        self.update_interval = kwargs["update_interval"]
        self.data = None
        self.last_update_success = True
        self.notifications = 0
        self.scheduled_at = time.monotonic() + self.update_interval.total_seconds()

    def async_update_listeners(self):
        self.notifications += 1

    def async_set_updated_data(self, data):
        self.data = data
        self.last_update_success = True
        self.scheduled_at = time.monotonic() + self.update_interval.total_seconds()
        self.async_update_listeners()

    async def async_request_refresh(self):
        try:
            self.data = await self._async_update_data()
        except _HAError:
            self.last_update_success = False
        else:
            self.last_update_success = True
        self.async_update_listeners()


class _CoordinatorEntity:
    def __class_getitem__(cls, item):
        return cls

    def __init__(self, coordinator):
        self.coordinator = coordinator

    @property
    def available(self):
        return self.coordinator.last_update_success


class _Features(IntFlag):
    OPEN = 1
    CLOSE = 2


@dataclass(frozen=True, kw_only=True)
class _SensorDescription:
    key: str
    translation_key: str
    icon: str
    device_class: str | None = None
    native_unit_of_measurement: str | None = None
    suggested_display_precision: int | None = None
    entity_registry_enabled_default: bool = True


def _module(name, **attributes):
    module = types.ModuleType(name)
    module.__dict__.update(attributes)
    return module


_modules = {
    "homeassistant": _module("homeassistant"),
    "homeassistant.config_entries": _module("config_entries", ConfigEntry=_Coordinator),
    "homeassistant.core": _module("core", HomeAssistant=object),
    "homeassistant.exceptions": _module(
        "exceptions", ConfigEntryAuthFailed=_HAError, HomeAssistantError=_HAError
    ),
    "homeassistant.helpers": _module("helpers"),
    "homeassistant.helpers.update_coordinator": _module(
        "update_coordinator",
        DataUpdateCoordinator=_Coordinator,
        CoordinatorEntity=_CoordinatorEntity,
        UpdateFailed=_HAError,
    ),
    "homeassistant.helpers.device_registry": _module(
        "device_registry",
        DeviceEntryType=types.SimpleNamespace(SERVICE="service"),
        DeviceInfo=dict,
    ),
    "homeassistant.helpers.entity": _module(
        "entity", EntityCategory=types.SimpleNamespace(DIAGNOSTIC="diagnostic")
    ),
    "homeassistant.const": _module(
        "const",
        PERCENTAGE="%",
        EntityCategory=types.SimpleNamespace(DIAGNOSTIC="diagnostic"),
        UnitOfTime=types.SimpleNamespace(SECONDS="s"),
    ),
    "homeassistant.components": _module("components"),
    "homeassistant.components.cover": _module(
        "cover",
        CoverDeviceClass=types.SimpleNamespace(GARAGE="garage"),
        CoverEntity=type("CoverEntity", (), {}),
        CoverEntityFeature=_Features,
    ),
    "homeassistant.components.sensor": _module(
        "sensor",
        SensorDeviceClass=types.SimpleNamespace(TIMESTAMP="timestamp", ENUM="enum"),
        SensorEntity=type("SensorEntity", (), {}),
        SensorEntityDescription=_SensorDescription,
    ),
    "homeassistant.components.binary_sensor": _module(
        "binary_sensor",
        BinarySensorDeviceClass=types.SimpleNamespace(
            CONNECTIVITY="connectivity", OPENING="opening"
        ),
        BinarySensorEntity=type("BinarySensorEntity", (), {}),
    ),
}
with patch.dict("sys.modules", _modules):
    coordinator_module = transport._load("coordinator")
    entity_module = transport._load("entity")
    cover_module = transport._load("cover")
    sensor_module = transport._load("sensor")
    binary_module = transport._load("binary_sensor")
    transport.package.TuyaSharedConfigEntry = object
    diagnostics_module = transport._load("diagnostics")


class _API:
    def __init__(self, device):
        self.device = device
        self.status = {"switch_1": False, "doorcontact_state": True, "countdown_1": 0}
        self.inventory_reads = 0
        self.fail = False
        self.commands = []

    async def async_get_shared_devices(self, uid):
        self.inventory_reads += 1
        return [self.device]

    async def async_get_status(self, device_id):
        if self.fail:
            raise transport.api.TuyaCloudConnectionError("private request URL")
        return dict(self.status)

    async def async_send_command(self, device_id, code, value):
        self.commands.append((code, value))
        self.status[code] = value


class RuntimeTests(unittest.TestCase):
    def make_coordinator(self):
        device = transport.models.TuyaSharedDevice("device", "Garage")
        api = _API(device)
        entry = types.SimpleNamespace(entry_id="entry")
        coordinator = coordinator_module.TuyaSharedCoordinator(
            types.SimpleNamespace(), entry, api, "uid", 600, [device], {}
        )
        return coordinator, api, device

    def push(self, coordinator, **values):
        coordinator.async_handle_push_payload(
            {
                "protocol": 4,
                "data": {
                    "devId": "device",
                    "status": [
                        {"code": code, "value": value} for code, value in values.items()
                    ],
                },
            }
        )

    def test_push_preserves_poll_schedule_and_failed_rest_health(self):
        async def run():
            coordinator, api, device = self.make_coordinator()
            await coordinator.async_request_refresh()
            self.assertEqual(api.inventory_reads, 0)
            api.fail = True
            await coordinator.async_request_refresh()
            scheduled_at = coordinator.scheduled_at
            coordinator.push_metrics.connected = True
            coordinator.push_metrics.subscribed = True
            for value in range(20):
                self.push(coordinator, countdown_1=value)
            self.assertEqual(coordinator.scheduled_at, scheduled_at)
            self.assertFalse(coordinator.last_update_success)
            self.assertFalse(
                binary_module.TuyaRestConnectivityBinarySensor(
                    coordinator, "entry"
                ).is_on
            )
            self.assertTrue(
                entity_module.TuyaSharedEntity(
                    coordinator, device, "switch_1"
                ).available
            )
            self.assertEqual(coordinator.data["device"]["countdown_1"], 19)
            self.assertEqual(
                coordinator.push_metrics.last_reconciliation_error_reason, "connection"
            )
            api.fail = False
            await coordinator.async_request_refresh()
            self.assertTrue(coordinator.last_update_success)

        asyncio.run(run())

    def test_command_confirmation_does_not_hide_unrelated_corrections(self):
        async def run():
            coordinator, api, _ = self.make_coordinator()
            await coordinator.async_request_refresh()
            api.status["countdown_1"] = 12
            await coordinator.async_send_command("device", "switch_1", True)
            self.assertEqual(coordinator.push_metrics.reconciliation_corrections, 1)
            self.assertTrue(coordinator.data["device"]["switch_1"])
            self.assertEqual(api.commands, [("switch_1", True)])
            self.assertFalse(coordinator._pending_command_values)

        asyncio.run(run())

    def test_open_only_cover_preserves_id_and_rejects_close(self):
        async def run():
            coordinator, api, device = self.make_coordinator()
            await coordinator.async_request_refresh()
            profile = coordinator_module.GarageDoorProfile(
                "device",
                invert_control=True,
                trust_status=False,
                allow_remote_close=False,
            )
            coordinator.garage_profiles["device"] = profile
            cover = cover_module.TuyaSharedGarageCover(coordinator, device, profile)
            self.assertEqual(cover._attr_unique_id, "device_garage_door")
            self.assertEqual(cover._attr_supported_features, _Features.OPEN)
            self.assertIsNone(cover.is_closed)
            with self.assertRaises(_HAError) as raised:
                await cover.async_close_cover()
            self.assertEqual(raised.exception.translation_key, "remote_close_disabled")
            self.assertFalse(api.commands)
            await cover.async_open_cover()
            self.assertEqual(api.commands, [("switch_1", False)])

        asyncio.run(run())

    def test_alarm_is_read_only_and_diagnostics_exclude_device_values(self):
        async def run():
            coordinator, api, device = self.make_coordinator()
            await coordinator.async_request_refresh()
            alarm = sensor_module.TuyaSharedDoorAlarmSensor(
                coordinator, device, "door_state_1"
            )
            self.push(coordinator, door_state_1="close_time_alarm")
            self.assertEqual(alarm.native_value, "close_time_alarm")
            self.push(coordinator, door_state_1="unexpected_alarm")
            self.assertIsNone(alarm.native_value)
            entry = types.SimpleNamespace(
                runtime_data=types.SimpleNamespace(
                    coordinator=coordinator,
                    push_client=types.SimpleNamespace(metrics=coordinator.push_metrics),
                )
            )
            diagnostics = await diagnostics_module.async_get_config_entry_diagnostics(
                None, entry
            )
            self.assertEqual(diagnostics["shared_device_count"], 1)
            self.assertNotIn(
                "device", repr(diagnostics).replace("shared_device_count", "")
            )
            self.assertNotIn("unexpected_alarm", repr(diagnostics))
            self.assertFalse(api.commands)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
