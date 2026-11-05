"""Zigbang / Samsung smart doorlock integration.

設定方式（UI）：設定 → 裝置與服務 → 新增整合 → "Zigbang"，填入帳號密碼，
整合會自行登入、自動帶出門鎖，並在 token 失效時自動重登。
"""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ZigbangLockClient
from .const import (
    CONF_AUTH_CODE,
    CONF_AUTH_TOKEN,
    CONF_BASE_URL,
    CONF_DEVICE_ID,
    CONF_DEVICE_UID,
    CONF_LOCALE,
    CONF_LOGIN_ID,
    CONF_MEMBER_ID,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_STATUS_INTERVAL,
    DEFAULT_BASE_URL,
    DEFAULT_HISTORY_INTERVAL,
    DEFAULT_LOCALE,
    DEFAULT_NAME,
    DEFAULT_STATUS_INTERVAL,
    MAX_STATUS_INTERVAL,
    MIN_STATUS_INTERVAL,
)
from .coordinator import ZigbangCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SENSOR]

type ZigbangConfigEntry = ConfigEntry[ZigbangCoordinator]


def _current_locale(entry: ConfigEntry) -> str:
    """語言：options（可隨時改）優先於 data（建立時的值）。"""
    return entry.options.get(
        CONF_LOCALE, entry.data.get(CONF_LOCALE, DEFAULT_LOCALE)
    )


def _status_interval(entry: ConfigEntry) -> timedelta:
    """狀態輪詢間隔：options 的秒數（夾在允許範圍內），未設定則用預設 8 秒。"""
    seconds = entry.options.get(CONF_STATUS_INTERVAL)
    if seconds is None:
        return DEFAULT_STATUS_INTERVAL
    return timedelta(
        seconds=min(max(int(seconds), MIN_STATUS_INTERVAL), MAX_STATUS_INTERVAL)
    )


async def async_setup_entry(hass: HomeAssistant, entry: ZigbangConfigEntry) -> bool:
    data = entry.data
    if not data.get(CONF_LOGIN_ID):
        # 舊版 token-only entry：沒有帳號就無法自動重登，請用戶重新驗證補上帳密。
        raise ConfigEntryAuthFailed("account login is required")
    client = ZigbangLockClient(
        session=async_get_clientsession(hass),
        base_url=data.get(CONF_BASE_URL, DEFAULT_BASE_URL),
        member_id=data.get(CONF_MEMBER_ID, ""),
        device_id=data[CONF_DEVICE_ID],
        auth_token=data.get(CONF_AUTH_TOKEN, ""),
        auth_code=data.get(CONF_AUTH_CODE, ""),
        locale=_current_locale(entry),
        login_id=data.get(CONF_LOGIN_ID),
        password=data.get(CONF_PASSWORD),
        device_uid=data.get(CONF_DEVICE_UID),
    )
    coordinator = ZigbangCoordinator(
        hass,
        entry,
        client,
        device_id=data[CONF_DEVICE_ID],
        name=data.get(CONF_NAME, DEFAULT_NAME),
        status_interval=_status_interval(entry),
        history_interval=DEFAULT_HISTORY_INTERVAL,
    )

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_update_options))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_update_options(
    hass: HomeAssistant, entry: ZigbangConfigEntry
) -> None:
    """語言、輪詢間隔等選項改動後重新載入整合。"""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ZigbangConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
