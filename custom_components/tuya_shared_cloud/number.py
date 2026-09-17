"""Numeric controls for Tuya Shared Cloud."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfTime

from .entity import TuyaSharedFunctionEntity


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Set up every writable Integer datapoint on shared devices."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        TuyaSharedNumber(coordinator, coordinator.devices[device_id], function)
        for device_id, functions in entry.runtime_data.functions.items()
        if device_id in coordinator.devices
        for function in functions.values()
        if function.type.lower() == "integer"
    )


class TuyaSharedNumber(TuyaSharedFunctionEntity, NumberEntity):
    """A writable Tuya Integer datapoint."""

    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, device, function) -> None:
        """Initialize a Tuya number."""
        super().__init__(coordinator, device, function)
        values = function.values
        self._scale = 10 ** int(values.get("scale", 0))
        self._attr_native_min_value = float(values.get("min", 0)) / self._scale
        self._attr_native_max_value = float(values.get("max", 100)) / self._scale
        self._attr_native_step = float(values.get("step", 1)) / self._scale
        if values.get("unit") == "s":
            self._attr_device_class = NumberDeviceClass.DURATION
            self._attr_native_unit_of_measurement = UnitOfTime.SECONDS

    @property
    def native_value(self) -> float | None:
        """Return the scaled numeric value."""
        value = self.value
        return float(value) / self._scale if isinstance(value, (int, float)) else None

    async def async_set_native_value(self, value: float) -> None:
        """Set the raw integer datapoint."""
        await self.coordinator.async_send_command(
            self.device_id, self.code, round(value * self._scale)
        )
