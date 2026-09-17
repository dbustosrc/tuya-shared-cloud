"""Garage cover entities for Tuya Shared Cloud."""

from __future__ import annotations

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)

from .const import DOOR_CLOSE, DOOR_OPEN, DP_DOOR_CONTACT, DP_DOOR_CONTROL
from .entity import TuyaSharedEntity


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Set up a cover for each shared device with door control."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        TuyaSharedGarageCover(coordinator, coordinator.devices[device_id])
        for device_id, functions in entry.runtime_data.functions.items()
        if DP_DOOR_CONTROL in functions and device_id in coordinator.devices
    )


class TuyaSharedGarageCover(TuyaSharedEntity, CoverEntity):
    """Garage door abstraction backed by control and contact datapoints."""

    _attr_device_class = CoverDeviceClass.GARAGE
    _attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE

    def __init__(self, coordinator, device) -> None:
        """Initialize the garage cover."""
        super().__init__(coordinator, device, "garage_door")
        self._attr_name = None
        self._attr_icon = None

    @property
    def is_closed(self) -> bool | None:
        """Return whether the physical contact reports closed."""
        value = (
            (self.coordinator.data or {}).get(self.device_id, {}).get(DP_DOOR_CONTACT)
        )
        return not value if isinstance(value, bool) else None

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
            DP_DOOR_CONTROL,
            DOOR_OPEN,
            door_command=DOOR_OPEN,
        )

    async def async_close_cover(self, **kwargs) -> None:
        """Send the supported close command even if the actuator ignores it."""
        await self.coordinator.async_send_command(
            self.device_id,
            DP_DOOR_CONTROL,
            DOOR_CLOSE,
            door_command=DOOR_CLOSE,
        )
