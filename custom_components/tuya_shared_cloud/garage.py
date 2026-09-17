"""Garage-door profiles and Tuya product quirks.

This module intentionally has no Home Assistant imports so command and status
mapping can be tested independently from the integration runtime.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .const import (
    CATEGORY_GARAGE_DOOR,
    CONF_EXPOSE_TRIGGER_BUTTON,
    CONF_GARAGE_DEVICES,
    CONF_INVERT_COVER_CONTROL,
    CONF_INVERT_COVER_STATUS,
    CONF_TRUST_COVER_STATUS,
    DOOR_CLOSE,
    DOOR_OPEN,
    DP_SWITCH_1,
)
from .models import TuyaFunction, TuyaSharedDevice


@dataclass(frozen=True, slots=True)
class GarageDoorProfile:
    """Per-device interpretation of Tuya garage-door datapoints."""

    device_id: str
    control_code: str = DP_SWITCH_1
    invert_control: bool = False
    invert_status: bool = False
    trust_status: bool = True
    expose_trigger_button: bool = True

    def command_value(self, command: str) -> bool:
        """Map a Home Assistant open/close command to Tuya's Boolean value."""
        if command not in (DOOR_OPEN, DOOR_CLOSE):
            raise ValueError(f"Unsupported garage-door command: {command}")
        value = command == DOOR_OPEN
        return not value if self.invert_control else value

    def contact_is_closed(self, raw_value: Any) -> bool | None:
        """Map Tuya's contact value to closed, or unknown when untrusted."""
        if not self.trust_status or not isinstance(raw_value, bool):
            return None
        contact_is_open = not raw_value if self.invert_status else raw_value
        return not contact_is_open


def device_garage_options(
    options: Mapping[str, Any], device_id: str
) -> Mapping[str, Any]:
    """Return safely parsed options for one garage-door device."""
    garage_devices = options.get(CONF_GARAGE_DEVICES, {})
    if not isinstance(garage_devices, Mapping):
        return {}
    device_options = garage_devices.get(device_id, {})
    return device_options if isinstance(device_options, Mapping) else {}


def build_garage_profiles(
    devices: list[TuyaSharedDevice],
    functions: Mapping[str, Mapping[str, TuyaFunction]],
    options: Mapping[str, Any],
) -> dict[str, GarageDoorProfile]:
    """Build profiles only for standard Tuya garage-door devices."""
    profiles: dict[str, GarageDoorProfile] = {}
    for device in devices:
        device_functions = functions.get(device.device_id, {})
        control = device_functions.get(DP_SWITCH_1)
        if (
            device.category != CATEGORY_GARAGE_DOOR
            or control is None
            or control.type.lower() != "boolean"
        ):
            continue
        configured = device_garage_options(options, device.device_id)
        profiles[device.device_id] = GarageDoorProfile(
            device_id=device.device_id,
            invert_control=bool(configured.get(CONF_INVERT_COVER_CONTROL, False)),
            invert_status=bool(configured.get(CONF_INVERT_COVER_STATUS, False)),
            trust_status=bool(configured.get(CONF_TRUST_COVER_STATUS, True)),
            expose_trigger_button=bool(
                configured.get(CONF_EXPOSE_TRIGGER_BUTTON, True)
            ),
        )
    return profiles
