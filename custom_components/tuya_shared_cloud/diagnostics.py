"""Diagnostics for Tuya Shared Cloud."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import TuyaSharedConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: TuyaSharedConfigEntry
) -> dict[str, Any]:
    """Return push-versus-poll evidence without credentials or device values."""
    coordinator = entry.runtime_data.coordinator
    metrics = entry.runtime_data.push_client.metrics
    return {
        "shared_device_count": len(coordinator.devices),
        "reconciliation_interval_seconds": int(
            coordinator.update_interval.total_seconds()
        ),
        "push": {
            "connected": metrics.connected,
            "subscribed": metrics.subscribed,
            "messages_received": metrics.messages_received,
            "reports_applied": metrics.reports_applied,
            "datapoints_applied": metrics.datapoints_applied,
            "ignored_messages": metrics.ignored_messages,
            "reconciliation_runs": metrics.reconciliation_runs,
            "reconciliation_corrections": metrics.reconciliation_corrections,
            "delivery_ratio": metrics.push_delivery_ratio,
            "has_received_message": metrics.last_message_monotonic is not None,
        },
    }
