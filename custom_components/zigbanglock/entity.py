"""Shared base entity / device info."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import ZigbangCoordinator


class ZigbangEntity(CoordinatorEntity[ZigbangCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: ZigbangCoordinator, device_id: str, name: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=coordinator.device_name or name,
            manufacturer=MANUFACTURER,
            model=MODEL,
        )
