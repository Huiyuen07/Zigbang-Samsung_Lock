#!/usr/bin/env bash
# 部署 custom_components/zigbanglock 到 Home Assistant（HAOS）。
# Deploy the custom component to Home Assistant (HAOS).
#
# 用法 / usage:  ./deploy.sh <ssh-host>
# <ssh-host> = 你 Home Assistant 的 SSH 連線名（見自己的 ~/.ssh/config）。
# <ssh-host> = the SSH host/alias of your Home Assistant (from your ~/.ssh/config).
#
# HAOS 的 SSH add-on 沒有 rsync，故用 tar 經 ssh 傳送，並先清空目標目錄，
# 令已刪除的檔案不會殘留。
# The HAOS SSH add-on has no rsync, so stream a tarball over ssh and clear the
# target first so deleted files do not linger.
set -euo pipefail

HOST="${1:?Usage: ./deploy.sh <ssh-host-of-home-assistant>}"
SRC="$(cd "$(dirname "$0")" && pwd)/custom_components/zigbanglock"
DEST="/config/custom_components/zigbanglock"

echo ">> 部署到 ${HOST}:${DEST}"
tar -C "$SRC" --exclude='__pycache__' --exclude='*.pyc' -czf - . \
  | ssh "$HOST" "rm -rf '${DEST}' && mkdir -p '${DEST}' && tar -C '${DEST}' -xzf -"

echo ">> 完成。必須整機重啟 HA 才會載入新程式碼（重新載入整合不會重新 import 模組）。"
echo ">> Done. A full HA restart is required to load new code"
echo "   (reloading the integration does not re-import Python modules)."
