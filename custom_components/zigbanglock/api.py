"""Async HTTP client for the Zigbang / Samsung doorlock cloud."""
from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

import aiohttp

from .const import (
    API_VER,
    APP_VER,
    DEFAULT_LOCALE,
    LOCALE_COUNTRY,
    OS_TYPE,
    OS_VER,
    PATH_DOORLOCK_LIST,
    PATH_HISTORY,
    PATH_LOGIN,
    PATH_OPEN,
    PATH_STATUS,
    USER_AGENT,
)
from .parsing import (
    LockEvent,
    LockStatus,
    ZigbangApiError,
    parse_history,
    parse_status,
)

_LOGGER = logging.getLogger(__name__)

# history 全量 ~374KB，給足時間；status/open/login 通常一秒內返回。
_TIMEOUT = 25


class ZigbangAuthError(ZigbangApiError):
    """Token/帳密失效。有帳密時會自動重登；否則觸發 reauth。"""


def _sha512(text: str) -> str:
    return hashlib.sha512(text.encode()).hexdigest()


def login_hash(body: dict[str, Any]) -> str:
    """Compute the login request's `hashData` field, in the same format as the app."""
    parts: list[str] = []
    for key in sorted(body):
        if key == "hashData":
            continue
        value = body[key]
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif isinstance(value, int):
            rendered = str(value)
        elif isinstance(value, str):
            rendered = value.strip()
        else:  # dict/list/None：略過（非純量）
            continue
        if rendered:
            parts.append(rendered)
    return _sha512("".join(parts))


