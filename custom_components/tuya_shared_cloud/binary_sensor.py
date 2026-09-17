"""Read-only Boolean status entities for Tuya Shared Cloud."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)

from .const import DP_DOOR_CONTACT
from .entity import TuyaSharedDiagnosticEntity, TuyaSharedEntity


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Set up transport health and read-only Boolean datapoints."""
    coordinator = entry.runtime_data.coordinator
    entities = [
        TuyaPushConnectivityBinarySensor(coordinator, entry.entry_id),
        TuyaRestConnectivityBinarySensor(coordinator, entry.entry_id),
    ]
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


class TuyaPushConnectivityBinarySensor(TuyaSharedDiagnosticEntity, BinarySensorEntity):
    """Show whether Tuya acknowledged the OpenMQ subscription."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "cloud_push"

    def __init__(self, coordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id, "cloud_push")

    @property
    def is_on(self) -> bool:
        """Return true only after the broker acknowledges subscriptions."""
        metrics = self.coordinator.push_metrics
        return metrics.connected and metrics.subscribed

    @property
    def extra_state_attributes(self):
        """Retain the existing summary attributes for compatibility."""
        metrics = self.coordinator.push_metrics
        ratio = metrics.push_delivery_ratio
        return {
            "messages_received": metrics.messages_received,
            "reports_applied": metrics.reports_applied,
            "datapoints_applied": metrics.datapoints_applied,
            "reconciliation_runs": metrics.reconciliation_runs,
            "reconciliation_corrections": metrics.reconciliation_corrections,
            "delivery_ratio": None if ratio is None else round(ratio, 4),
        }


class TuyaRestConnectivityBinarySensor(TuyaSharedDiagnosticEntity, BinarySensorEntity):
    """Show whether the most recent REST reconciliation succeeded."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "rest_polling"

    def __init__(self, coordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id, "rest_polling")

    @property
    def is_on(self) -> bool:
        """Return the health of the latest coordinator refresh."""
        return self.coordinator.last_update_success


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
