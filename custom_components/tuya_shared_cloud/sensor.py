"""Read-only non-Boolean status entities for Tuya Shared Cloud."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory

from .entity import TuyaSharedEntity


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Set up status-only datapoints not represented by writable entities."""
    coordinator = entry.runtime_data.coordinator
    entities = []
    for device_id, status in (coordinator.data or {}).items():
        device = coordinator.devices.get(device_id)
        if device is None:
            continue
        writable = set(entry.runtime_data.functions.get(device_id, {}))
        entities.extend(
            TuyaSharedSensor(coordinator, device, code)
            for code, value in status.items()
            if code not in writable and not isinstance(value, bool)
        )
    async_add_entities(entities)


class TuyaSharedSensor(TuyaSharedEntity, SensorEntity):
    """A read-only Tuya datapoint."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        """Return the raw Tuya value."""
        return self.value