class ZigbangLockClient:
    """讀狀態、讀進出紀錄、遠端開鎖；以帳密登入並在 token 失效時自動重登。"""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        member_id: str = "",
        device_id: str = "",
        auth_token: str = "",
        auth_code: str = "",
        locale: str = DEFAULT_LOCALE,
        *,
        login_id: str | None = None,
        password: str | None = None,
        device_uid: str | None = None,
    ) -> None:
        self._session = session
        self._base = base_url.rstrip("/")
        self._member = member_id
        self._device = device_id
        self._token = auth_token
        self._authcode = auth_code
        self._locale = locale
        self._login_id = login_id
        self._password = password
        self._device_uid = device_uid
        self._login_lock = asyncio.Lock()

    # ---- 身分 / 設定存取 ---------------------------------------------------

    @property
    def member_id(self) -> str:
        return self._member

    @property
    def auth_token(self) -> str:
        return self._token

    @property
    def auth_code(self) -> str:
        return self._authcode

    def set_locale(self, locale: str) -> None:
        self._locale = locale

    def can_login(self) -> bool:
        return bool(self._login_id and self._password and self._device_uid)

    # ---- 低階請求 ---------------------------------------------------------

    def _headers(self, *, login: bool = False) -> dict[str, str]:
        # 登入時還沒有 token，app 送的 authorization 就是字面 "CUL"。
        return {
            "authorization": "CUL" if login else f"CUL {self._token}",
            "authcode": "" if login else self._authcode,
            "contents-type": "application/json",
            "acceptlanguage": self._locale,
            "accept": "*/*",
            "user-agent": USER_AGENT,
        }

    @staticmethod
    def _now() -> str:
        # API 的 createDate 格式（UTC）
        return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

    @staticmethod
    def _timezone_hours() -> int:
        offset = datetime.now().astimezone().utcoffset()
        return int(offset.total_seconds() // 3600) if offset else 0

    def _params(self, **extra: str) -> dict[str, str]:
        return {
            "createDate": self._now(),
            "memberId": self._member,
            "hashData": "",
            **extra,
        }

    async def _request_once(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        login: bool = False,
    ) -> dict[str, Any]:
        """送出單次請求並回傳 JSON；所有傳輸層錯誤都包成 ZigbangApiError。"""
        url = f"{self._base}{path}"
        try:
            async with asyncio.timeout(_TIMEOUT):
                async with self._session.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    headers=self._headers(login=login),
                ) as resp:
                    if resp.status in (401, 403):
                        raise ZigbangAuthError(f"HTTP {resp.status}")
                    resp.raise_for_status()
                    data = await resp.json(content_type=None)
        except TimeoutError as err:
            raise ZigbangApiError(f"timeout after {_TIMEOUT}s") from err
        except aiohttp.ClientError as err:
            raise ZigbangApiError(str(err)) from err
        except ValueError as err:  # 非 JSON（例如 HTML 錯誤頁）
            raise ZigbangApiError(f"invalid JSON response: {err}") from err

        if not isinstance(data, dict):
            raise ZigbangApiError(f"unexpected response type: {type(data).__name__}")
        # 伺服器對失效 token 常回 200 + result:false，需看 code 判斷；
        # 成功碼為 S001，E4xx 類視為認證/授權失效。
        code = str(data.get("code", "")).upper()
        if not data.get("result") and code.startswith("E4"):
            raise ZigbangAuthError(data.get("errorMessage") or code)
        return data

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """一般請求：遇到認證失效且備有帳密時，自動重登一次再重試。"""
        try:
            return await self._request_once(method, path, params=params, json=json)
        except ZigbangAuthError:
            if not self.can_login():
                raise
            await self.async_login()
            # memberId 登入後可能更新，重建帶 memberId 的 params
            if params is not None and "memberId" in params:
                params = {**params, "memberId": self._member}
            return await self._request_once(method, path, params=params, json=json)

    # ---- 登入 -------------------------------------------------------------

    def _login_body(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "apiVer": API_VER,
            "loginId": self._login_id or "",
            "appVer": APP_VER,
            "timeZone": self._timezone_hours(),
            "countryCd": LOCALE_COUNTRY.get(self._locale, "US"),
            "locale": self._locale,
            "osVer": OS_VER,
            "pushToken": "",
            "imei": self._device_uid or "",
            "pwd": _sha512(self._password or ""),
            "overwrite": True,
            "osTypeCd": OS_TYPE,
            "mobileNum": "",
            "locationAgreeYn": "N",
            "authNumber": "",
            "authCode": "",
            "createDate": self._now(),
        }
        body["hashData"] = login_hash(body)
        return body

    async def async_login(self) -> None:
        """用帳密登入，更新 memberId / authToken / authCode。"""
        if not self.can_login():
            raise ZigbangAuthError("no stored credentials to log in with")
        async with self._login_lock:
            data = await self._request_once(
                "PUT", PATH_LOGIN, json=self._login_body(), login=True
            )
            if not data.get("result"):
                code = str(data.get("code", "")).upper()
                raise ZigbangAuthError(
                    data.get("errorMessage") or data.get("message") or code or "login failed"
                )
            self._token = data.get("authToken") or ""
            if data.get("authCode"):
                self._authcode = str(data["authCode"])
            if data.get("memberId"):
                self._member = str(data["memberId"])
            _LOGGER.debug("Logged in; memberId=%s", self._member)

    async def async_get_doorlocks(self) -> list[dict[str, str]]:
        """回傳帳號下的門鎖清單：[{device_id, name}, ...]（供設定時自動帶出）。"""
        # favoriteYn="A"（全部）＝ app 首頁的用法；"N" 會濾到空清單。
        data = await self._request(
            "GET",
            PATH_DOORLOCK_LIST,
            params=self._params(favoriteYn="A", locale=self._locale),
        )
        locks: list[dict[str, str]] = []
        for vo in data.get("doorlockVOList") or []:
            if not isinstance(vo, dict):
                continue
            device_id = vo.get("deviceId")
            if device_id:
                locks.append(
                    {"device_id": str(device_id), "name": str(vo.get("deviceNm") or "")}
                )
        return locks

    # ---- 讀取 / 控制 -------------------------------------------------------

    async def async_get_status(self) -> LockStatus:
        data = await self._request(
            "GET", PATH_STATUS, params=self._params(deviceId=self._device)
        )
        return parse_status(data)

    async def async_get_history(self) -> list[LockEvent]:
        data = await self._request(
            "GET",
            PATH_HISTORY,
            params=self._params(deviceId=self._device, locale=self._locale),
        )
        return parse_history(data)

    async def async_open(self) -> None:
        """遠端開鎖（門約 9 秒後自動上鎖）。"""
        body = {
            "open": True,
            "isSecurityMode": False,
            "createDate": self._now(),
            "securityModeRptEndDt": "",
            "hashData": "",
            "deviceId": self._device,
            "memberId": self._member,
            "securityModeRptStartDt": "",
        }
        data = await self._request("PUT", PATH_OPEN, json=body)
        if not data.get("result"):
            raise ZigbangApiError(
                data.get("errorMessage") or data.get("code") or "open failed"
            )
