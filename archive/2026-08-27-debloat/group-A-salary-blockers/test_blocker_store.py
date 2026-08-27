"""Tests for the Sprint 3 automation-rule + blocker-queue store methods."""

import pytest

from resualign.job_library import JobLibraryStore
from resualign.workspace import UserStoreError


@pytest.fixture
def store(tmp_path):
    return JobLibraryStore(db_path=tmp_path / "blocker.db")


# -- automation_rules --------------------------------------------------------


def test_create_and_list_rules(store):
    rule = store.create_rule("tenant-1", "blacklist", "外包，单休", label="外包拦截")
    assert rule["rule_id"]
    assert rule["rule_type"] == "blacklist"
    assert rule["value"] == "外包，单休"
    assert rule["label"] == "外包拦截"
    assert rule["enabled"] is True

    listed = store.list_rules("tenant-1")
    assert [r["rule_id"] for r in listed] == [rule["rule_id"]]


def test_create_rule_validates_type(store):
    with pytest.raises(UserStoreError, match="rule_type"):
        store.create_rule("tenant-1", "unknown_type", "外包")


def test_create_rule_requires_value(store):
    with pytest.raises(UserStoreError, match="value"):
        store.create_rule("tenant-1", "blacklist", "  ")


def test_create_min_salary_rule_validates_number(store):
    with pytest.raises(UserStoreError, match="number"):
        store.create_rule("tenant-1", "min_salary", "not-a-number")
    with pytest.raises(UserStoreError, match="positive"):
        store.create_rule("tenant-1", "min_salary", "-100")
    rule = store.create_rule("tenant-1", "min_salary", "30000")
    assert rule["rule_type"] == "min_salary"


def test_create_rule_disabled(store):
    rule = store.create_rule("tenant-1", "blacklist", "外包", enabled=0)
    assert rule["enabled"] is False


def test_list_rules_enabled_only(store):
    store.create_rule("tenant-1", "blacklist", "外包", enabled=1)
    store.create_rule("tenant-1", "blacklist", "单休", enabled=0)
    enabled = store.list_rules("tenant-1", enabled_only=True)
    assert [r["value"] for r in enabled] == ["外包"]


def test_update_rule(store):
    rule = store.create_rule("tenant-1", "blacklist", "外包")
    updated = store.update_rule(
        "tenant-1", rule["rule_id"], value="外包，单休", label="更新", enabled=0
    )
    assert updated["value"] == "外包，单休"
    assert updated["label"] == "更新"
    assert updated["enabled"] is False


def test_update_rule_partial_keeps_other_fields(store):
    rule = store.create_rule("tenant-1", "blacklist", "外包", label="原标签")
    updated = store.update_rule("tenant-1", rule["rule_id"], enabled=0)
    assert updated["value"] == "外包"
    assert updated["label"] == "原标签"
    assert updated["enabled"] is False


def test_update_rule_requires_nonempty_value(store):
    rule = store.create_rule("tenant-1", "blacklist", "外包")
    with pytest.raises(UserStoreError, match="empty"):
        store.update_rule("tenant-1", rule["rule_id"], value="  ")


def test_update_missing_rule_returns_none(store):
    assert store.update_rule("tenant-1", "missing", enabled=0) is None


def test_delete_rule(store):
    rule = store.create_rule("tenant-1", "blacklist", "外包")
    assert store.delete_rule("tenant-1", rule["rule_id"]) is True
    assert store.get_rule("tenant-1", rule["rule_id"]) is None
    assert store.delete_rule("tenant-1", rule["rule_id"]) is False


def test_rule_tenant_isolation(store):
    rule = store.create_rule("tenant-1", "blacklist", "外包")
    assert store.get_rule("tenant-2", rule["rule_id"]) is None
    assert store.list_rules("tenant-2") == []
    assert store.delete_rule("tenant-2", rule["rule_id"]) is False
    # Updating another tenant's rule must not touch the owner's row.
    assert store.update_rule("tenant-2", rule["rule_id"], value="单休") is None
    assert store.get_rule("tenant-1", rule["rule_id"])["value"] == "外包"


# -- blocker_queue -----------------------------------------------------------


