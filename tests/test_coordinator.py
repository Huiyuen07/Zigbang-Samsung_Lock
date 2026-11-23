"""Coordinator auth handling: transient cloud errors must not trigger reauth right away."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zigbanglock.api import ZigbangAuthError
from custom_components.zigbanglock.const import DOMAIN
from custom_components.zigbanglock.coordinator import AUTH_GRACE, ZigbangCoordinator
from custom_components.zigbanglock.parsing import LockStatus


class FakeClient:
    def __init__(self, *, can_login: bool = True):
        self._can_login = can_login
        self.fail = True

    def can_login(self) -> bool:
        return self._can_login

    async def async_get_status(self) -> LockStatus:
        if self.fail:
            raise ZigbangAuthError("RunTimeException failed. (E402)")
        return LockStatus(locked=True, battery=50, wifi_connected=True, raw={})

    async def async_get_history(self):
        return []


def _coordinator(hass: HomeAssistant, client: FakeClient) -> ZigbangCoordinator:
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    return ZigbangCoordinator(
        hass,
        entry,
        client,
        device_id="dev-aaaa",
        name="Front Door",
        status_interval=timedelta(seconds=8),
        history_interval=timedelta(seconds=1800),
    )


async def test_auth_error_within_grace_is_update_failed(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, FakeClient())
    with pytest.raises(UpdateFailed):
        await coord._async_update_data()


async def test_auth_error_past_grace_triggers_reauth(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, FakeClient())
    start = dt_util.utcnow()
    with patch("custom_components.zigbanglock.coordinator.dt_util.utcnow", return_value=start):
        with pytest.raises(UpdateFailed):
            await coord._async_update_data()
    later = start + AUTH_GRACE + timedelta(seconds=1)
    with patch("custom_components.zigbanglock.coordinator.dt_util.utcnow", return_value=later):
        with pytest.raises(ConfigEntryAuthFailed):
            await coord._async_update_data()


async def test_recovery_resets_grace(hass: HomeAssistant) -> None:
    client = FakeClient()
    coord = _coordinator(hass, client)
    start = dt_util.utcnow()
    with patch("custom_components.zigbanglock.coordinator.dt_util.utcnow", return_value=start):
        with pytest.raises(UpdateFailed):
            await coord._async_update_data()
    client.fail = False
    mid = start + timedelta(minutes=30)
    with patch("custom_components.zigbanglock.coordinator.dt_util.utcnow", return_value=mid):
        data = await coord._async_update_data()
    assert data.status.locked is True
    # 恢復後重新計時：距首次失敗已超過寬限期，但這是新一輪失敗，仍未到 reauth
    client.fail = True
    later = start + AUTH_GRACE + timedelta(minutes=29)
    with patch("custom_components.zigbanglock.coordinator.dt_util.utcnow", return_value=later):
        with pytest.raises(UpdateFailed):
            await coord._async_update_data()


async def test_no_credentials_reauth_immediately(hass: HomeAssistant) -> None:
    coord = _coordinator(hass, FakeClient(can_login=False))
    with pytest.raises(ConfigEntryAuthFailed):
        await coord._async_update_data()
