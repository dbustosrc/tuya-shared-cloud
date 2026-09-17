"""Base entities for Tuya Shared Cloud."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, DP_ICONS, DP_NAMES
from .coordinator import TuyaSharedCoordinator
from .models import TuyaFunction, TuyaSharedDevice


def datapoint_name(code: str, fallback: str | None = None) -> str:
    """Return a friendly datapoint name."""
    return DP_NAMES.get(code, fallback or code.replace("_", " ").title())


class TuyaSharedDiagnosticEntity(CoordinatorEntity[TuyaSharedCoordinator]):
    """Base entity for account-level transport diagnostics."""

    _attr_available = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: TuyaSharedCoordinator,
        entry_id: str,
        key: str,
    ) -> None:
        """Attach a diagnostic entity to the integration service device."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}_service")},
            name="Tuya Shared Cloud",
            manufacturer="Tuya",
            model="Shared Cloud integration",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://github.com/dbustosrc/tuya-shared-cloud",
        )

    @property
    def available(self) -> bool:
        """Keep health entities visible when one transport is unavailable."""
        return True


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
        """Return availability while either Cloud transport remains healthy."""
        device = self.coordinator.devices.get(self.device_id)
        metrics = self.coordinator.push_metrics
        transport_available = super().available or (
            metrics.connected and metrics.subscribed
        )
        return (
            transport_available
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
