"""Base entities for Tuya Shared Cloud."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, DP_ICONS, DP_NAMES
from .coordinator import TuyaSharedCoordinator
from .models import TuyaFunction, TuyaSharedDevice


def datapoint_name(code: str, fallback: str | None = None) -> str:
    """Return a friendly datapoint name."""
    return DP_NAMES.get(code, fallback or code.replace("_", " ").title())


class TuyaSharedEntity(CoordinatorEntity[TuyaSharedCoordinator]):
    """Base class shared by all entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TuyaSharedCoordinator,
        device: TuyaSharedDevice,
        code: str,
    ) -> None:
        """Initialize a datapoint entity."""
        super().__init__(coordinator)
        self.device_id = device.device_id
        self.code = code
        self._attr_unique_id = f"{device.device_id}_{code}"
        self._attr_name = datapoint_name(code)
        self._attr_icon = DP_ICONS.get(code)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.device_id)},
            name=device.name,
            manufacturer="Tuya",
            model=device.model
            or device.product_name
            or device.category
            or "Cloud device",
            configuration_url="https://platform.tuya.com/",
        )

    @property
    def available(self) -> bool:
        """Return availability from Cloud polling and Tuya's online flag."""
        device = self.coordinator.devices.get(self.device_id)
        return (
            super().available
            and device is not None
            and device.online
            and self.device_id in (self.coordinator.data or {})
        )

    @property
    def value(self):
        """Return the current raw datapoint value."""
        return (self.coordinator.data or {}).get(self.device_id, {}).get(self.code)


class TuyaSharedFunctionEntity(TuyaSharedEntity):
    """Base entity for a writable Tuya function."""

    def __init__(
        self,
        coordinator: TuyaSharedCoordinator,
        device: TuyaSharedDevice,
        function: TuyaFunction,
    ) -> None:
        """Initialize a writable datapoint entity."""
        super().__init__(coordinator, device, function.code)
        self.function = function
        self._attr_name = datapoint_name(function.code, function.name)
