#!/usr/bin/env sh
# ResuAlign SQLite 在线一致性备份（macOS / Linux）。
#
# 用法：
#   ./scripts/backup.sh                 # 备份默认 data/ 目录
#   ./scripts/backup.sh /path/to/data   # 指定数据目录（也可用 $RESUALIGN_DATA_DIR）
#
# 使用 Python sqlite3 .backup() API 做在线一致性备份，服务可保持运行。
# 备份目录：<DataDir>/backups/
# 文件名：  {dbname}-{yyyyMMdd-HHmmss}.db
#           每月 1 号生成 {dbname}-weekly-{yyyyMMdd-HHmmss}.db
# 保留策略：日备份保留 7 天；weekly 备份保留 30 天（简化版，见 docs/backup-restore.md）。
#
# 不要在服务运行时直接 cp 复制 .db 文件：WAL 模式下直接复制会得到不一致快照。
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
DATA_DIR="${1:-${RESUALIGN_DATA_DIR:-data}}"
case "$DATA_DIR" in
  /*) ;;
  *) DATA_DIR="$ROOT/$DATA_DIR" ;;
esac

if [ ! -d "$DATA_DIR" ]; then
  echo "[backup] ERROR: data directory not found: $DATA_DIR" >&2
  exit 1
fi

PY=""
if command -v python >/dev/null 2>&1; then PY="python"
elif command -v python3 >/dev/null 2>&1; then PY="python3"
else
  echo "[backup] ERROR: python not found (needed for the sqlite3 backup API)" >&2
  exit 1
fi

BACKUP_DIR="$DATA_DIR/backups"
mkdir -p "$BACKUP_DIR"

TS="$(date +%Y%m%d-%H%M%S)"
PREFIX=""
if [ "$(date +%d)" = "01" ]; then
  PREFIX="weekly-"
fi

echo "[backup] start: data dir=$DATA_DIR backup dir=$BACKUP_DIR"

# Python 片段：打开源库 -> .backup() 在线备份到目标库 -> PRAGMA integrity_check。
PY_BACKUP='import sqlite3, sys
src = sqlite3.connect(sys.argv[1])
dst = sqlite3.connect(sys.argv[2])
with dst:
    src.backup(dst)
print(dst.execute("PRAGMA integrity_check").fetchone()[0])
dst.close()
src.close()'

fail=0
for db in jobs.db content.db content-cache.db; do
  src="$DATA_DIR/$db"
  if [ ! -f "$src" ]; then
    echo "[backup] skip: $db not found"
    continue
  fi
  dst="$BACKUP_DIR/$db-$PREFIX$TS.db"
  if integrity="$(printf '%s\n' "$PY_BACKUP" | "$PY" - "$src" "$dst")" && [ "$integrity" = "ok" ]; then
    size="$(wc -c < "$dst" | tr -d ' ')"
    echo "[backup] ok: $db -> $(basename "$dst") (${size} bytes, integrity=${integrity})"
  else
    echo "[backup] FAILED: $db -> $(basename "$dst") (integrity=${integrity:-none})" >&2
    rm -f "$dst"
    fail=$((fail + 1))
  fi
done

# 保留策略：按文件名区分日备份与 weekly 备份，按修改时间清理。
count_backups() {
  find "$BACKUP_DIR" -maxdepth 1 -type f -name '*.db' \( \
      -name '*-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9].db' \
      -o -name '*-weekly-*.db' \) | wc -l | tr -d ' '
}
before="$(count_backups)"
# 日备份（明确排除 weekly）：超过 7 天删除
find "$BACKUP_DIR" -maxdepth 1 -type f \
  -name '*-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9].db' \
  ! -name '*-weekly-*' -mtime +7 -delete 2>/dev/null || true
# weekly 备份（每月 1 号）：超过 30 天删除
find "$BACKUP_DIR" -maxdepth 1 -type f \
  -name '*-weekly-*.db' -mtime +30 -delete 2>/dev/null || true
after="$(count_backups)"
removed=$((before - after))
echo "[backup] retention: removed ${removed} expired backup(s) (daily >7d, weekly >30d)"

if [ "$fail" -gt 0 ]; then
  echo "[backup] FAILED: ${fail} database(s)" >&2
  exit 1
fi
echo "[backup] done: all databases backed up to $BACKUP_DIR"
