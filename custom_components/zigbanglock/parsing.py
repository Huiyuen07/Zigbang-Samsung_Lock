"""Pure parsing helpers for the Zigbang / Samsung smart doorlock cloud API.

這個模組刻意「純函式、無 Home Assistant 依賴」，方便離線單元測試。
This module is intentionally pure (no Home Assistant imports) so it can be
unit-tested offline against anonymised API fixtures.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# API 回傳的 rgstDt 是 UTC（實測：HKT 11:25 → rgstDt 03:25），不帶時區字串。
# The API's rgstDt is UTC despite the account's zoneRegionId; no tz suffix.
_RGST_FMT = "%Y-%m-%d %H:%M:%S"

# pinTypeCd → 人類可讀的「開/關鎖方式」。None/未知保留原碼。
# pinTypeCd -> human readable method. Unknown codes are passed through.
PIN_TYPE_LABELS = {
    "FGP": "fingerprint",
    "INDOOR": "indoor_button",
    "AUTO": "auto_lock",
    "MNU": "manual",
    "NUM": "keypad",
    "RFC": "rfid_card",
    "NFC": "nfc",
    "MST": "mobile",
    "SVR": "app",          # App 遠端開鎖（msgText: "… unlocked the door by App"）
    "ONE": "one_time_code",
}

# 明確屬於「開鎖」的 pinType（當 msgCd 無法判斷時的後備）。
# AUTO/MNU 為上鎖動作，不列入。
_UNLOCK_PIN_TYPES = {"FGP", "INDOOR", "NUM", "RFC", "NFC", "MST", "SVR", "ONE"}


class ZigbangApiError(Exception):
    """API 回了 result=false 等非成功狀態。Raised when result != true."""


def _api_ok(payload: dict[str, Any]) -> bool:
    return bool(payload.get("result")) and payload.get("code") == "S001"


def ensure_ok(payload: dict[str, Any]) -> dict[str, Any]:
    """成功就原樣回傳，否則丟 ZigbangApiError。"""
    if not _api_ok(payload):
        raise ZigbangApiError(
            payload.get("errorMessage") or payload.get("message") or payload.get("code") or "unknown"
        )
    return payload


@dataclass(frozen=True)
class LockStatus:
    locked: bool | None
    battery: int | None
    wifi_connected: bool | None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


def parse_status(payload: dict[str, Any]) -> LockStatus:
    """doorlockstatus 回應 → LockStatus。"""
    vo = ensure_ok(payload).get("doorlockStatusVO") or {}
    return LockStatus(
        locked=bool(vo["locked"]) if "locked" in vo else None,
        battery=int(vo["battery"]) if vo.get("battery") is not None else None,
        wifi_connected=bool(vo["wifiConnected"]) if "wifiConnected" in vo else None,
        raw=vo,
    )


@dataclass(frozen=True)
class LockEvent:
    event_id: str
    ts: datetime | None            # UTC, tz-aware
    device_name: str | None
    msg: str                       # msgText
    submsg: str                    # subMsgText
    msg_code: str | None           # msgCd
    pin_type: str | None           # pinTypeCd (raw)
    method: str | None             # 人類可讀，由 pin_type 映射
    pin_name: str | None           # pinNm，指紋/鑰匙名稱
    member_name: str | None        # eventMemberNm，帳號成員名稱
    member_id: str | None
    is_unlock: bool                # 這筆是否為「開鎖」事件

    @property
    def who(self) -> str | None:
        """誰開鎖：優先用指紋/鑰匙名，其次帳號成員名。無則 None（如自動上鎖）。"""
        return self.pin_name or self.member_name

    @property
    def is_lock(self) -> bool:
        """這筆是否為「上鎖」動作（自動/手動上鎖）。警告類（門開太久）不算。"""
        return (self.msg_code or "").startswith("622_NONE")


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, _RGST_FMT).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _is_unlock(msg_code: str | None, pin_type: str | None) -> bool:
    code = (msg_code or "")
    # 622_NONE_AUTO / 622_NONE_MNU = 上鎖；622_OUT / 622_IN_* = 開鎖
    if code.startswith("622_NONE"):
        return False
    if code.startswith("622"):
        return True
    # msgCd 無法判斷時（如 SVR App 遠端），退回看 pinType
    if pin_type in _UNLOCK_PIN_TYPES:
        return True
    # 648/652 = 門開太久等警告，非開鎖動作
    return False


def parse_event(item: dict[str, Any]) -> LockEvent:
    pin_type = item.get("pinTypeCd") or None
    msg_code = item.get("msgCd") or None
    return LockEvent(
        event_id=item.get("eventId") or "",
        ts=_parse_ts(item.get("rgstDt")),
        device_name=item.get("deviceNm") or None,
        msg=item.get("msgText") or "",
        submsg=item.get("subMsgText") or "",
        msg_code=msg_code,
        pin_type=pin_type,
        method=PIN_TYPE_LABELS.get(pin_type, pin_type),
        pin_name=item.get("pinNm") or None,
        member_name=item.get("eventMemberNm") or None,
        member_id=item.get("eventMemberId") or None,
        is_unlock=_is_unlock(msg_code, pin_type),
    )


def parse_history(payload: dict[str, Any]) -> list[LockEvent]:
    """inouthistory 回應 → LockEvent 清單（維持 API 原順序：最新在前）。"""
    items = ensure_ok(payload).get("historyVOList") or []
    return [parse_event(i) for i in items]


def new_events_since(
    events: list[LockEvent], seen_ids: set[str]
) -> list[LockEvent]:
    """回傳 seen_ids 未見過的事件，依時間由舊到新（方便依序派發/通知）。"""
    fresh = [e for e in events if e.event_id and e.event_id not in seen_ids]
    fresh.sort(key=lambda e: (e.ts or datetime.min.replace(tzinfo=timezone.utc)))
    return fresh


def latest_unlock(events: list[LockEvent]) -> LockEvent | None:
    """最近一筆「開鎖」事件（events 以最新在前）；無則 None。

    供「最近開門」實體使用：門約 9 秒自動上鎖，最新一筆通常是 auto-lock，
    用這個取回真正的開門那筆（誰/方式/時間）。
    """
    return next((e for e in events if e.is_unlock), None)


def format_lock_message(
    is_unlock: bool | None,
    who: str | None,
    method: str | None,
    msg: str = "",
    submsg: str = "",
) -> str:
    """Logbook / 通知用的一句話。

    優先沿用 API 原本的 msgText（＝app 顯示的句子，最忠實）；若為空才用
    誰＋動作＋方式自組，確保永遠有可讀內容。
    """
    text = f"{msg or ''} {submsg or ''}".strip()
    if text:
        return text
    actor = who or "Someone"
    action = "unlocked" if is_unlock else "locked"
    out = f"{actor} {action} the door"
    if method:
        out += f" ({method})"
    return out
