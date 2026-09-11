"""ADR-0035: API Key 静态加密（secret_box）round-trip 与存储层集成。"""

import pytest
from cryptography.fernet import Fernet

from resualign import secret_box
from resualign.secret_box import decrypt_value, encrypt_value
from resualign.settings_store import SettingsStore
from resualign.workspace import UserStore

from .conftest import fake_api_key


def test_roundtrip_encrypts_with_prefix_and_decrypts():
    plain = fake_api_key("roundtrip")
    stored = encrypt_value(plain)
    assert stored != plain
    assert stored.startswith("enc:v1:")
    assert decrypt_value(stored) == plain


def test_none_and_empty_and_legacy_plaintext_pass_through():
    assert encrypt_value(None) is None
    assert encrypt_value("") == ""
    assert decrypt_value(None) is None
    assert decrypt_value("") == ""
    # 遗留明文（无前缀）原样透传——存量行不炸，下次保存自然升级
    legacy = fake_api_key("legacy")
    assert decrypt_value(legacy) == legacy


def test_encrypt_is_idempotent_for_already_encrypted_values():
    once = encrypt_value(fake_api_key("idem"))
    assert encrypt_value(once) == once


def test_key_file_is_created_on_first_use(tmp_path, monkeypatch):
    key_path = tmp_path / "nested" / "secret.key"
    monkeypatch.setenv("RESUALIGN_SECRET_KEY_FILE", str(key_path))
    secret_box.reset_cache()
    encrypt_value(fake_api_key("create"))
    assert key_path.exists()
    secret_box.reset_cache()


def test_wrong_key_file_raises_readable_error(tmp_path, monkeypatch):
    plain = fake_api_key("lost")
    stored = encrypt_value(plain)
    # 换一把钥匙（模拟密钥文件丢失后被重建）
    other = tmp_path / "other.key"
    other.write_bytes(Fernet.generate_key())
    monkeypatch.setenv("RESUALIGN_SECRET_KEY_FILE", str(other))
    secret_box.reset_cache()
    with pytest.raises(RuntimeError, match="解密失败"):
        decrypt_value(stored)
    secret_box.reset_cache()


def _store_pair(tmp_path):
    db = tmp_path / "kv.db"
    users = UserStore(db_path=db)
    settings = SettingsStore(db_path=db)
    user = users.get_or_create_personal_user()
    tenant = user["tenant_id"] if "tenant_id" in user else user["user_id"]
    return settings, tenant


def test_settings_store_encrypts_llm_api_key_at_rest(tmp_path):
    settings, tenant = _store_pair(tmp_path)
    key = fake_api_key("atrest")
    current = settings.get_settings(tenant)
    llm = dict(current["llm"])
    llm["api_key"] = key
    settings.update_settings(tenant, {"llm": llm})

    # 落库的是密文：raw llm_json 不含明文 key
    import sqlite3

    conn = sqlite3.connect(tmp_path / "kv.db")
    try:
        raw = conn.execute(
            "SELECT llm_json FROM user_settings WHERE tenant_id = ?", (tenant,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert key not in raw
    assert "enc:v1:" in raw
    # 读回解密：API 层拿到的仍是明文（掩码在路由层做）
    reread = settings.get_settings(tenant)
    assert reread["llm"]["api_key"] == key


def test_settings_store_roundtrip_keeps_stored_key_on_partial_update(tmp_path):
    settings, tenant = _store_pair(tmp_path)
    llm = dict(settings.get_settings(tenant)["llm"])
    llm["api_key"] = fake_api_key("mask")
    settings.update_settings(tenant, {"llm": llm})
    # 部分更新不带 api_key 字段 → 合并语义保留已存（已解密的）key
    settings.update_settings(tenant, {"llm": {"provider": "deepseek"}})
    final = settings.get_settings(tenant)["llm"]
    assert final["api_key"] == fake_api_key("mask")
