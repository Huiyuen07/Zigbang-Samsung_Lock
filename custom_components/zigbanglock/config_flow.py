"""Config flow (UI setup via login, lock selection, reauth, language options)."""
from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ZigbangAuthError, ZigbangLockClient
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
    DEFAULT_BASE_URL,
    DEFAULT_LOCALE,
    DEFAULT_NAME,
    DOMAIN,
    LOCALES,
)
from .parsing import ZigbangApiError

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
        vol.Required(CONF_LOGIN_ID): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_LOCALE, default=DEFAULT_LOCALE): vol.In(LOCALES),
        vol.Optional(CONF_BASE_URL, default=DEFAULT_BASE_URL): str,
    }
)


def _new_device_uid() -> str:
    """等同手機的 android_id：每個 entry 一個固定的裝置槽，不會擠走手機 app。"""
    return uuid.uuid4().hex[:16]


class ZigbangConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._user_input: dict[str, Any] = {}
        self._client: ZigbangLockClient | None = None
        self._device_uid = ""
        self._locks: dict[str, str] = {}  # device_id → 門鎖名稱（尚未設定的）

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return ZigbangOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """帳密登入：自行登入、自動帶出門鎖。"""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._device_uid = _new_device_uid()
            client = ZigbangLockClient(
                session=async_get_clientsession(self.hass),
                base_url=user_input.get(CONF_BASE_URL, DEFAULT_BASE_URL),
                locale=user_input.get(CONF_LOCALE, DEFAULT_LOCALE),
                login_id=user_input[CONF_LOGIN_ID],
                password=user_input[CONF_PASSWORD],
                device_uid=self._device_uid,
            )
            error, locks = await self._async_login_and_list(client)
            if error is None and not locks:
                error = "no_locks"
            if error is None:
                configured = self._async_current_ids(include_ignore=False)
                available = {
                    lock["device_id"]: lock["name"]
                    for lock in locks
                    if lock["device_id"] not in configured
                }
                if not available:
                    return self.async_abort(reason="already_configured")
                self._user_input = user_input
                self._client = client
                self._locks = available
                if len(available) == 1:
                    return await self._async_create_lock_entry(
                        next(iter(available)), multiple=len(locks) > 1
                    )
                return await self.async_step_pick_lock()
            errors["base"] = error
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA, user_input
            ),
            errors=errors,
        )

    async def async_step_pick_lock(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """帳號下有多於一把未設定的門鎖：讓用戶揀一把（其餘可再新增一次）。"""
        if user_input is not None:
            return await self._async_create_lock_entry(
                user_input[CONF_DEVICE_ID], multiple=True
            )
        options = {
            device_id: name or device_id for device_id, name in self._locks.items()
        }
        return self.async_show_form(
            step_id="pick_lock",
            data_schema=vol.Schema({vol.Required(CONF_DEVICE_ID): vol.In(options)}),
        )

    async def _async_create_lock_entry(
        self, device_id: str, *, multiple: bool
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(device_id)
        self._abort_if_unique_id_configured()
        assert self._client is not None
        user_input = self._user_input
        # 一帳號多把鎖時，用 app 內的門鎖名稱區分各 entry
        name = (self._locks.get(device_id) if multiple else None) or user_input[
            CONF_NAME
        ]
        locale = user_input.get(CONF_LOCALE, DEFAULT_LOCALE)
        return self.async_create_entry(
            title=name,
            data={
                CONF_NAME: name,
                CONF_LOGIN_ID: user_input[CONF_LOGIN_ID],
                CONF_PASSWORD: user_input[CONF_PASSWORD],
                CONF_DEVICE_UID: self._device_uid,
                CONF_DEVICE_ID: device_id,
                CONF_MEMBER_ID: self._client.member_id,
                CONF_AUTH_TOKEN: self._client.auth_token,
                CONF_AUTH_CODE: self._client.auth_code,
                CONF_BASE_URL: user_input.get(CONF_BASE_URL, DEFAULT_BASE_URL),
                CONF_LOCALE: locale,
            },
            options={CONF_LOCALE: locale},
        )

    async def _async_login_and_list(
        self, client: ZigbangLockClient
    ) -> tuple[str | None, list[dict[str, str]]]:
        """登入並取回門鎖清單；回傳 (錯誤鍵 or None, 門鎖清單)。"""
        try:
            await client.async_login()
            return None, await client.async_get_doorlocks()
        except ZigbangAuthError:
            return "invalid_auth", []
        except ZigbangApiError:
            return "cannot_connect", []
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected error during doorlock login")
            return "unknown", []

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """重新輸入密碼即可；舊版沒有帳號的 entry 會一併要求帳號。"""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        stored_login = entry.data.get(CONF_LOGIN_ID)
        if user_input is not None:
            login_id = stored_login or user_input[CONF_LOGIN_ID]
            device_uid = entry.data.get(CONF_DEVICE_UID) or _new_device_uid()
            client = ZigbangLockClient(
                session=async_get_clientsession(self.hass),
                base_url=entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL),
                locale=entry.data.get(CONF_LOCALE, DEFAULT_LOCALE),
                login_id=login_id,
                password=user_input[CONF_PASSWORD],
                device_uid=device_uid,
            )
            error, locks = await self._async_login_and_list(client)
            if error is None and entry.data.get(CONF_DEVICE_ID) not in {
                lock["device_id"] for lock in locks
            }:
                # 登入的帳號看不到這把鎖（例如填錯帳號）
                error = "wrong_account"
            if error is None:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_LOGIN_ID: login_id,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_DEVICE_UID: device_uid,
                        CONF_MEMBER_ID: client.member_id,
                        CONF_AUTH_TOKEN: client.auth_token,
                        CONF_AUTH_CODE: client.auth_code,
                    },
                )
            errors["base"] = error
        schema: dict[Any, Any] = {}
        if not stored_login:
            schema[vol.Required(CONF_LOGIN_ID)] = str
        schema[vol.Required(CONF_PASSWORD)] = str
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(schema),
            description_placeholders={"name": entry.title},
            errors=errors,
        )


class ZigbangOptionsFlow(OptionsFlow):
    """只放可隨時變更、不需重新登入的設定——目前是顯示語言。"""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options.get(
            CONF_LOCALE, self.config_entry.data.get(CONF_LOCALE, DEFAULT_LOCALE)
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {vol.Optional(CONF_LOCALE, default=current): vol.In(LOCALES)}
            ),
        )
