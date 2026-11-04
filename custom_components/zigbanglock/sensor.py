"""Sensors: battery, last event and last opened (who/when/how)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ZigbangConfigEntry
from .const import CONF_DEVICE_ID, CONF_NAME, DEFAULT_NAME
from .entity import ZigbangEntity
from .parsing import LockEvent


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
            DoorlockBatterySensor(coordinator, did, name),
            DoorlockLastEventSensor(coordinator, did, name),
            DoorlockLastOpenedSensor(coordinator, did, name),
        ]
    )


def _who_attrs(ev: LockEvent) -> dict[str, Any]:
    """「誰/怎樣」共用 attributes（last_event 與 last_opened 一致）。"""
    return {
        "who": ev.who,
        "method": ev.method,
        "pin_type": ev.pin_type,
        "pin_name": ev.pin_name,
        "member_name": ev.member_name,
        "event_id": ev.event_id,
    }


class DoorlockBatterySensor(ZigbangEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, device_id, name):
        super().__init__(coordinator, device_id, name)
        self._attr_unique_id = f"{device_id}_battery"
        self._attr_name = "Battery"

    @property
    def native_value(self) -> int | None:
        return self.coordinator.data.status.battery


class DoorlockLastEventSensor(ZigbangEntity, SensorEntity):
    """state = 最近一筆事件訊息；attributes 帶 誰/方式/時間。"""

    _attr_icon = "mdi:door"

    def __init__(self, coordinator, device_id, name):
        super().__init__(coordinator, device_id, name)
        self._attr_unique_id = f"{device_id}_last_event"
        self._attr_name = "Last event"

    @property
    def native_value(self) -> str | None:
        ev = self.coordinator.data.last_event
        if ev is None:
            return None
        return f"{ev.msg} {ev.submsg}".strip()[:255]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        ev = self.coordinator.data.last_event
        if ev is None:
            return {}
        return {
            **_who_attrs(ev),
            "is_unlock": ev.is_unlock,
            "time_utc": ev.ts.isoformat() if ev.ts else None,
        }


class DoorlockLastOpenedSensor(ZigbangEntity, SensorEntity):
    """最近一次「開鎖」的時間（device_class timestamp）。

    只在開鎖事件更新，不會被 ~9 秒後的自動上鎖蓋掉；每次開門都是新時間戳，
    故狀態必定改變 → 一定會寫進 Logbook 並在 UI 反映。attributes 帶誰/方式/訊息。
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:door-open"

    def __init__(self, coordinator, device_id, name):
        super().__init__(coordinator, device_id, name)
        self._attr_unique_id = f"{device_id}_last_opened"
        self._attr_name = "Last opened"

    @property
    def native_value(self) -> datetime | None:
        ev = self.coordinator.data.last_unlock
        return ev.ts if ev else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        ev = self.coordinator.data.last_unlock
        if ev is None:
            return {}
        return {**_who_attrs(ev), "message": f"{ev.msg} {ev.submsg}".strip()}
