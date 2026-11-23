"""Unlock button.

門鎖只有「開鎖」指令（約 9 秒後自動上鎖），沒有獨立「上鎖」指令，
故以 button 而非 lock 實體呈現，語義最誠實。
"""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ZigbangConfigEntry
from .api import ZigbangAuthError
from .const import CONF_DEVICE_ID, CONF_NAME, DEFAULT_NAME
from .entity import ZigbangEntity
from .parsing import ZigbangApiError

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZigbangConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    did = entry.data[CONF_DEVICE_ID]
    name = entry.data.get(CONF_NAME, DEFAULT_NAME)
    async_add_entities([DoorlockUnlockButton(coordinator, did, name)])


class DoorlockUnlockButton(ZigbangEntity, ButtonEntity):
    _attr_icon = "mdi:lock-open-variant"

    def __init__(self, coordinator, device_id, name):
        super().__init__(coordinator, device_id, name)
        self._attr_unique_id = f"{device_id}_unlock"
        self._attr_name = "Unlock"

    async def async_press(self) -> None:
        _LOGGER.info("Unlock pressed for %s", self._device_id)
        try:
            await self.coordinator.client.async_open()
        except ZigbangAuthError as err:
            # 認證持續失效時 coordinator 會在寬限期後觸發 reauth
            raise HomeAssistantError(
                f"Unlock failed: authentication expired ({err})"
            ) from err
        except ZigbangApiError as err:
            raise HomeAssistantError(f"Unlock failed: {err}") from err

        # 立即拉 history 記下「誰開鎖」；之後的開/關鎖變化由 8 秒 status 輪詢
        # 偵測到再補拉，毋須另外排程延遲刷新。
        self.coordinator.request_history_burst()
        await self.coordinator.async_request_refresh()
