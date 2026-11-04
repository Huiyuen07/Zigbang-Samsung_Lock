"""Config flow tests (login, lock selection, reauth) with a fake cloud client."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zigbanglock import async_setup_entry as REAL_SETUP_ENTRY
from custom_components.zigbanglock.api import ZigbangAuthError
from custom_components.zigbanglock.const import (
    CONF_DEVICE_ID,
    CONF_DEVICE_UID,
    CONF_LOGIN_ID,
    CONF_NAME,
    CONF_PASSWORD,
    DOMAIN,
)

LOCK_A = {"device_id": "dev-aaaa", "name": "Front Door"}
LOCK_B = {"device_id": "dev-bbbb", "name": "Back Door"}
USER_INPUT = {CONF_NAME: "Doorlock", CONF_LOGIN_ID: "tester", CONF_PASSWORD: "pw"}


class FakeClient:
    """取代 ZigbangLockClient：登入結果與門鎖清單由測試設定。"""

    locks: list[dict[str, str]] = [LOCK_A]
    login_error: Exception | None = None
    instances: list["FakeClient"] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.member_id = "mem-yyyy"
        self.auth_token = "tok"
        self.auth_code = "ac"
        FakeClient.instances.append(self)

    async def async_login(self):
        if FakeClient.login_error is not None:
            raise FakeClient.login_error

    async def async_get_doorlocks(self):
        return list(FakeClient.locks)


@pytest.fixture(autouse=True)
def fake_client():
    FakeClient.locks = [LOCK_A]
    FakeClient.login_error = None
    FakeClient.instances = []
    with (
        patch("custom_components.zigbanglock.config_flow.ZigbangLockClient", FakeClient),
        patch("custom_components.zigbanglock.async_setup_entry", return_value=True),
    ):
        yield FakeClient


async def _start(hass: HomeAssistant):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def test_single_lock_creates_entry(hass: HomeAssistant) -> None:
    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Doorlock"
    data = result["data"]
    assert data[CONF_DEVICE_ID] == "dev-aaaa"
    assert data[CONF_LOGIN_ID] == "tester"
    assert len(data[CONF_DEVICE_UID]) == 16
    assert result["result"].unique_id == "dev-aaaa"


@pytest.mark.parametrize(
    ("error", "key"),
    [
        (ZigbangAuthError("bad"), "invalid_auth"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_login_errors_show_form(hass: HomeAssistant, error, key) -> None:
    FakeClient.login_error = error
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": key}


async def test_no_locks(hass: HomeAssistant) -> None:
    FakeClient.locks = []
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["errors"] == {"base": "no_locks"}


async def test_two_locks_pick_second(hass: HomeAssistant) -> None:
    FakeClient.locks = [LOCK_A, LOCK_B]
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "pick_lock"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_DEVICE_ID: "dev-bbbb"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Back Door"
    assert result["data"][CONF_DEVICE_ID] == "dev-bbbb"


async def test_second_lock_added_when_first_configured(hass: HomeAssistant) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id="dev-aaaa", data={}).add_to_hass(hass)
    FakeClient.locks = [LOCK_A, LOCK_B]
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    # 只剩一把未設定 → 不用揀，直接建立
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_DEVICE_ID] == "dev-bbbb"
    assert result["title"] == "Back Door"


async def test_all_locks_configured_aborts(hass: HomeAssistant) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id="dev-aaaa", data={}).add_to_hass(hass)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


def _entry(hass: HomeAssistant, **data) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="dev-aaaa",
        title="Front Door",
        data={CONF_DEVICE_ID: "dev-aaaa", **data},
    )
    entry.add_to_hass(hass)
    return entry


async def test_reauth_password_only(hass: HomeAssistant) -> None:
    entry = _entry(hass, **{CONF_LOGIN_ID: "tester", CONF_PASSWORD: "old", CONF_DEVICE_UID: "abcd1234abcd1234"})
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    assert list(result["data_schema"].schema) == [CONF_PASSWORD]
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_PASSWORD: "new"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "new"
    assert entry.data[CONF_DEVICE_UID] == "abcd1234abcd1234"


async def test_reauth_legacy_entry_asks_account(hass: HomeAssistant) -> None:
    entry = _entry(hass)
    result = await entry.start_reauth_flow(hass)
    assert list(result["data_schema"].schema) == [CONF_LOGIN_ID, CONF_PASSWORD]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_LOGIN_ID: "tester", CONF_PASSWORD: "pw"}
    )
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_LOGIN_ID] == "tester"
    assert len(entry.data[CONF_DEVICE_UID]) == 16


async def test_reauth_wrong_account(hass: HomeAssistant) -> None:
    entry = _entry(hass, **{CONF_LOGIN_ID: "tester", CONF_PASSWORD: "old"})
    FakeClient.locks = [LOCK_B]
    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_PASSWORD: "new"})
    assert result["errors"] == {"base": "wrong_account"}


async def test_setup_without_account_starts_reauth(hass: HomeAssistant) -> None:
    entry = _entry(hass)  # 舊版 entry：沒有帳號
    with patch("custom_components.zigbanglock.async_setup_entry", REAL_SETUP_ENTRY):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == [config_entries.SOURCE_REAUTH]
