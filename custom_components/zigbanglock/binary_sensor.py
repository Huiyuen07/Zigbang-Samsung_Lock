"""Binary sensors: lock state + Wi-Fi connectivity."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ZigbangConfigEntry
from .const import CONF_DEVICE_ID, CONF_NAME, DEFAULT_NAME
from .entity import ZigbangEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZigbangConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    did = entry.data[CONF_DEVICE_ID]
    name = entry.data.get(CONF_NAME, DEFAULT_NAME)
    async_add_entities(
        [
            DoorlockBinarySensor(coordinator, did, name),
            DoorlockWifiBinarySensor(coordinator, did, name),
        ]
    )


class DoorlockBinarySensor(ZigbangEntity, BinarySensorEntity):
    """on = 開鎖（unlocked）。device_class lock: on=unlocked。

    純由狀態端點 `locked` 驅動；status 每 8 秒輪詢，故開門（門約 9 秒自動上鎖）
    多數會被抓到，顯示真實的開鎖區間與正確時間戳。少數被輪詢錯過的開門，仍由
    `sensor.*_last_opened` 與 `zigbanglock_event` Logbook 完整補齊。
    """

    _attr_device_class = BinarySensorDeviceClass.LOCK

    def __init__(self, coordinator, device_id, name):
        super().__init__(coordinator, device_id, name)
        self._attr_unique_id = f"{device_id}_lock"
        self._attr_name = "Lock state"

    @property
    def is_on(self) -> bool | None:
        locked = self.coordinator.data.status.locked
        return None if locked is None else not locked


class DoorlockWifiBinarySensor(ZigbangEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device_id, name):
        super().__init__(coordinator, device_id, name)
        self._attr_unique_id = f"{device_id}_wifi"
        self._attr_name = "Wi-Fi"

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.status.wifi_connected
