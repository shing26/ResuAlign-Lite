"""Tests for the SQLite-backed user/session store and tenant scoping."""

import pytest

from resualign.jobs import JobRegistry
from resualign.workspace import (
    ApplicationStore,
    MasterResumeStore,
    UserStore,
    UserStoreError,
)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "workspace.db"


def _store(db_path):
    return UserStore(db_path=db_path)


def test_create_user_and_login(db_path):
    store = _store(db_path)

    user = store.create_user("ada@example.com", "correct-horse")

    assert user["user_id"]
    assert user["email"] == "ada@example.com"
    assert "password" not in user
    assert "password_hash" not in user
    assert "salt" not in user

    token = store.login("ada@example.com", "correct-horse")
    assert token


def test_duplicate_email_rejected(db_path):
    store = _store(db_path)
    store.create_user("ada@example.com", "password-1")

    with pytest.raises(UserStoreError):
        store.create_user("ada@example.com", "password-2")


def test_wrong_password_rejected(db_path):
    store = _store(db_path)
    store.create_user("ada@example.com", "correct-horse")

    with pytest.raises(UserStoreError):
        store.login("ada@example.com", "wrong-password")


def test_unknown_email_rejected(db_path):
    store = _store(db_path)

    with pytest.raises(UserStoreError):
        store.login("missing@example.com", "password")


def test_token_roundtrip_and_revocation(db_path):
    store = _store(db_path)
    store.create_user("ada@example.com", "correct-horse")
    token = store.login("ada@example.com", "correct-horse")

    user = store.user_for_token(token)
    assert user["email"] == "ada@example.com"

    store.revoke_token(token)

    assert store.user_for_token(token) is None


def test_invalid_token_returns_none(db_path):
    store = _store(db_path)

    assert store.user_for_token("not-a-real-token") is None


def test_tokens_are_stored_hashed_not_plaintext(db_path):
    store = _store(db_path)
    store.create_user("ada@example.com", "correct-horse")
    token = store.login("ada@example.com", "correct-horse")

    raw = db_path.read_bytes()
    assert token.encode("utf-8") not in raw
    assert b"correct-horse" not in raw


def test_passwords_are_hashed_with_salt(db_path):
    store = _store(db_path)
    first = store.create_user("one@example.com", "same-password")
    second = store.create_user("two@example.com", "same-password")

    assert first["user_id"] != second["user_id"]
    raw = db_path.read_bytes()
    assert b"same-password" not in raw


def test_job_registry_scopes_jobs_by_tenant(db_path):
    registry = JobRegistry(db_path=db_path)
    tenant_a = "tenant-a"
    tenant_b = "tenant-b"

    job_a = registry.create({"resume_text": "A"}, object(), tenant_id=tenant_a)
    job_b = registry.create({"resume_text": "B"}, object(), tenant_id=tenant_b)

    assert registry.snapshot(job_a.job_id, tenant_id=tenant_a) is not None
    assert registry.snapshot(job_a.job_id, tenant_id=tenant_b) is None
    assert registry.snapshot(job_a.job_id) is not None
    assert registry.get(job_b.job_id, tenant_id=tenant_b) is not None
    assert registry.get(job_b.job_id, tenant_id=tenant_a) is None


def test_old_job_database_migrates_tenant_column(tmp_path):
    import sqlite3

    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE jobs ("
        "job_id TEXT PRIMARY KEY, status TEXT NOT NULL, stage TEXT NOT NULL "
        "DEFAULT '', message TEXT NOT NULL DEFAULT '', created_at REAL NOT "
        "NULL, started_at REAL, finished_at REAL, result_json TEXT, "
        "error TEXT)"
    )
    conn.commit()
    conn.close()

    registry = JobRegistry(db_path=db_path)
    job = registry.create(
        {"resume_text": "legacy"},
        object(),
        tenant_id="tenant-x",
    )

    assert registry.snapshot(job.job_id, tenant_id="tenant-x") is not None
    assert registry.snapshot(job.job_id, tenant_id="other") is None


def test_master_resume_create_versions_and_get(db_path):
    store = MasterResumeStore(db_path=db_path)

    created = store.create_master_resume(
        "tenant-1", "Master Resume", "Python developer."
    )
    assert created["resume_id"]
    assert created["current_version"] == 1
    assert created["title"] == "Master Resume"

    detail = store.get_master_resume("tenant-1", created["resume_id"])
    assert detail["current_version"] == 1
    assert detail["content"] == "Python developer."
    assert len(detail["versions"]) == 1
    assert detail["versions"][0]["version"] == 1


