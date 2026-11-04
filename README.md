# Zigbang / Samsung Smart Doorlock — Home Assistant

[繁體中文](#繁體中文) · [English](#english)

## 繁體中文

這款門鎖在香港很受歡迎，很多人因為這款門鎖而入坑智能家居。不過不幸地這款產品沒有太多社區資源，即使 SmartThings 和 Google Home 的整合也不全面。萬幸這款產品支援 Wi-Fi 連線，也支援雲端開鎖，透過逆向工程可以令產品在 Home Assistant 中整合。

> **已測試型號：** SHP-DP609（香港帳號）。其他支援 Wi-Fi 連線的型號可能也適用，歡迎在 issue 回報結果。
>
> ⚠️ 非官方項目，與 Samsung SDS／Zigbang 無關；依賴門鎖的雲端服務，服務一改就可能失效。

### 功能

| 實體 | 說明 |
|------|------|
| `binary_sensor.*_lock_state` | 鎖狀態（on＝開鎖，device_class `lock`） |
| `binary_sensor.*_wi_fi` | 門鎖 Wi-Fi 連線 |
| `sensor.*_battery` | 電量 % |
| `sensor.*_last_event` | 最近一筆事件，attributes 帶 `who`／`method`／`time_utc` |
| `sensor.*_last_opened` | 最近一次**開鎖**的時間（timestamp），不會被自動上鎖蓋掉；attributes 帶 `who`／`method`／`message` |
| `button.*_unlock` | 遠端開鎖（按一下開門，約 9 秒後自動上鎖） |

> 🔐 請自行評估自動化程式與開鎖控制結合的風險。

每筆新的進出紀錄會：
- 寫進 Home Assistant 的 **Logbook**（掛在門鎖裝置下，可逐筆看「誰幾點用什麼方式開門」）；
- 發出 event bus 事件 `zigbanglock_event`（含 `who`、`method`、`is_unlock`、`time` 等），可用來做通知。

### 安裝

**經 HACS（建議）**
1. HACS → 搜尋 **Zigbang / Samsung Smart Doorlock** → 下載。
   （若搜尋不到：HACS 右上 ⋮ → Custom repositories，加入
   `https://github.com/Huiyuen07/Zigbang-Samsung_Lock`，類別選 **Integration**。）
2. 重啟 Home Assistant。
3. 設定 → 裝置與服務 → 新增整合 → **Zigbang**，填入門鎖 App 的**帳號（登入 ID）與密碼**、名稱和訊息語言。送出時會實際登入並自動找出你的門鎖。

**手動**：把 `custom_components/zigbanglock/` 複製到 HA 的 `/config/custom_components/`，然後重啟。

### 使用說明
- **一個帳號多把鎖**：新增時會讓你揀一把；其餘的再新增一次整合即可，已加入的鎖不會再出現。
- **自動重新登入**：token 失效會自動重登，通常不會察覺。只有改了密碼（或帳號被登出）時，HA 才會提示重新驗證，再輸入一次密碼即可。
- **不會擠走手機 App**：整合使用自己的裝置識別碼，手機上的 App 照常登入。
- **訊息語言**：進出紀錄的文字由雲端按語言回傳，可在整合的「設定選項」隨時切換（`zh_TW` 繁中／`zh_CN` 簡中／`en_US`／`ko_KR`）。中文只分 `zh_TW`＝繁體，其餘＝簡體。
- **Logbook 去重**：`sensor.*_last_event` 的文字與事件條目相同，Logbook 會出現兩條一樣的紀錄。想去重可在 `configuration.yaml` 加（只影響 Logbook，歷史和自動化不變）：

  ```yaml
  logbook:
    exclude:
      entities:
        - sensor.front_door_last_event
  ```
- **回報問題**：在整合頁面 ⋮ → 下載診斷資料，附在 issue。帳號、密碼、token、裝置 ID 和人名都已遮蔽。

### 怎麼運作
- 門鎖沒有推送給第三方，只能輪詢雲端。狀態每 8 秒查一次；一偵測到開↔關變化，就多查兩次進出紀錄找出「誰」，**實測外部開門約 5–7 秒**反映。門只開約 9 秒，偶爾會落在兩次輪詢之間，屆時由定期的紀錄查詢補上。
- 進出紀錄體積較大，所以平時每 30 分鐘才查一次；門被撐開也不會不停重查。
- 紀錄時間以 UTC 解析，HA 會按你的時區顯示。

### 通知範例（有人開門就推播）
```yaml
automation:
  - alias: 門鎖有人開門就通知
    trigger:
      - platform: event
        event_type: zigbanglock_event
    condition:
      - "{{ trigger.event.data.is_unlock }}"
    action:
      - service: notify.notify
        data:
          message: >
            {{ trigger.event.data.who or '有人' }} 開了門
            （{{ trigger.event.data.method }}）
```

### 開發
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
./deploy.sh <你的-HA-ssh-host>   # 經 ssh 以 tar 傳送到 /config/custom_components/，之後要重啟 HA
```

### 授權
MIT

---

## English

This doorlock is very popular in Hong Kong, and many people got into smart homes because of it. Unfortunately, it has few community resources, and even its SmartThings and Google Home integrations are incomplete. Fortunately, it supports Wi-Fi and cloud unlocking, and reverse engineering makes it possible to integrate it into Home Assistant.

> **Tested model:** SHP-DP609 (Hong Kong account). Other Wi-Fi models may also work; please report your results in an issue.
>
> ⚠️ Unofficial project, not affiliated with Samsung SDS or Zigbang. It relies on the doorlock's cloud service and may break if that service changes.

### Features

| Entity | Meaning |
|--------|---------|
| `binary_sensor.*_lock_state` | Lock state (on = unlocked, device_class `lock`) |
| `binary_sensor.*_wi_fi` | Doorlock Wi-Fi connectivity |
| `sensor.*_battery` | Battery % |
| `sensor.*_last_event` | Latest entry, with `who` / `method` / `time_utc` attributes |
| `sensor.*_last_opened` | Time of the most recent **unlock** (timestamp), not overwritten by auto-lock; `who` / `method` / `message` attributes |
| `button.*_unlock` | Remote unlock (auto-relocks after about 9 s) |

> 🔐 Assess for yourself the risk of combining automations with unlock control.

Each new history entry is:
- written to Home Assistant's **Logbook**, attached to the doorlock device, so you can browse who opened the door, when and how;
- fired as a bus event `zigbanglock_event` (`who`, `method`, `is_unlock`, `time`, …) for notifications.

### Install

**With HACS (recommended)**
1. HACS → search for **Zigbang / Samsung Smart Doorlock** → Download.
   (If it does not show up: HACS ⋮ menu → Custom repositories, add
   `https://github.com/Huiyuen07/Zigbang-Samsung_Lock` with category **Integration**.)
2. Restart Home Assistant.
3. Settings → Devices & services → Add integration → **Zigbang**, and enter your doorlock app **account (login ID) and password**, a name and the message language. It signs in and finds your lock on submit.

**Manual:** copy `custom_components/zigbanglock/` into HA's `/config/custom_components/` and restart.

### Usage
- **Several locks on one account:** setup asks you to pick one; add the integration again for the others. Locks already added are not offered again.
- **Automatic re-login:** an expired token is renewed automatically, so you normally never notice. Only after a password change (or if the account is signed out) does HA ask you to re-authenticate; enter the password once more.
- **Does not sign out the phone app:** the integration uses its own device identifier, so the app on your phone stays signed in.
- **Message language:** history text comes from the cloud in the selected language. Change it any time in the integration's options (`zh_TW` Traditional / `zh_CN` Simplified / `en_US` / `ko_KR`). For Chinese, only `zh_TW` gives Traditional; anything else gives Simplified.
- **Logbook de-duplication:** `sensor.*_last_event` carries the same text as the event entries, so the Logbook shows each one twice. To de-duplicate, add this to `configuration.yaml` (affects the Logbook only; history and automations are unchanged):

  ```yaml
  logbook:
    exclude:
      entities:
        - sensor.front_door_last_event
  ```
- **Reporting problems:** on the integration page, ⋮ → Download diagnostics, and attach the file to an issue. Account, password, tokens, device IDs and people's names are redacted.

### How it works
- The lock does not push to third parties, so the integration polls the cloud. Status is checked every 8 s; when it flips between locked and unlocked, history is fetched twice more to find *who*. External opens show up in **about 5–7 s (measured)**. The door is only unlocked for about 9 s, so an open can occasionally fall between polls; the periodic history fetch then catches up.
- History is large, so it is otherwise fetched only every 30 minutes, and a door held open does not cause repeated fetches.
- History times are parsed as UTC; HA shows them in your time zone.

### Notification example (someone opened the door)
```yaml
automation:
  - alias: Notify when the door is unlocked
    trigger:
      - platform: event
        event_type: zigbanglock_event
    condition:
      - "{{ trigger.event.data.is_unlock }}"
    action:
      - service: notify.notify
        data:
          message: >
            {{ trigger.event.data.who or 'Someone' }} unlocked the door
            ({{ trigger.event.data.method }})
```

### Development
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
./deploy.sh <your-HA-ssh-host>   # streams a tarball over ssh into /config/custom_components/; restart HA afterwards
```

### Licence
MIT
