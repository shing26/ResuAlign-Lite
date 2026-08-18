"""Shared one-click backup/restore core for ResuAlign.

PowerShell and bash wrappers delegate to this module so the snapshot
semantics, integrity checks, manifest format and upload-directory handling
stay identical across platforms.

Backup (service may stay up):
  - each SQLite database is copied with sqlite3.Connection.backup()
    (a consistent WAL-aware snapshot) and validated with integrity_check;
  - the upload directory is archived into one zip inside the same backup;
  - a JSON manifest records the data dir, upload dir, files, integrity
    results and timestamp so restore can target one consistent snapshot.

Restore (service must be stopped):
  - validates the manifest / backup files;
  - moves the current databases and upload dir to *.pre-restore-<ts>*;
  - restores the snapshot and removes stale -wal/-shm files so SQLite does
    not replay an old WAL over the restored database.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import socket
import sqlite3
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

DB_FILES = ("jobs.db", "content.db", "content-cache.db")
UPLOADS_ZIP = "uploads.zip"


def _now_tag() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _resolve_data_dir(data_dir: str | None) -> Path:
    if data_dir:
        return Path(data_dir).expanduser().resolve()
    import os

    override = os.environ.get("RESUALIGN_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parents[1] / "data"


def _resolve_upload_dir(data_dir: Path) -> Path:
    import os

    override = os.environ.get("RESUALIGN_UPLOAD_DIR")
    return (Path(override).expanduser().resolve() if override else data_dir / "uploads")


def _backup_database(src: Path, dst: Path) -> bool:
    """Copy one SQLite database via the official backup API and verify it."""
    try:
        source = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
        try:
            target = sqlite3.connect(str(dst))
            try:
                with target:
                    source.backup(target)
                row = target.execute("PRAGMA integrity_check").fetchone()
                return bool(row and row[0] == "ok")
            finally:
                target.close()
        finally:
            source.close()
    except sqlite3.Error:
        return False


def _archive_uploads(upload_dir: Path, archive_path: Path) -> int:
    if not upload_dir.is_dir():
        return 0
    count = 0
    with zipfile.ZipFile(
        archive_path, "w", compression=zipfile.ZIP_DEFLATED
    ) as zf:
        for path in sorted(upload_dir.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(upload_dir))
                count += 1
    return count


def _prune_backups(backup_dir: Path) -> int:
    """Remove expired snapshots by filename pattern and modification time.

    Daily backups (plain ``-yyyyMMdd-HHmmss``) stay 7 days; ``weekly-``
    backups stay 30 days. Kept conservative: only files that look like
    ResuAlign backup artifacts are ever removed.
    """
    now = time.time()
    removed = 0
    pattern = re.compile(r"-(?:weekly-)?\d{8}-\d{6}\.db$")
    for path in backup_dir.glob("*.db"):
        name = path.name
        weekly = "-weekly-" in name
        if not pattern.search(name):
            continue
        cutoff = now - (30 if weekly else 7) * 86400
        if path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)
            removed += 1
    return removed


def _extract_uploads(archive_path: Path, upload_dir: Path) -> int:
    if not archive_path.exists():
        return 0
    upload_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(archive_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            target = (upload_dir / info.filename).resolve()
            if not str(target).startswith(str(upload_dir.resolve())):
                raise ValueError(f"unsafe upload path in backup: {info.filename}")
            zf.extract(info, upload_dir)
            count += 1
    return count


def cmd_backup(args: argparse.Namespace) -> int:
    data_dir = _resolve_data_dir(args.data_dir)
    if not data_dir.is_dir():
        print(f"[backup] ERROR: data directory not found: {data_dir}", file=sys.stderr)
        return 1
    upload_dir = _resolve_upload_dir(data_dir)
    backup_dir = data_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    tag = _now_tag()
    prefix = "weekly-" if time.localtime().tm_mday == 1 else ""
    print(f"[backup] start: data dir={data_dir} backup dir={backup_dir}")

    manifest: dict[str, Any] = {
        "app": "ResuAlign-Lite",
        "kind": "snapshot-backup",
        "created_at": time.time(),
        "timestamp": tag,
        "data_dir": str(data_dir),
        "upload_dir": str(upload_dir),
        "databases": {},
        "uploads_archive": None,
        "uploads_count": 0,
    }
    failures: list[str] = []
    for db_name in DB_FILES:
        src = data_dir / db_name
        if not src.is_file():
            print(f"[backup] skip: {db_name} not found")
            continue
        dst = backup_dir / f"{db_name}-{prefix}{tag}.db"
        ok = _backup_database(src, dst)
        if not ok:
            print(f"[backup] FAILED: {db_name} -> {dst.name}", file=sys.stderr)
            dst.unlink(missing_ok=True)
            failures.append(db_name)
            continue
        size = dst.stat().st_size
        manifest["databases"][db_name] = {
            "backup": dst.name,
            "size_bytes": size,
            "integrity": "ok",
        }
        print(f"[backup] ok: {db_name} -> {dst.name} ({size} bytes, integrity=ok)")

    uploads_archive = backup_dir / f"{UPLOADS_ZIP}-{prefix}{tag}.zip"
    count = _archive_uploads(upload_dir, uploads_archive)
    manifest["uploads_archive"] = uploads_archive.name
    manifest["uploads_count"] = count
    if count:
        print(
            f"[backup] ok: uploads -> {uploads_archive.name} ({count} file(s))"
        )
    else:
        print(
            "[backup] uploads: no files found, empty archive still recorded"
        )

    manifest_path = backup_dir / f"manifest-{prefix}{tag}.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[backup] manifest: {manifest_path.name}")
    removed = _prune_backups(backup_dir)
    if removed:
        print(
            f"[backup] retention: removed {removed} expired backup(s) "
            "(daily >7d, weekly >30d)"
        )
    if failures:
        print(f"[backup] FAILED: {', '.join(failures)}", file=sys.stderr)
        return 1
    print(f"[backup] done: {len(manifest['databases'])} database(s) + uploads")
    return 0


def _find_latest_manifest(backup_dir: Path) -> Path | None:
    candidates = sorted(
        backup_dir.glob("manifest-*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _service_listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def cmd_verify(args: argparse.Namespace) -> int:
    data_dir = _resolve_data_dir(args.data_dir)
    backup_dir = data_dir / "backups"
    manifest_path = (
        Path(args.manifest).expanduser().resolve()
        if args.manifest
        else _find_latest_manifest(backup_dir)
    )
    if manifest_path is None or not manifest_path.is_file():
        print("[restore] ERROR: no backup manifest found", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    ok = True
    for db_name, info in (manifest.get("databases") or {}).items():
        backup_file = backup_dir / str(info["backup"])
        if not backup_file.is_file():
            print(f"[verify] MISSING: {db_name} -> {backup_file}", file=sys.stderr)
            ok = False
            continue
        conn = sqlite3.connect(str(backup_file))
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
            integrity = row[0] if row else "error"
        finally:
            conn.close()
        if integrity != "ok":
            print(f"[verify] BAD INTEGRITY: {db_name}", file=sys.stderr)
            ok = False
        else:
            print(f"[verify] ok: {db_name} -> {backup_file.name}")
    archive_name = manifest.get("uploads_archive")
    if archive_name:
        archive = backup_dir / str(archive_name)
        if not archive.is_file():
            print(f"[verify] MISSING uploads archive: {archive}", file=sys.stderr)
            ok = False
        else:
            print(f"[verify] ok: uploads -> {archive.name}")
    return 0 if ok else 1


def cmd_restore(args: argparse.Namespace) -> int:
    data_dir = _resolve_data_dir(args.data_dir)
    backup_dir = data_dir / "backups"
    manifest_path = (
        Path(args.manifest).expanduser().resolve()
        if args.manifest
        else _find_latest_manifest(backup_dir)
    )
    if manifest_path is None or not manifest_path.is_file():
        print("[restore] ERROR: no backup manifest found", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if args.service_check and not args.force and _service_listening(args.service_check):
        print(
            "[restore] ERROR: a service is listening on port "
            f"{args.service_check}; stop it before restoring (or pass --force)",
            file=sys.stderr,
        )
        return 1
    tag = _now_tag()

    def preserve(path: Path) -> Path:
        if not path.exists():
            return path
        target = path.with_name(f"{path.name}.pre-restore-{tag}")
        shutil.move(str(path), str(target))
        return target

    for db_name in DB_FILES:
        current = data_dir / db_name
        for suffix in ("-wal", "-shm"):
            sidecar = data_dir / f"{db_name}{suffix}"
            if sidecar.exists():
                preserve(sidecar)
        preserve(current)

    restored: list[str] = []
    for db_name, info in (manifest.get("databases") or {}).items():
        backup_file = backup_dir / str(info["backup"])
        if not backup_file.is_file():
            print(f"[restore] ERROR: missing backup file {backup_file}", file=sys.stderr)
            return 1
        target = data_dir / db_name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(backup_file), str(target))
        for suffix in ("-wal", "-shm"):
            (data_dir / f"{db_name}{suffix}").unlink(missing_ok=True)
        print(f"[restore] ok: {db_name} <- {backup_file.name}")
        restored.append(db_name)

    upload_dir = _resolve_upload_dir(data_dir)
    if upload_dir.exists():
        preserve(upload_dir)
    archive_name = manifest.get("uploads_archive")
    if archive_name:
        archive = backup_dir / str(archive_name)
        if not archive.is_file():
            print(f"[restore] ERROR: missing uploads archive {archive}", file=sys.stderr)
            return 1
        count = _extract_uploads(archive, upload_dir)
        print(f"[restore] ok: uploads <- {archive.name} ({count} file(s))")
    elif upload_dir.exists():
        upload_dir.mkdir(parents=True, exist_ok=True)

    print(
        "[restore] done: "
        + ", ".join(restored)
        + "; previous files kept as *.pre-restore-"
        + tag
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="backup_restore",
        description="ResuAlign one-click backup / restore / verify",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    backup = sub.add_parser("backup", help="create a consistent snapshot")
    backup.add_argument("--data-dir", dest="data_dir", default=None)
    backup.set_defaults(func=cmd_backup)
    verify = sub.add_parser("verify", help="validate a snapshot")
    verify.add_argument("--data-dir", dest="data_dir", default=None)
    verify.add_argument("--manifest", default=None)
    verify.set_defaults(func=cmd_verify)
    restore = sub.add_parser("restore", help="restore a snapshot (service stopped)")
    restore.add_argument("--data-dir", dest="data_dir", default=None)
    restore.add_argument("--manifest", default=None)
    restore.add_argument(
        "--service-check",
        type=int,
        default=8000,
        help="refuse restore while this port is listening (0 disables)",
    )
    restore.add_argument(
        "--force",
        action="store_true",
        help="restore even when the service-check port is listening",
    )
    restore.set_defaults(func=cmd_restore)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
