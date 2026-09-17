"""Boolean controls for Tuya Shared Cloud."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory

from .const import DP_VOICE_CONTROL
from .entity import TuyaSharedFunctionEntity


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Set up every writable Boolean datapoint on shared devices."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        TuyaSharedSwitch(coordinator, coordinator.devices[device_id], function)
        for device_id, functions in entry.runtime_data.functions.items()
        if device_id in coordinator.devices
        for function in functions.values()
        if function.type.lower() == "boolean"
    )


class TuyaSharedSwitch(TuyaSharedFunctionEntity, SwitchEntity):
    """A writable Tuya Boolean datapoint."""

    def __init__(self, coordinator, device, function) -> None:
        """Initialize a Tuya switch."""
        super().__init__(coordinator, device, function)
        if function.code == DP_VOICE_CONTROL:
            self._attr_entity_category = EntityCategory.CONFIG

    @property
    def is_on(self) -> bool | None:
        """Return whether the datapoint is on."""
        return self.value if isinstance(self.value, bool) else None

    async def async_turn_on(self, **kwargs) -> None:
        """Set the datapoint to true."""
        await self.coordinator.async_send_command(self.device_id, self.code, True)

    async def async_turn_off(self, **kwargs) -> None:
        """Set the datapoint to false."""
        await self.coordinator.async_send_command(self.device_id, self.code, False)
