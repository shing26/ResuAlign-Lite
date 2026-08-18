"""MVP-11: one-click backup/restore round trip and upload persistence."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "backup_restore.py"


def _run(data_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["RESUALIGN_DATA_DIR"] = str(data_dir)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _seed_data(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(data_dir / "jobs.db"))
    conn.executescript(
        """
        CREATE TABLE library_jobs (
            job_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            title TEXT NOT NULL,
            jd_text TEXT NOT NULL,
            dedupe_key TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            final_draft TEXT,
            final_draft_version INTEGER NOT NULL DEFAULT 0,
            diffs_json TEXT NOT NULL DEFAULT '[]',
            match_score REAL
        );
        """
    )
    conn.execute(
        "INSERT INTO library_jobs VALUES "
        "('j1', 't1', 'Backend', 'Python', 'text:1', 1, 1, "
        "'# 定稿', 1, '[{\"diff_id\": \"d1\"}]', 82.5)"
    )
    conn.commit()
    conn.close()
    uploads = data_dir / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    (uploads / "resume.txt").write_bytes(b"resume original")


def test_backup_restore_round_trip(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _seed_data(data_dir)

    backup = _run(data_dir, "backup")
    assert backup.returncode == 0, backup.stdout + backup.stderr
    backup_dir = data_dir / "backups"
    manifests = list(backup_dir.glob("manifest-*.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["databases"]["jobs.db"]["integrity"] == "ok"
    assert manifest["uploads_archive"]
    assert list(backup_dir.glob("jobs.db-*.db"))
    assert list(backup_dir.glob("uploads.zip-*.zip"))

    verify = _run(data_dir, "verify", "--manifest", str(manifests[0]))
    assert verify.returncode == 0, verify.stdout + verify.stderr

    # Mutate the live data, then restore and confirm the snapshot wins.
    conn = sqlite3.connect(str(data_dir / "jobs.db"))
    conn.execute(
        "UPDATE library_jobs SET final_draft = '# changed after backup' "
        "WHERE job_id = 'j1'"
    )
    conn.commit()
    conn.close()
    (data_dir / "uploads" / "resume.txt").write_bytes(b"changed after backup")
    (data_dir / "uploads" / "extra.txt").write_bytes(b"extra")

    restore = _run(
        data_dir,
        "restore",
        "--manifest",
        str(manifests[0]),
        "--service-check",
        "0",
    )
    assert restore.returncode == 0, restore.stdout + restore.stderr
    assert "*.pre-restore-" in restore.stdout

    conn = sqlite3.connect(str(data_dir / "jobs.db"))
    row = conn.execute(
        "SELECT final_draft, final_draft_version, match_score "
        "FROM library_jobs WHERE job_id = 'j1'"
    ).fetchone()
    conn.close()
    assert row == ("# 定稿", 1, 82.5)
    assert (data_dir / "uploads" / "resume.txt").read_bytes() == b"resume original"
    assert not (data_dir / "uploads" / "extra.txt").exists()
    assert list(data_dir.glob("jobs.db.pre-restore-*"))
    assert list(data_dir.glob("uploads.pre-restore-*"))
    assert not list(data_dir.glob("jobs.db-wal"))
    assert not list(data_dir.glob("jobs.db-shm"))


def test_restore_refuses_while_service_check_port_is_open(tmp_path: Path) -> None:
    import socket
    import threading

    data_dir = tmp_path / "data"
    _seed_data(data_dir)
    backup = _run(data_dir, "backup")
    assert backup.returncode == 0
    manifest = next((data_dir / "backups").glob("manifest-*.json"))

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    stop = threading.Event()

    def accept_until_stopped() -> None:
        server.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = server.accept()
                conn.close()
            except OSError:
                pass

    thread = threading.Thread(target=accept_until_stopped, daemon=True)
    thread.start()
    try:
        restore = _run(
            data_dir,
            "restore",
            "--manifest",
            str(manifest),
            "--service-check",
            str(port),
        )
    finally:
        stop.set()
        server.close()
        thread.join(timeout=1)
    assert restore.returncode != 0
    assert "stop it before restoring" in restore.stderr
    assert (data_dir / "jobs.db").exists(), "restore must not touch data on refusal"