def test_create_and_get_blocker(store):
    blocker = store.create_blocker(
        "tenant-1",
        url="https://example.com/jobs/1",
        title="后端工程师",
        reason="需要登录",
        category="login_required",
    )
    assert blocker["blocker_id"]
    assert blocker["status"] == "pending"
    assert blocker["category"] == "login_required"
    assert blocker["job_id"] is None
    assert blocker["manual_text"] is None

    fetched = store.get_blocker("tenant-1", blocker["blocker_id"])
    assert fetched["url"] == "https://example.com/jobs/1"
    assert fetched["reason"] == "需要登录"


def test_create_blocker_default_category(store):
    blocker = store.create_blocker("tenant-1", url="https://example.com")
    assert blocker["category"] == "fetch_error"


def test_create_blocker_validates_category(store):
    with pytest.raises(UserStoreError, match="category"):
        store.create_blocker("tenant-1", url="https://example.com", category="nope")


def test_create_blocker_default_category_on_blank(store):
    blocker = store.create_blocker("tenant-1", url="https://example.com", category="")
    assert blocker["category"] == "fetch_error"


def test_list_blockers_status_filter(store):
    pending = store.create_blocker(
        "tenant-1", url="https://example.com/1", category="timeout"
    )
    store.ignore_blocker("tenant-1", pending["blocker_id"])

    all_blockers = store.list_blockers("tenant-1")
    assert len(all_blockers) == 1
    assert all_blockers[0]["status"] == "ignored"

    assert store.list_blockers("tenant-1", status="pending") == []
    assert len(store.list_blockers("tenant-1", status="ignored")) == 1


def test_list_blockers_validates_status(store):
    with pytest.raises(UserStoreError, match="status"):
        store.list_blockers("tenant-1", status="nope")


def test_ignore_blocker(store):
    blocker = store.create_blocker(
        "tenant-1", url="https://example.com", category="site_error"
    )
    ignored = store.ignore_blocker("tenant-1", blocker["blocker_id"])
    assert ignored["status"] == "ignored"
    # A second ignore is a no-op, not an error.
    again = store.ignore_blocker("tenant-1", blocker["blocker_id"])
    assert again["status"] == "ignored"


def test_ignore_blocker_missing_returns_none(store):
    assert store.ignore_blocker("tenant-1", "missing") is None


def test_resolve_blocker(store):
    blocker = store.create_blocker(
        "tenant-1", url="https://example.com", category="rule_rejected"
    )
    resolved = store.resolve_blocker(
        "tenant-1",
        blocker["blocker_id"],
        job_id="job-1",
        manual_text="负责后端开发",
    )
    assert resolved["status"] == "resolved"
    assert resolved["job_id"] == "job-1"
    assert resolved["manual_text"] == "负责后端开发"


def test_resolve_blocker_requires_pending(store):
    blocker = store.create_blocker(
        "tenant-1", url="https://example.com", category="timeout"
    )
    store.ignore_blocker("tenant-1", blocker["blocker_id"])
    with pytest.raises(UserStoreError, match="pending"):
        store.resolve_blocker("tenant-1", blocker["blocker_id"], job_id="job-1")


def test_resolve_blocker_requires_job_id(store):
    blocker = store.create_blocker(
        "tenant-1", url="https://example.com", category="timeout"
    )
    with pytest.raises(UserStoreError, match="job_id"):
        store.resolve_blocker("tenant-1", blocker["blocker_id"], job_id="")


def test_resolve_blocker_missing_returns_none(store):
    assert store.resolve_blocker("tenant-1", "missing", job_id="job-1") is None


def test_blocker_tenant_isolation(store):
    blocker = store.create_blocker(
        "tenant-1", url="https://example.com", category="timeout"
    )
    assert store.get_blocker("tenant-2", blocker["blocker_id"]) is None
    assert store.list_blockers("tenant-2") == []
    assert store.ignore_blocker("tenant-2", blocker["blocker_id"]) is None
    # Another tenant cannot see the blocker, so resolution reports None.
    assert (
        store.resolve_blocker("tenant-2", blocker["blocker_id"], job_id="job-1")
        is None
    )
    # The owner's blocker is untouched.
    assert store.get_blocker("tenant-1", blocker["blocker_id"])["status"] == "pending"
