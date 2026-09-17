"""Diagnostics for Tuya Shared Cloud."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant

from . import TuyaSharedConfigEntry


def _serialize_timestamp(value: datetime | None) -> str | None:
    """Return an ISO timestamp suitable for downloaded diagnostics."""
    return value.isoformat() if value is not None else None


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: TuyaSharedConfigEntry
) -> dict[str, Any]:
    """Return transport evidence without credentials or device values."""
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
            "delivery_ratio": metrics.push_delivery_ratio,
            "last_message_at": _serialize_timestamp(metrics.last_message_at),
        },
        "rest_reconciliation": {
            "healthy": coordinator.last_update_success,
            "runs": metrics.reconciliation_runs,
            "failures": metrics.reconciliation_failures,
            "corrections": metrics.reconciliation_corrections,
            "last_attempt_at": _serialize_timestamp(
                metrics.last_reconciliation_attempt_at
            ),
            "last_success_at": _serialize_timestamp(
                metrics.last_reconciliation_success_at
            ),
            "last_failure_at": _serialize_timestamp(
                metrics.last_reconciliation_failure_at
            ),
            "last_duration_seconds": metrics.last_reconciliation_duration_seconds,
        },
    }
