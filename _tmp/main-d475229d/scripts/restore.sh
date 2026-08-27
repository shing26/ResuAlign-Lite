#!/usr/bin/env sh
# ResuAlign 一键恢复（macOS / Linux 包装）。
#
# 用法：
#   ./scripts/restore.sh                 # 恢复 backups/ 下最新快照
#   ./scripts/restore.sh /path/to/data   # 指定数据目录
#   ./scripts/restore.sh /path/to/data /path/to/manifest.json
#
# 实际逻辑在 scripts/backup_restore.py。要求服务已停止（默认检查 8000
# 端口），会保留 *.pre-restore-* 现场便于回退。
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

PY=""
if command -v python >/dev/null 2>&1; then PY="python"
elif command -v python3 >/dev/null 2>&1; then PY="python3"
else
  echo "[restore] ERROR: python not found" >&2
  exit 1
fi

ARGS="$ROOT/scripts/backup_restore.py restore"
if [ "${1:-}" != "" ]; then
  ARGS="$ARGS --data-dir $1"
fi
if [ "${2:-}" != "" ]; then
  ARGS="$ARGS --manifest $2"
fi

# shellcheck disable=SC2086
"$PY" $ARGS
