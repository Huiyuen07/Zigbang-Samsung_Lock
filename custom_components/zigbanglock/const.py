"""Constants for the Zigbang / Samsung smart doorlock integration."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "zigbanglock"

# 設定鍵（UI 設定流程）
CONF_BASE_URL = "base_url"
CONF_MEMBER_ID = "member_id"
CONF_DEVICE_ID = "device_id"
CONF_AUTH_TOKEN = "auth_token"
CONF_AUTH_CODE = "auth_code"
CONF_NAME = "name"
CONF_LOCALE = "locale"
# 自動登入（帳號密碼）相關
CONF_LOGIN_ID = "login_id"
CONF_PASSWORD = "password"
CONF_DEVICE_UID = "device_uid"  # 等同手機的 android_id，決定帳號「裝置槽」；一經產生就固定

DEFAULT_BASE_URL = "https://iot.samsung-ihp.com:8088"
DEFAULT_NAME = "Doorlock"
DEFAULT_LOCALE = "en_US"

# 伺服器按此回不同語言的事件文字（msgText）；app 對中文只分 TW→繁體、其餘→簡體。
LOCALES = ["en_US", "zh_TW", "zh_CN", "ko_KR"]
# locale → 登入用 countryCd
LOCALE_COUNTRY = {
    "en_US": "US",
    "zh_TW": "TW",
    "zh_CN": "CN",
    "ko_KR": "KR",
}

# 登入請求的固定欄位（對應 app 26.9.2）
APP_VER = "26.9.2"
API_VER = "v20"
OS_TYPE = "ADR"
OS_VER = "13"
# status 很小（~610B），快輪詢以便一偵測到 locked=false 就觸發 history 抓「誰」。
DEFAULT_STATUS_INTERVAL = timedelta(seconds=8)
# history 很大（~374KB 全量、無分頁），開門已由 status 觸發，週期性只作 fallback。
DEFAULT_HISTORY_INTERVAL = timedelta(seconds=1800)

# App 的 User-Agent
USER_AGENT = (
    "SmartDoorLock_Global/26.7.3 "
    "(com.samsung.sds.global.doorlock.dlis; build:260703; iOS 27.0.1) Alamofire/5.0.5"
)

# API 路徑
PATH_LOGIN = "/openhome/v10/user/login"
PATH_DOORLOCK_LIST = "/openhome/v20/doorlockctrl/membersdoorlocklist"
PATH_STATUS = "/openhome/v20/doorlockctrl/doorlockstatus"
PATH_HISTORY = "/openhome/v20/doorlockctrl/inouthistory"
PATH_OPEN = "/openhome/v20/doorlockctrl/open"

# 新開鎖/上鎖事件會以此名稱打到 HA event bus；automation 可監聽做通知。
EVENT_LOCK = f"{DOMAIN}_event"

MANUFACTURER = "Samsung SDS / Zigbang"
MODEL = "Smart Doorlock"