def test_master_resume_update_creates_version(db_path):
    store = MasterResumeStore(db_path=db_path)
    created = store.create_master_resume(
        "tenant-1", "Master Resume", "Python developer."
    )

    updated = store.update_master_resume(
        "tenant-1", created["resume_id"], "Python developer. FastAPI."
    )

    assert updated["current_version"] == 2
    detail = store.get_master_resume("tenant-1", created["resume_id"])
    assert detail["current_version"] == 2
    assert len(detail["versions"]) == 2
    assert detail["content"] == "Python developer. FastAPI."


def test_master_resume_rollback_to_previous_version(db_path):
    store = MasterResumeStore(db_path=db_path)
    created = store.create_master_resume(
        "tenant-1", "Master Resume", "Python developer."
    )
    store.update_master_resume(
        "tenant-1", created["resume_id"], "Python developer. FastAPI."
    )

    rolled = store.rollback_master_resume(
        "tenant-1", created["resume_id"], 1
    )

    assert rolled["current_version"] == 1
    detail = store.get_master_resume("tenant-1", created["resume_id"])
    assert detail["content"] == "Python developer."
    assert len(detail["versions"]) == 2


def test_master_resume_update_after_rollback_uses_unique_version(db_path):
    store = MasterResumeStore(db_path=db_path)
    created = store.create_master_resume(
        "tenant-1", "Master Resume", "Python developer."
    )
    store.update_master_resume(
        "tenant-1", created["resume_id"], "Python developer. FastAPI."
    )
    store.rollback_master_resume("tenant-1", created["resume_id"], 1)

    updated = store.update_master_resume(
        "tenant-1", created["resume_id"], "Python developer. FastAPI. Docker."
    )

    assert updated["current_version"] == 3
    detail = store.get_master_resume("tenant-1", created["resume_id"])
    assert [v["version"] for v in detail["versions"]] == [1, 2, 3]


def test_master_resume_is_tenant_scoped(db_path):
    store = MasterResumeStore(db_path=db_path)
    created = store.create_master_resume(
        "tenant-1", "Master Resume", "Python developer."
    )

    assert store.get_master_resume("tenant-2", created["resume_id"]) is None
    assert store.list_master_resumes("tenant-2") == []


def test_master_resume_delete(db_path):
    store = MasterResumeStore(db_path=db_path)
    created = store.create_master_resume(
        "tenant-1", "Master Resume", "Python developer."
    )

    assert (
        store.delete_master_resume(
            "tenant-1", created["resume_id"]
        )
        is True
    )
    assert store.get_master_resume("tenant-1", created["resume_id"]) is None
    assert (
        store.delete_master_resume(
            "tenant-1", created["resume_id"]
        )
        is False
    )


def test_master_resume_tracks_latest_diagnosis_job(db_path):
    store = MasterResumeStore(db_path=db_path)
    created = store.create_master_resume(
        "tenant-1", "Master Resume", "Python developer."
    )

    linked = store.set_latest_diagnosis_job(
        "tenant-1", created["resume_id"], "job-1"
    )
    assert linked["latest_diagnosis_job_id"] == "job-1"
    detail = store.get_master_resume("tenant-1", created["resume_id"])
    assert detail["latest_diagnosis_job_id"] == "job-1"
    assert store.list_master_resumes("tenant-1")[0][
        "latest_diagnosis_job_id"
    ] == "job-1"
    assert (
        store.set_latest_diagnosis_job(
            "tenant-2", created["resume_id"], "job-2"
        )
        is None
    )


def test_old_master_resume_database_migrates_diagnosis_column(tmp_path):
    import sqlite3

    db_path = tmp_path / "legacy-master.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE master_resumes ("
        "resume_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, title TEXT NOT "
        "NULL, current_version INTEGER NOT NULL DEFAULT 1, created_at REAL "
        "NOT NULL, updated_at REAL NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE resume_versions ("
        "version_id TEXT PRIMARY KEY, resume_id TEXT NOT NULL, tenant_id TEXT "
        "NOT NULL, version INTEGER NOT NULL, content TEXT NOT NULL, "
        "created_at REAL NOT NULL, UNIQUE(resume_id, version))"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_resume_versions_resume "
        "ON resume_versions(resume_id)"
    )
    conn.commit()
    conn.close()

    store = MasterResumeStore(db_path=db_path)
    created = store.create_master_resume(
        "tenant-1", "Legacy", "Old content."
    )
    assert created["latest_diagnosis_job_id"] is None

    linked = store.set_latest_diagnosis_job(
        "tenant-1", created["resume_id"], "job-abc"
    )
    assert linked["latest_diagnosis_job_id"] == "job-abc"


