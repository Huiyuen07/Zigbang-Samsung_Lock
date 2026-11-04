"""Diagnostics must not leak credentials or people's names."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zigbanglock.const import DOMAIN
from custom_components.zigbanglock.diagnostics import async_get_config_entry_diagnostics
from custom_components.zigbanglock.parsing import LockEvent, LockStatus

SECRETS = ["tester", "pw", "tok", "ac", "mem-yyyy", "dev-xxxx", "abcd1234abcd1234", "TestMember"]


async def test_diagnostics_redacts(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "login_id": "tester",
            "password": "pw",
            "auth_token": "tok",
            "auth_code": "ac",
            "member_id": "mem-yyyy",
            "device_id": "dev-xxxx",
            "device_uid": "abcd1234abcd1234",
            "locale": "en_US",
        },
    )
    ev = LockEvent(
        event_id="evt-0001",
        ts=datetime(2026, 1, 1, tzinfo=timezone.utc),
        device_name="Front Door",
        msg="Unlocked",
        submsg="",
        msg_code="622_1",
        pin_type="FGP",
        method="fingerprint",
        pin_name="TestMember",
        member_name="TestMember",
        member_id="mem-yyyy",
        is_unlock=True,
    )
    entry.runtime_data = SimpleNamespace(
        data=SimpleNamespace(
            status=LockStatus(locked=True, battery=80, wifi_connected=True),
            last_event=ev,
            last_unlock=ev,
        ),
        last_update_success=True,
        update_interval=timedelta(seconds=8),
    )
    diag = await async_get_config_entry_diagnostics(hass, entry)
    text = repr(diag)
    for secret in SECRETS:
        assert f"'{secret}'" not in text, secret
    assert diag["status"]["battery"] == 80
    assert diag["last_event"]["method"] == "fingerprint"
