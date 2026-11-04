"""Offline unit tests for the pure parsing layer (no Home Assistant needed)."""
from __future__ import annotations

import json
import sys
from datetime import timezone
from pathlib import Path

import pytest

# 讓測試能 import custom_components/zigbanglock/parsing.py
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "custom_components" / "zigbanglock"))

from parsing import (  # noqa: E402
    LockStatus,
    ZigbangApiError,
    format_lock_message,
    latest_unlock,
    new_events_since,
    parse_event,
    parse_history,
    parse_status,
)

FIX = ROOT / "tests" / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIX / name).read_text())


def test_parse_status():
    st = parse_status(_load("status.json"))
    assert isinstance(st, LockStatus)
    assert st.locked is True
    assert st.battery == 51
    assert st.wifi_connected is True


def test_parse_status_rejects_auth_error():
    with pytest.raises(ZigbangApiError):
        parse_status(_load("error_auth.json"))


def test_parse_history_count_and_order():
    events = parse_history(_load("history.json"))
    assert len(events) == 5
    # API 原順序：最新在前
    assert events[0].event_id == "evt-0001"


def test_event_timestamp_is_utc():
    events = parse_history(_load("history.json"))
    ev = events[0]
    assert ev.ts is not None
    assert ev.ts.tzinfo == timezone.utc
    assert ev.ts.hour == 3 and ev.ts.minute == 25  # rgstDt 當 UTC 解析


def test_fingerprint_event_who_and_method():
    events = {e.event_id: e for e in parse_history(_load("history.json"))}
    fgp = events["evt-0003"]
    assert fgp.method == "fingerprint"
    assert fgp.pin_name == "TestFinger"
    assert fgp.member_name == "TestMember"
    assert fgp.who == "TestFinger"
    assert fgp.is_unlock is True


def test_auto_lock_is_not_unlock_and_has_no_who():
    events = {e.event_id: e for e in parse_history(_load("history.json"))}
    auto = events["evt-0001"]
    assert auto.method == "auto_lock"
    assert auto.is_unlock is False
    assert auto.is_lock is True
    assert auto.who is None


def test_unlock_event_is_not_a_lock_action():
    events = {e.event_id: e for e in parse_history(_load("history.json"))}
    fgp = events["evt-0003"]
    assert fgp.is_unlock is True
    assert fgp.is_lock is False


def test_warning_event_is_neither_lock_nor_unlock():
    events = {e.event_id: e for e in parse_history(_load("history.json"))}
    warn = events["evt-0004"]  # msgCd 648 門開太久警告
    assert warn.is_unlock is False
    assert warn.is_lock is False


def test_indoor_unlock_classified():
    events = {e.event_id: e for e in parse_history(_load("history.json"))}
    indoor = events["evt-0002"]
    assert indoor.is_unlock is True
    assert indoor.method == "indoor_button"


def test_warning_event_not_unlock():
    events = {e.event_id: e for e in parse_history(_load("history.json"))}
    warn = events["evt-0004"]  # msgCd 648
    assert warn.is_unlock is False


def test_app_remote_unlock_svr():
    # 實測抓到：pinTypeCd=SVR, msgText 由 App 遠端解鎖
    ev = parse_event(
        {
            "eventId": "evt-svr",
            "deviceNm": "Front Door",
            "msgText": "TestMember unlocked the door by App",
            "pinTypeCd": "SVR",
            "eventMemberNm": "TestMember",
            "eventMemberId": "mem-yyyy",
            "rgstDt": "2026-10-25 03:41:50",
        }
    )
    assert ev.method == "app"
    assert ev.is_unlock is True
    assert ev.who == "TestMember"


def test_new_events_since_baseline():
    events = parse_history(_load("history.json"))
    # 已見過前兩筆，應只回新的三筆，且由舊到新排序
    seen = {"evt-0001", "evt-0002"}
    fresh = new_events_since(events, seen)
    assert [e.event_id for e in fresh] == ["evt-0005", "evt-0004", "evt-0003"]


def test_new_events_since_all_seen_returns_empty():
    events = parse_history(_load("history.json"))
    seen = {e.event_id for e in events}
    assert new_events_since(events, seen) == []


def test_latest_unlock_picks_newest_unlock():
    events = parse_history(_load("history.json"))
    lu = latest_unlock(events)
    # events 最新在前；第一筆是 auto-lock（evt-0001），故最近開鎖為 evt-0002
    assert lu is not None
    assert lu.event_id == "evt-0002"
    assert lu.is_unlock is True


def test_latest_unlock_none_when_no_unlock():
    auto = parse_event(
        {"eventId": "x", "msgCd": "622_NONE_AUTO", "pinTypeCd": "AUTO",
         "rgstDt": "2026-10-25 03:00:00"}
    )
    assert latest_unlock([auto]) is None
    assert latest_unlock([]) is None


def test_format_lock_message_prefers_api_text():
    # 有 msgText 就原樣沿用（忠於 app 顯示），submsg 接在後面
    out = format_lock_message(
        True, "TestMember", "fingerprint", "TestMember unlocked the door", "by fingerprint"
    )
    assert out == "TestMember unlocked the door by fingerprint"


def test_format_lock_message_fallback_unlock():
    out = format_lock_message(True, "TestMember", "fingerprint", "", "")
    assert out == "TestMember unlocked the door (fingerprint)"


def test_format_lock_message_fallback_lock_without_who():
    out = format_lock_message(False, None, "auto_lock", "", "")
    assert out == "Someone locked the door (auto_lock)"
