"""Logbook platform: render each zigbanglock_event as a Logbook entry.

每筆進出紀錄（開/上鎖、誰、方式）都會原生出現在 HA 的 Logbook。事件資料帶
HA 的 device_id，故亦會出現在門鎖裝置頁；刻意不掛 entity_id，免得使用者用
`logbook: exclude` 隱藏某個實體時連這些條目一齊被藏。
"""
from __future__ import annotations

from collections.abc import Callable

from homeassistant.components.logbook import (
    LOGBOOK_ENTRY_MESSAGE,
    LOGBOOK_ENTRY_NAME,
)
from homeassistant.core import Event, HomeAssistant, callback

from .const import DEFAULT_NAME, DOMAIN, EVENT_LOCK
from .parsing import format_lock_message


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[[str, str, Callable[[Event], dict[str, str]]], None],
) -> None:
    @callback
    def async_describe_lock_event(event: Event) -> dict[str, str]:
        data = event.data
        return {
            LOGBOOK_ENTRY_NAME: data.get("device_name") or DEFAULT_NAME,
            LOGBOOK_ENTRY_MESSAGE: format_lock_message(
                data.get("is_unlock"),
                data.get("who"),
                data.get("method"),
                data.get("message") or "",
                data.get("sub_message") or "",
            ),
        }

    async_describe_event(DOMAIN, EVENT_LOCK, async_describe_lock_event)
