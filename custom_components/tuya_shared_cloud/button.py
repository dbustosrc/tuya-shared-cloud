"""Stateless garage-door actions for Tuya Shared Cloud."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity

from .const import DOOR_OPEN
from .entity import TuyaSharedEntity


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Set up a stateless trigger for configured garage doors."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        TuyaSharedGarageTriggerButton(
            coordinator,
            coordinator.devices[device_id],
            profile,
        )
        for device_id, profile in entry.runtime_data.garage_profiles.items()
        if profile.expose_trigger_button and device_id in coordinator.devices
    )


class TuyaSharedGarageTriggerButton(TuyaSharedEntity, ButtonEntity):
    """Send the configured open/trigger value without inferring door state."""

    _attr_translation_key = "door_trigger"
    _attr_icon = "mdi:garage-open-variant"

    def __init__(self, coordinator, device, profile) -> None:
        """Initialize the stateless garage-door trigger."""
        super().__init__(coordinator, device, "garage_trigger")
        self.profile = profile
        self._attr_name = None
        self._attr_icon = "mdi:garage-open-variant"

    async def async_press(self) -> None:
        """Send one configured trigger command to Tuya Cloud."""
        await self.coordinator.async_send_command(
            self.device_id,
            self.profile.control_code,
            self.profile.command_value(DOOR_OPEN),
        )
