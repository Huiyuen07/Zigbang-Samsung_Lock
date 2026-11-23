"""Tests for the API client's request shapes and error mapping (fake session)."""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import pytest

# 以套件情境載入 const/parsing/api，但不執行 __init__.py（它需要 homeassistant）
PKGDIR = Path(__file__).resolve().parent.parent / "custom_components" / "zigbanglock"
_pkg = types.ModuleType("zb")
_pkg.__path__ = [str(PKGDIR)]
sys.modules["zb"] = _pkg
for _mod in ("const", "parsing", "api"):
    _spec = importlib.util.spec_from_file_location(f"zb.{_mod}", PKGDIR / f"{_mod}.py")
    _m = importlib.util.module_from_spec(_spec)
    sys.modules[f"zb.{_mod}"] = _m
    _spec.loader.exec_module(_m)

api = sys.modules["zb.api"]
ZigbangApiError = api.ZigbangApiError
ZigbangAuthError = api.ZigbangAuthError
ZigbangLockClient = api.ZigbangLockClient


def _run(coro):
    """跑 coroutine 但不動全域 event loop（asyncio.run 會清走，影響 HA 測試套件）。"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

STATUS_OK = {
    "result": True,
    "code": "S001",
    "doorlockStatusVO": {"locked": True, "battery": 52, "wifiConnected": True},
}


class _FakeResp:
    """模仿 aiohttp：session.request() 回傳 async context manager。"""

    def __init__(self, status=200, payload=None, exc=None):
        self.status = status
        self._payload = payload if payload is not None else {"result": True, "code": "S001"}
        self._exc = exc
        self.released = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        self.released = True
        return False

    def raise_for_status(self):
        pass

    async def json(self, content_type=None):
        if self._exc is not None:
            raise self._exc
        return self._payload


class _FakeSession:
    def __init__(self, resp):
        self._resp = resp
        self.calls = []

    def request(self, method, url, params=None, json=None, headers=None):
        self.calls.append(
            {"method": method, "url": url, "params": params, "json": json, "headers": headers}
        )
        return self._resp


class _HangingSession(_FakeSession):
    def request(self, *args, **kwargs):
        outer = self

        class _Hang:
            async def __aenter__(self):
                await asyncio.sleep(3600)

            async def __aexit__(self, *exc_info):
                return False

        outer.calls.append(args)
        return _Hang()


def _client(session):
    return ZigbangLockClient(session, "https://host:8088", "mem", "dev", "tok", "ac")


def test_open_request_shape():
    sess = _FakeSession(_FakeResp())
    _run(_client(sess).async_open())
    call = sess.calls[-1]
    assert call["method"] == "PUT"
    assert call["url"].endswith("/openhome/v20/doorlockctrl/open")
    assert call["json"]["open"] is True
    assert call["json"]["deviceId"] == "dev"
    assert call["json"]["memberId"] == "mem"
    assert call["headers"]["authorization"] == "CUL tok"
    assert call["headers"]["authcode"] == "ac"


def test_status_request_shape_and_parse():
    resp = _FakeResp(payload=STATUS_OK)
    sess = _FakeSession(resp)
    st = _run(_client(sess).async_get_status())
    call = sess.calls[-1]
    assert call["method"] == "GET"
    assert call["url"].endswith("/openhome/v20/doorlockctrl/doorlockstatus")
    assert call["params"]["deviceId"] == "dev"
    assert call["params"]["memberId"] == "mem"
    assert st.locked is True and st.battery == 52
    assert resp.released  # 連線有歸還（async with）


def test_auth_error_code_in_body():
    sess = _FakeSession(_FakeResp(payload={"result": False, "code": "E401"}))
    with pytest.raises(ZigbangAuthError):
        _run(_client(sess).async_open())


def test_auth_error_http_401_releases_connection():
    resp = _FakeResp(status=401)
    with pytest.raises(ZigbangAuthError):
        _run(_client(_FakeSession(resp)).async_get_status())
    assert resp.released


def test_open_generic_failure():
    sess = _FakeSession(_FakeResp(payload={"result": False, "code": "B0502"}))
    with pytest.raises(ZigbangApiError) as exc:
        _run(_client(sess).async_open())
    assert not isinstance(exc.value, ZigbangAuthError)


def test_non_json_response_is_api_error():
    sess = _FakeSession(_FakeResp(exc=ValueError("Expecting value")))
    with pytest.raises(ZigbangApiError):
        _run(_client(sess).async_get_status())


def test_timeout_is_api_error(monkeypatch):
    monkeypatch.setattr(api, "_TIMEOUT", 0.05)
    with pytest.raises(ZigbangApiError, match="timeout"):
        _run(_client(_HangingSession(None)).async_get_status())


# --- 自動登入 ----------------------------------------------------------

import hashlib  # noqa: E402

login_hash = api.login_hash

LOGIN_OK = {
    "result": True,
    "code": "S001",
    "authToken": "newtok",
    "authCode": "newac",
    "memberId": "mem-123",
}


class _SeqSession:
    """每次 request() 依序回下一個 _FakeResp，並記錄呼叫。"""

    def __init__(self, *resps):
        self._resps = list(resps)
        self.calls = []

    def request(self, method, url, params=None, json=None, headers=None):
        self.calls.append(
            {"method": method, "url": url, "params": params, "json": json, "headers": headers}
        )
        return self._resps.pop(0)


def _cred_client(session):
    return ZigbangLockClient(
        session,
        "https://host:8088",
        login_id="u@x.com",
        password="secret",
        device_uid="abcd1234",
        locale="zh_TW",
    )


def test_login_hash_known_vector():
    body = {"a": "1", "b": "2", "c": "", "d": True, "e": 3, "hashData": "ignored"}
    expected = hashlib.sha512("12true3".encode()).hexdigest()
    assert login_hash(body) == expected


def test_login_builds_body_and_updates_tokens():
    sess = _SeqSession(_FakeResp(payload=LOGIN_OK))
    client = _cred_client(sess)
    _run(client.async_login())
    call = sess.calls[-1]
    assert call["method"] == "PUT"
    assert call["url"].endswith("/openhome/v10/user/login")
    body = call["json"]
    assert body["pwd"] == hashlib.sha512(b"secret").hexdigest()
    assert body["loginId"] == "u@x.com"
    assert body["imei"] == "abcd1234"
    assert body["overwrite"] is True
    assert body["hashData"] == login_hash(body)
    assert call["headers"]["authorization"] == "CUL"
    # 回應更新了身分
    assert client.auth_token == "newtok"
    assert client.auth_code == "newac"
    assert client.member_id == "mem-123"


def test_login_rejected_raises_auth_error():
    sess = _SeqSession(_FakeResp(payload={"result": False, "code": "E401"}))
    with pytest.raises(ZigbangAuthError):
        _run(_cred_client(sess).async_login())


def test_auto_relogin_on_auth_error_then_retry():
    # 首次 status → E401；自動登入成功；重試 status → OK
    sess = _SeqSession(
        _FakeResp(payload={"result": False, "code": "E401"}),
        _FakeResp(payload=LOGIN_OK),
        _FakeResp(payload=STATUS_OK),
    )
    st = _run(_cred_client(sess).async_get_status())
    assert st.locked is True
    assert len(sess.calls) == 3
    assert sess.calls[1]["url"].endswith("/user/login")
    # 重試的 status 帶上登入後取得的 memberId
    assert sess.calls[2]["params"]["memberId"] == "mem-123"


def test_no_credentials_does_not_retry():
    # 無帳密的舊式 client：401 直接拋出，不嘗試登入
    sess = _SeqSession(_FakeResp(status=401))
    with pytest.raises(ZigbangAuthError):
        _run(_client(sess).async_get_status())
    assert len(sess.calls) == 1


def test_get_doorlocks_parses_list():
    payload = {
        "result": True,
        "code": "S001",
        "doorlockVOList": [
            {"deviceId": "DEV1", "deviceNm": "Front"},
            {"deviceId": "DEV2", "deviceNm": "Back"},
            {"deviceNm": "no id, skipped"},
        ],
    }
    sess = _SeqSession(_FakeResp(payload=payload))
    client = _cred_client(sess)
    client._member = "mem-123"  # 已登入狀態
    locks = _run(client.async_get_doorlocks())
    assert sess.calls[-1]["params"]["favoriteYn"] == "A"  # "N" 會濾到空
    assert locks == [
        {"device_id": "DEV1", "name": "Front"},
        {"device_id": "DEV2", "name": "Back"},
    ]


# ---- 自動重登退避（伺服器暫時出錯時不狂登入）---------------------------

E4_FAIL = {"result": False, "code": "E402", "errorMessage": "RunTimeException failed."}


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _backoff_client(sess, clock):
    client = _cred_client(sess)
    client._clock = clock
    return client


def test_auth_error_message_includes_code():
    sess = _SeqSession(_FakeResp(payload=E4_FAIL))
    with pytest.raises(ZigbangAuthError, match=r"RunTimeException failed\. \(E402\)"):
        _run(_client(sess).async_get_status())


def test_failed_relogin_backs_off_before_next_login():
    clock = _Clock()
    # 第一輪：status E4 → login 亦 E4 → 拋出
    sess = _SeqSession(
        _FakeResp(payload=E4_FAIL),
        _FakeResp(payload=E4_FAIL),
        # 第二輪（仍在退避內）：只打 status，不再登入
        _FakeResp(payload=E4_FAIL),
        # 第三輪（退避已過）：status E4 → login OK → status OK
        _FakeResp(payload=E4_FAIL),
        _FakeResp(payload=LOGIN_OK),
        _FakeResp(payload=STATUS_OK),
    )
    client = _backoff_client(sess, clock)
    with pytest.raises(ZigbangAuthError):
        _run(client.async_get_status())
    assert len(sess.calls) == 2

    clock.t += 30
    with pytest.raises(ZigbangAuthError):
        _run(client.async_get_status())
    assert len(sess.calls) == 3
    assert not sess.calls[2]["url"].endswith("/user/login")

    clock.t += 60
    st = _run(client.async_get_status())
    assert st.locked is True
    assert sess.calls[4]["url"].endswith("/user/login")


def test_relogin_backoff_grows_and_resets_after_success():
    clock = _Clock()
    client = _backoff_client(_SeqSession(), clock)
    delays = []
    for _ in range(6):
        client._note_relogin_failure()
        delays.append(client._next_relogin_at - clock.t)
    assert delays == [60, 120, 300, 600, 600, 600]
    client._note_relogin_success()
    client._note_relogin_failure()
    assert client._next_relogin_at - clock.t == 60


def test_transient_status_error_succeeds_on_retry_without_backoff():
    # status 偶發 E4，重登成功、重試成功 → 不留退避
    clock = _Clock()
    sess = _SeqSession(
        _FakeResp(payload=E4_FAIL),
        _FakeResp(payload=LOGIN_OK),
        _FakeResp(payload=STATUS_OK),
    )
    client = _backoff_client(sess, clock)
    _run(client.async_get_status())
    assert client._next_relogin_at == 0.0
