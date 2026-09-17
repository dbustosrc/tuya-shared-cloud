"""Data models for Tuya Shared Cloud."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class TuyaFunction:
    """One writable Tuya datapoint definition."""

    code: str
    name: str
    type: str
    values: dict[str, Any]

    @classmethod
    def from_api(cls, value: dict[str, Any]) -> TuyaFunction:
        """Create a function definition from Tuya's response."""
        raw_values = value.get("values", {})
        if isinstance(raw_values, str):
            try:
                raw_values = json.loads(raw_values)
            except json.JSONDecodeError:
                raw_values = {}
        return cls(
            code=str(value["code"]),
            name=str(value.get("name") or value["code"]),
            type=str(value.get("type", "Raw")),
            values=raw_values if isinstance(raw_values, dict) else {},
        )


@dataclass(slots=True)
class TuyaSharedDevice:
    """A device returned specifically by Tuya's sharing inventory."""

    device_id: str
    name: str
    category: str = ""
    model: str = ""
    product_name: str = ""
    online: bool = True
    status: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, value: dict[str, Any]) -> TuyaSharedDevice:
        """Create a shared device from Tuya's API response."""
        raw_status = value.get("status", [])
        status = {
            item["code"]: item.get("value")
            for item in raw_status
            if isinstance(item, dict) and isinstance(item.get("code"), str)
        }
        return cls(
            device_id=str(value["id"]),
            name=str(value.get("name") or value["id"]).strip(),
            category=str(value.get("category", "")),
            model=str(value.get("model", "")),
            product_name=str(value.get("product_name", "")),
            online=bool(value.get("online", True)),
            status=status,
        )


@dataclass(slots=True)
class TuyaSharedRuntimeData:
    """Runtime objects owned by one account config entry."""

    coordinator: Any
    functions: dict[str, dict[str, TuyaFunction]]
    garage_profiles: dict[str, Any]
    push_client: Any
