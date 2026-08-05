"""Tests for the SQLite content blob store."""

import hashlib

import pytest

from resualign.content_store import ContentStore


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _store(tmp_path, **kwargs):
    return ContentStore(db_path=tmp_path / "content.db", **kwargs)


def test_put_dedupes_and_delete_releases_references(tmp_path):
    store = _store(tmp_path)
    digest = _sha("same payload")

    assert store.put(digest, "same payload", "text/plain") == digest
    assert store.put(digest, "same payload", "text/plain") == digest

    assert store.ref_count(digest) == 2
    assert store.total_size() == len("same payload")
    assert store.get(digest) == b"same payload"
    assert store.get_text(digest) == "same payload"

    assert store.delete(digest) is True
    assert store.exists(digest) is True
    assert store.get(digest) == b"same payload"

    assert store.delete(digest) is True
    assert store.exists(digest) is False
    assert store.get(digest) is None
    assert store.delete(digest) is False


def test_content_store_persists_across_instances(tmp_path):
    db_path = tmp_path / "content.db"
    digest = _sha("persisted payload")
    ContentStore(db_path=db_path).put(
        digest, "persisted payload", "text/plain"
    )

    reopened = ContentStore(db_path=db_path)

    assert reopened.get(digest) == b"persisted payload"


def test_ttl_removes_expired_content(tmp_path):
    now = [100.0]
    store = _store(
        tmp_path,
        default_ttl_seconds=10,
        clock=lambda: now[0],
    )
    digest = _sha("temporary payload")
    store.put(digest, "temporary payload", "text/plain")

    assert store.get(digest) == b"temporary payload"

    now[0] = 111.0

    assert store.get(digest) is None
    assert store.exists(digest) is False


def test_size_cap_evicts_oldest_blob(tmp_path):
    store = _store(tmp_path, max_bytes=100, default_ttl_seconds=None)
    older = _sha("a" * 80)
    newer = _sha("b" * 80)

    store.put(older, "a" * 80, "text/plain")
    store.put(newer, "b" * 80, "text/plain")

    assert store.exists(older) is False
    assert store.exists(newer) is True
    assert store.total_size() <= 100


def test_put_rejects_sha256_mismatch(tmp_path):
    store = _store(tmp_path)

    with pytest.raises(ValueError, match="does not match"):
        store.put(_sha("actual"), "different", "text/plain")