def test_master_resume_clears_dangling_diagnosis_job(db_path):
    store = MasterResumeStore(db_path=db_path)
    created = store.create_master_resume(
        "tenant-1", "Master Resume", "Python developer."
    )
    linked = store.set_latest_diagnosis_job(
        "tenant-1", created["resume_id"], "job-1"
    )
    assert linked["latest_diagnosis_job_id"] == "job-1"

    cleared = store.clear_latest_diagnosis_job(
        "tenant-1", created["resume_id"]
    )
    assert cleared is not None
    assert cleared["latest_diagnosis_job_id"] is None
    detail = store.get_master_resume("tenant-1", created["resume_id"])
    assert detail["latest_diagnosis_job_id"] is None
    assert (
        store.clear_latest_diagnosis_job("tenant-2", created["resume_id"])
        is None
    )


def test_application_creation_snapshots_resume_version(db_path):
    resume_store = MasterResumeStore(db_path=db_path)
    app_store = ApplicationStore(db_path=db_path)
    resume = resume_store.create_master_resume(
        "tenant-1", "Master Resume", "Python developer."
    )
    resume_store.update_master_resume(
        "tenant-1", resume["resume_id"], "Python developer. FastAPI."
    )

    app = app_store.create_application(
        tenant_id="tenant-1",
        title="Backend at Acme",
        master_resume_id=resume["resume_id"],
        jd_text="Looking for a Python backend engineer.",
    )

    assert app["application_id"]
    assert app["title"] == "Backend at Acme"
    assert app["master_resume_id"] == resume["resume_id"]
    assert app["resume_version"] == 2
    assert app["resume_snapshot"] == "Python developer. FastAPI."
    assert app["jd_text"] == "Looking for a Python backend engineer."
    assert app["status"] == "draft"


def test_application_lists_and_details_are_tenant_scoped(db_path):
    resume_store = MasterResumeStore(db_path=db_path)
    app_store = ApplicationStore(db_path=db_path)
    resume = resume_store.create_master_resume(
        "tenant-1", "Master Resume", "Python developer."
    )
    app_store.create_application(
        tenant_id="tenant-1",
        title="Backend at Acme",
        master_resume_id=resume["resume_id"],
    )

    assert len(app_store.list_applications("tenant-1")) == 1
    assert app_store.list_applications("tenant-2") == []
    app_id = app_store.list_applications("tenant-1")[0]["application_id"]
    assert app_store.get_application("tenant-2", app_id) is None


def test_application_update_and_job_link(db_path):
    resume_store = MasterResumeStore(db_path=db_path)
    app_store = ApplicationStore(db_path=db_path)
    resume = resume_store.create_master_resume(
        "tenant-1", "Master Resume", "Python developer."
    )
    app = app_store.create_application(
        tenant_id="tenant-1",
        title="Backend at Acme",
        master_resume_id=resume["resume_id"],
        jd_text="old jd",
    )

    updated = app_store.update_application(
        "tenant-1",
        app["application_id"],
        title="Backend at Acme (updated)",
        jd_text="new jd",
    )
    assert updated["title"] == "Backend at Acme (updated)"
    assert updated["jd_text"] == "new jd"
    assert updated["resume_snapshot"] == "Python developer."

    linked = app_store.set_application_job(
        "tenant-1", app["application_id"], "job-123", "running"
    )
    assert linked["latest_job_id"] == "job-123"
    assert linked["status"] == "running"


def test_application_delete(db_path):
    resume_store = MasterResumeStore(db_path=db_path)
    app_store = ApplicationStore(db_path=db_path)
    resume = resume_store.create_master_resume(
        "tenant-1", "Master Resume", "Python developer."
    )
    app = app_store.create_application(
        tenant_id="tenant-1",
        title="Backend at Acme",
        master_resume_id=resume["resume_id"],
    )

    assert (
        app_store.delete_application(
            "tenant-1", app["application_id"]
        )
        is True
    )
    assert app_store.get_application("tenant-1", app["application_id"]) is None
    assert (
        app_store.delete_application(
            "tenant-1", app["application_id"]
        )
        is False
    )


def test_application_requires_existing_resume(db_path):
    app_store = ApplicationStore(db_path=db_path)

    with pytest.raises(UserStoreError):
        app_store.create_application(
            tenant_id="tenant-1",
            title="Backend at Acme",
            master_resume_id="missing",
        )
