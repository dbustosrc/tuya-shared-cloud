"""Read-only Boolean status entities for Tuya Shared Cloud."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DP_DOOR_CONTACT
from .entity import TuyaSharedEntity


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Set up Boolean statuses that are not writable functions."""
    coordinator = entry.runtime_data.coordinator
    entities = [TuyaPushConnectivityBinarySensor(coordinator, entry.entry_id)]
    for device_id, status in (coordinator.data or {}).items():
        device = coordinator.devices.get(device_id)
        if device is None:
            continue
        writable = set(entry.runtime_data.functions.get(device_id, {}))
        entities.extend(
            TuyaSharedBinarySensor(coordinator, device, code)
            for code, value in status.items()
            if code not in writable and isinstance(value, bool)
        )
    async_add_entities(entities)


class TuyaPushConnectivityBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Show whether Tuya acknowledged the OpenMQ subscription."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_name = "Cloud push"

    def __init__(self, coordinator, entry_id: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_cloud_push"

    @property
    def is_on(self) -> bool:
        """Return true only after the broker acknowledges subscriptions."""
        metrics = self.coordinator.push_metrics
        return bool(metrics and metrics.connected and metrics.subscribed)

    @property
    def extra_state_attributes(self):
        """Expose evidence that push is carrying state changes."""
        metrics = self.coordinator.push_metrics
        if metrics is None:
            return {}
        ratio = metrics.push_delivery_ratio
        return {
            "messages_received": metrics.messages_received,
            "reports_applied": metrics.reports_applied,
            "datapoints_applied": metrics.datapoints_applied,
            "reconciliation_runs": metrics.reconciliation_runs,
            "reconciliation_corrections": metrics.reconciliation_corrections,
            "delivery_ratio": None if ratio is None else round(ratio, 4),
        }


class TuyaSharedBinarySensor(TuyaSharedEntity, BinarySensorEntity):
    """A read-only Tuya Boolean datapoint."""

    def __init__(self, coordinator, device, code: str) -> None:
        """Initialize a Tuya binary sensor."""
        super().__init__(coordinator, device, code)
        if code == DP_DOOR_CONTACT:
            self._attr_device_class = BinarySensorDeviceClass.OPENING

    @property
    def is_on(self) -> bool | None:
        """Return the datapoint's Boolean state."""
        return self.value if isinstance(self.value, bool) else None
