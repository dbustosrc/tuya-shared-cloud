"""Status and integration-diagnostic sensors for Tuya Shared Cloud."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTime

from .entity import TuyaSharedDiagnosticEntity, TuyaSharedEntity


@dataclass(frozen=True, kw_only=True)
class TuyaDiagnosticSensorEntityDescription(SensorEntityDescription):
    """Describe an account-level diagnostic sensor."""

    value_fn: Callable[[Any], Any]


DIAGNOSTIC_SENSORS: tuple[TuyaDiagnosticSensorEntityDescription, ...] = (
    TuyaDiagnosticSensorEntityDescription(
        key="last_cloud_message",
        translation_key="last_cloud_message",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:message-badge-outline",
        value_fn=lambda coordinator: coordinator.push_metrics.last_message_at,
    ),
    TuyaDiagnosticSensorEntityDescription(
        key="last_rest_poll",
        translation_key="last_rest_poll",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:cloud-sync-outline",
        value_fn=lambda coordinator: (
            coordinator.push_metrics.last_reconciliation_success_at
        ),
    ),
    TuyaDiagnosticSensorEntityDescription(
        key="push_delivery_ratio",
        translation_key="push_delivery_ratio",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
        icon="mdi:chart-donut",
        value_fn=lambda coordinator: (
            None
            if coordinator.push_metrics.push_delivery_ratio is None
            else coordinator.push_metrics.push_delivery_ratio * 100
        ),
    ),
    TuyaDiagnosticSensorEntityDescription(
        key="rest_corrections",
        translation_key="rest_corrections",
        icon="mdi:database-sync-outline",
        value_fn=lambda coordinator: (
            coordinator.push_metrics.reconciliation_corrections
        ),
    ),
    TuyaDiagnosticSensorEntityDescription(
        key="cloud_messages",
        translation_key="cloud_messages",
        icon="mdi:message-processing-outline",
        entity_registry_enabled_default=False,
        value_fn=lambda coordinator: coordinator.push_metrics.messages_received,
    ),
    TuyaDiagnosticSensorEntityDescription(
        key="ignored_cloud_messages",
        translation_key="ignored_cloud_messages",
        icon="mdi:message-alert-outline",
        entity_registry_enabled_default=False,
        value_fn=lambda coordinator: coordinator.push_metrics.ignored_messages,
    ),
    TuyaDiagnosticSensorEntityDescription(
        key="rest_polling_runs",
        translation_key="rest_polling_runs",
        icon="mdi:counter",
        entity_registry_enabled_default=False,
        value_fn=lambda coordinator: coordinator.push_metrics.reconciliation_runs,
    ),
    TuyaDiagnosticSensorEntityDescription(
        key="rest_polling_failures",
        translation_key="rest_polling_failures",
        icon="mdi:cloud-alert-outline",
        entity_registry_enabled_default=False,
        value_fn=lambda coordinator: coordinator.push_metrics.reconciliation_failures,
    ),
    TuyaDiagnosticSensorEntityDescription(
        key="rest_polling_duration",
        translation_key="rest_polling_duration",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_display_precision=2,
        icon="mdi:timer-outline",
        entity_registry_enabled_default=False,
        value_fn=lambda coordinator: (
            coordinator.push_metrics.last_reconciliation_duration_seconds
        ),
    ),
    TuyaDiagnosticSensorEntityDescription(
        key="rest_polling_interval",
        translation_key="rest_polling_interval",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        icon="mdi:update",
        entity_registry_enabled_default=False,
        value_fn=lambda coordinator: int(coordinator.update_interval.total_seconds()),
    ),
    TuyaDiagnosticSensorEntityDescription(
        key="shared_devices",
        translation_key="shared_devices",
        icon="mdi:devices",
        entity_registry_enabled_default=False,
        value_fn=lambda coordinator: len(coordinator.devices),
    ),
)


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Set up integration diagnostics and status-only datapoints."""
    coordinator = entry.runtime_data.coordinator
    entities = [
        TuyaIntegrationDiagnosticSensor(
            coordinator,
            entry.entry_id,
            description,
        )
        for description in DIAGNOSTIC_SENSORS
    ]
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


class TuyaIntegrationDiagnosticSensor(TuyaSharedDiagnosticEntity, SensorEntity):
    """Expose one account-level transport metric."""

    entity_description: TuyaDiagnosticSensorEntityDescription

    def __init__(self, coordinator, entry_id: str, description) -> None:
        super().__init__(coordinator, entry_id, description.key)
        self.entity_description = description

    @property
    def native_value(self):
        """Return the current in-memory metric without doing I/O."""
        return self.entity_description.value_fn(self.coordinator)


class TuyaSharedSensor(TuyaSharedEntity, SensorEntity):
    """A read-only Tuya datapoint."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        """Return the raw Tuya value."""
        return self.value
