"""Diagnostics: a bug-report snapshot with credentials and names removed."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import ZigbangConfigEntry
from .const import (
    CONF_AUTH_CODE,
    CONF_AUTH_TOKEN,
    CONF_DEVICE_ID,
    CONF_DEVICE_UID,
    CONF_LOGIN_ID,
    CONF_MEMBER_ID,
    CONF_PASSWORD,
)
from .parsing import LockEvent

TO_REDACT = {
    CONF_PASSWORD,
    CONF_AUTH_TOKEN,
    CONF_AUTH_CODE,
    CONF_MEMBER_ID,
    CONF_DEVICE_ID,
    CONF_DEVICE_UID,
    CONF_LOGIN_ID,
}


def _event(ev: LockEvent | None) -> dict[str, Any] | None:
    """只留排查用的欄位；人名（who/pin_name/member_name）一律不輸出。"""
    if ev is None:
        return None
    return {
        "method": ev.method,
        "pin_type": ev.pin_type,
        "is_unlock": ev.is_unlock,
        "is_lock": ev.is_lock,
        "time": ev.ts.isoformat() if ev.ts else None,
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ZigbangConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    data = coordinator.data
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "update_interval": str(coordinator.update_interval),
        },
        "status": None
        if data is None
        else {
            "locked": data.status.locked,
            "battery": data.status.battery,
            "wifi_connected": data.status.wifi_connected,
        },
        "last_event": None if data is None else _event(data.last_event),
        "last_unlock": None if data is None else _event(data.last_unlock),
    }
