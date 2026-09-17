"""Enum controls for Tuya Shared Cloud."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity

from .const import DOOR_CLOSE, DOOR_OPEN, DP_DOOR_CONTROL
from .entity import TuyaSharedFunctionEntity


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Set up every writable Enum datapoint on shared devices."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        TuyaSharedSelect(coordinator, coordinator.devices[device_id], function)
        for device_id, functions in entry.runtime_data.functions.items()
        if device_id in coordinator.devices
        for function in functions.values()
        if function.type.lower() == "enum"
    )


class TuyaSharedSelect(TuyaSharedFunctionEntity, SelectEntity):
    """A writable Tuya Enum datapoint."""

    def __init__(self, coordinator, device, function) -> None:
        """Initialize a Tuya select."""
        super().__init__(coordinator, device, function)
        self._attr_options = [
            str(option) for option in function.values.get("range", [])
        ]

    @property
    def current_option(self) -> str | None:
        """Return the current enum option."""
        return str(self.value) if self.value is not None else None

    async def async_select_option(self, option: str) -> None:
        """Set the enum datapoint."""
        door_command = (
            option
            if self.code == DP_DOOR_CONTROL and option in (DOOR_OPEN, DOOR_CLOSE)
            else None
        )
        await self.coordinator.async_send_command(
            self.device_id, self.code, option, door_command=door_command
        )
