"""Garage cover entities for Tuya Shared Cloud."""

from __future__ import annotations

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)

from .const import DOOR_CLOSE, DOOR_OPEN, DP_DOOR_CONTACT
from .entity import TuyaSharedEntity


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Set up a cover for each standard Tuya garage-door device."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        TuyaSharedGarageCover(
            coordinator,
            coordinator.devices[device_id],
            profile,
        )
        for device_id, profile in entry.runtime_data.garage_profiles.items()
        if device_id in coordinator.devices
    )


class TuyaSharedGarageCover(TuyaSharedEntity, CoverEntity):
    """Garage door abstraction backed by switch_1 and doorcontact_state."""

    _attr_device_class = CoverDeviceClass.GARAGE
    _attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE

    def __init__(self, coordinator, device, profile) -> None:
        """Initialize the garage cover."""
        super().__init__(coordinator, device, "garage_door")
        self.profile = profile
        self._attr_name = None
        self._attr_icon = None
        self._attr_assumed_state = not profile.trust_status

    @property
    def is_closed(self) -> bool | None:
        """Return whether the physical contact reports closed."""
        raw_value = (
            (self.coordinator.data or {}).get(self.device_id, {}).get(DP_DOOR_CONTACT)
        )
        return self.profile.contact_is_closed(raw_value)

    @property
    def is_opening(self) -> bool:
        """Return whether an open command is pending."""
        return self.coordinator.pending_door_command(self.device_id) == DOOR_OPEN

    @property
    def is_closing(self) -> bool:
        """Return whether a close command is pending."""
        return self.coordinator.pending_door_command(self.device_id) == DOOR_CLOSE

    @property
    def current_cover_position(self) -> int | None:
        """Map the binary contact to a cover position."""
        closed = self.is_closed
        return None if closed is None else (0 if closed else 100)

    async def async_open_cover(self, **kwargs) -> None:
        """Open the garage door."""
        await self.coordinator.async_send_command(
            self.device_id,
            self.profile.control_code,
            self.profile.command_value(DOOR_OPEN),
            door_command=DOOR_OPEN,
        )

    async def async_close_cover(self, **kwargs) -> None:
        """Send the supported close command even if the actuator ignores it."""
        await self.coordinator.async_send_command(
            self.device_id,
            self.profile.control_code,
            self.profile.command_value(DOOR_CLOSE),
            door_command=DOOR_CLOSE,
        )
