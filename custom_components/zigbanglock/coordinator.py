"""Polling coordinator: lock status + history, fires events for new entries."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import ZigbangAuthError, ZigbangLockClient
from .const import DOMAIN, EVENT_LOCK
from .parsing import (
    LockEvent,
    LockStatus,
    ZigbangApiError,
    latest_unlock,
    new_events_since,
)

_LOGGER = logging.getLogger(__name__)

# 鎖狀態一有變化（開↔關），接下來這麼多次刷新都拉 history 抓「誰」。
# 開鎖、自動上鎖兩個邊緣各 2 次 ≈ 每次開門 4 次；門被撐開時不會無限拉。
_BURST_CYCLES = 2
# history 拉取失敗後的重試間隔（不跟 status 每次刷新一齊重試 374KB）
_HISTORY_RETRY = timedelta(seconds=60)
# 有存帳密時，認證類錯誤持續超過此時長才要求用戶重新驗證；
# 寬限期內當作暫時錯誤（伺服器偶發回 E4xx「RunTimeException」），由 client 退避重登。
AUTH_GRACE = timedelta(hours=1)


@dataclass
class ZigbangData:
    status: LockStatus
    last_event: LockEvent | None = None
    last_unlock: LockEvent | None = None  # 最近一筆「開鎖」，不被自動上鎖蓋掉


class ZigbangCoordinator(DataUpdateCoordinator[ZigbangData]):
    """每次刷新讀狀態；鎖狀態變化或到期時讀進出紀錄，並為新紀錄派發事件。"""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: ZigbangLockClient,
        *,
        device_id: str,
        name: str,
        status_interval: timedelta,
        history_interval: timedelta,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{name}",
            update_interval=status_interval,
        )
        self.client = client
        self.device_id = device_id  # 雲端 deviceId，同時是 HA device identifier
        self.device_name = name  # 拿到 history 後改用 app 內的裝置名
        self._history_interval = history_interval
        self._seen_ids: set[str] | None = None  # None = 尚未建立 baseline
        self._next_history_at: datetime | None = None
        self._history_burst = 0
        self._history_failing = False
        self._last_locked: bool | None = None
        self._ha_device_id: str | None = None
        self._auth_failing_since: datetime | None = None

    def request_history_burst(self) -> None:
        """接下來幾次刷新都拉 history（開鎖鍵或偵測到鎖狀態變化時用）。"""
        self._history_burst = max(self._history_burst, _BURST_CYCLES)

    async def _async_update_data(self) -> ZigbangData:
        # 狀態係關鍵：失敗先至令實體 unavailable；認證持續失效才觸發 reauth
        try:
            status = await self.client.async_get_status()
        except ZigbangAuthError as err:
            raise self._auth_failure(err) from err
        except ZigbangApiError as err:
            raise UpdateFailed(str(err)) from err
        if self._auth_failing_since is not None:
            self._auth_failing_since = None
            _LOGGER.info("Authentication recovered")

        # 邊緣觸發：只在開↔關變化時加拉 history（level 觸發會在門被撐開時狂拉）
        prev, self._last_locked = self._last_locked, status.locked
        if prev is not None and status.locked is not None and status.locked != prev:
            self.request_history_burst()

        data = ZigbangData(status=status)
        if self.data is not None:
            data.last_event = self.data.last_event
            data.last_unlock = self.data.last_unlock

        now = dt_util.utcnow()
        due = self._next_history_at is None or now >= self._next_history_at
        if self._history_burst > 0 or due:
            if self._history_burst > 0:
                self._history_burst -= 1
            await self._try_poll_history(data, now)
        return data

    def _auth_failure(self, err: ZigbangAuthError) -> Exception:
        """認證錯誤 → 寬限期內當暫時錯誤（UpdateFailed），超過才 reauth。"""
        if not self.client.can_login():
            return ConfigEntryAuthFailed(str(err))
        now = dt_util.utcnow()
        if self._auth_failing_since is None:
            self._auth_failing_since = now
            _LOGGER.warning(
                "Authentication error from cloud, will keep re-logging in "
                "automatically for up to %s before asking to re-authenticate: %s",
                AUTH_GRACE,
                err,
            )
        if now - self._auth_failing_since >= AUTH_GRACE:
            return ConfigEntryAuthFailed(str(err))
        return UpdateFailed(f"authentication error, retrying: {err}")

    async def _try_poll_history(self, data: ZigbangData, now: datetime) -> None:
        """history 係 best-effort：失敗唔可以連坐 status 令全部實體 unavailable。"""
        try:
            await self._poll_history(data)
        except Exception as err:  # noqa: BLE001
            self._next_history_at = now + _HISTORY_RETRY
            if not self._history_failing:
                self._history_failing = True
                # 非 API 錯誤（多半是解析 bug）附上 traceback 方便排查
                _LOGGER.warning(
                    "History fetch failed (status still OK, retrying): %s",
                    err,
                    exc_info=not isinstance(err, ZigbangApiError),
                )
            else:
                _LOGGER.debug("History fetch still failing: %s", err)
            return

        self._next_history_at = now + self._history_interval
        if self._history_failing:
            self._history_failing = False
            _LOGGER.info("History fetch recovered")

    async def _poll_history(self, data: ZigbangData) -> None:
        events = await self.client.async_get_history()
        if not events:
            return
        if events[0].device_name:
            self.device_name = events[0].device_name

        data.last_event = events[0]
        if (unlock := latest_unlock(events)) is not None:
            data.last_unlock = unlock

        # 首次只建 baseline 不派發（免得重啟時洗出 1000+ 筆）
        if self._seen_ids is not None:
            for ev in new_events_since(events, self._seen_ids):
                self._fire_event(ev)
        # 伺服器每次都回全量清單，記住目前這份即可（不會無限增長）
        self._seen_ids = {e.event_id for e in events if e.event_id}

    def _ha_device(self) -> str | None:
        """HA device registry id；事件帶上它，Logbook 才會顯示在門鎖裝置頁。"""
        if self._ha_device_id is None:
            device = dr.async_get(self.hass).async_get_device(
                identifiers={(DOMAIN, self.device_id)}
            )
            self._ha_device_id = device.id if device else None
        return self._ha_device_id

    def _fire_event(self, ev: LockEvent) -> None:
        # 刻意不帶 entity_id：Logbook 的實體 exclude 會比對事件裡的 entity_id，
        # 帶了就會跟被排除的實體一齊被藏起來。
        self.hass.bus.async_fire(
            EVENT_LOCK,
            {
                "device_id": self._ha_device(),
                "lock_id": self.device_id,
                "device_name": ev.device_name,
                "event_id": ev.event_id,
                "message": ev.msg,
                "sub_message": ev.submsg,
                "method": ev.method,
                "pin_type": ev.pin_type,
                "pin_name": ev.pin_name,
                "member_name": ev.member_name,
                "who": ev.who,
                "is_unlock": ev.is_unlock,
                "is_lock": ev.is_lock,
                "time": ev.ts.isoformat() if ev.ts else None,
            },
        )
        _LOGGER.debug("Fired %s: %s (%s)", EVENT_LOCK, ev.msg, ev.who)
