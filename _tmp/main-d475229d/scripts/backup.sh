#!/usr/bin/env sh
# ResuAlign SQLite 在线一致性备份（macOS / Linux 包装）。
#
# 用法：
#   ./scripts/backup.sh                 # 备份默认 data/ 目录
#   ./scripts/backup.sh /path/to/data   # 指定数据目录（也可用 $RESUALIGN_DATA_DIR）
#
# 实际逻辑在 scripts/backup_restore.py（sqlite3 .backup() + uploads 快照
# + manifest），服务可保持运行。
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

PY=""
if command -v python >/dev/null 2>&1; then PY="python"
elif command -v python3 >/dev/null 2>&1; then PY="python3"
else
  echo "[backup] ERROR: python not found" >&2
  exit 1
fi

ARGS="$ROOT/scripts/backup_restore.py backup"
if [ "${1:-}" != "" ]; then
  ARGS="$ARGS --data-dir $1"
fi

# shellcheck disable=SC2086
"$PY" $ARGS
