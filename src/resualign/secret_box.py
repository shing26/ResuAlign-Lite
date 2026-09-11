"""At-rest encryption for LLM API keys stored in local SQLite.

Threat model (ADR-0035): the workspace databases are plain files that get
copied by backups, cloud-sync folders, and accidental shares. Encrypting the
key material at rest ensures a leaked *database file alone* does not leak
usable LLM credentials. The encryption key lives in a separate file under
the data directory — this is honest about its limits: a full-disk compromise
(data dir included) still yields the key, so this is hardening, not sandboxing.

Storage format: ``enc:v1:<fernet-token>``. Values without the prefix are
returned as-is on decrypt (legacy plaintext rows keep working; they are
re-encrypted the next time they are saved).
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .store_base import resolve_data_dir

_PREFIX = "enc:v1:"

_SECRET_FILE_ENV = "RESUALIGN_SECRET_KEY_FILE"

_lock = threading.Lock()
_fernet: Fernet | None = None


def _key_file() -> Path:
    override = os.environ.get(_SECRET_FILE_ENV, "").strip()
    if override:
        return Path(override)
    return resolve_data_dir() / "secret.key"


def _load_or_create_fernet() -> Fernet:
    """Load the data-dir key file, creating a fresh key on first use.

    创建用 O_EXCL：并发首开时输的一方退回读取现存密钥，避免裸抛
    FileExistsError。
    """
    global _fernet
    with _lock:
        if _fernet is not None:
            return _fernet
        path = _key_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            key = path.read_bytes().strip()
            if not key:
                # Treat a truncated/empty key file as unrecoverable rather
                # than silently rotating it (that would brick stored keys).
                raise RuntimeError(
                    f"密钥文件为空：{path}。删除它会让已存 API Key 永久无法解密，"
                    "请先恢复该文件或重新录入各节点的 API Key。"
                )
        else:
            key = Fernet.generate_key()
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as handle:
                    handle.write(key + b"\n")
            except FileExistsError:
                # 并发进程赢下了创建权：改读它写入的密钥。
                key = path.read_bytes().strip()
        _fernet = Fernet(key)
        return _fernet


def reset_cache() -> None:
    """Drop the cached Fernet (tests swap key files; stores reload lazily)."""
    global _fernet
    with _lock:
        _fernet = None


def encrypt_value(value: str | None) -> str | None:
    """Encrypt a secret for storage; None/empty and already-encrypted pass through."""
    if value is None or value == "":
        return value
    if value.startswith(_PREFIX):
        return value
    fernet = _load_or_create_fernet()
    token = fernet.encrypt(value.encode("utf-8")).decode("ascii")
    return f"{_PREFIX}{token}"


def decrypt_value(value: str | None) -> str | None:
    """Decrypt a stored secret; legacy plaintext (no prefix) passes through."""
    if value is None or value == "":
        return value
    if not value.startswith(_PREFIX):
        return value
    fernet = _load_or_create_fernet()
    token = value[len(_PREFIX):]
    try:
        return fernet.decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        # from None：原始 InvalidToken 对终端用户无意义，恢复指引已在上文；
        # 类型根因（密钥不匹配 vs 载荷损坏）可由 message 中的场景区分。
        raise RuntimeError(
            "已存 API Key 解密失败：密钥文件缺失、被替换或损坏。"
            f"请恢复 {_key_file()}（或在系统设置重新录入各节点的 API Key）。"
        ) from None
