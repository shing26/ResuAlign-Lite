"""Tests for the tenant-scoped Job Library store."""

import sqlite3

import pytest

from resualign.job_library import (
    JOB_FUNCTIONS,
    SENIORITIES,
    CrawlTaskStore,
    JobLibraryStore,
)
from resualign.workspace import UserStoreError


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "jobs.db"


def _store(db_path):
    return JobLibraryStore(db_path=db_path)


def _job_payload(**overrides):
    payload = {
        "tenant_id": "tenant-1",
        "title": "Backend Engineer",
        "jd_text": "Python backend engineer. Salary 20-30K.",
        "company": "Acme",
        "location": "Shanghai",
        "salary_min": 20000,
        "salary_max": 30000,
    }
    payload.update(overrides)
    return payload


def test_create_and_get_job(db_path):
    store = _store(db_path)

    job = store.create_job(**_job_payload())

    assert job["job_id"]
    assert job["title"] == "Backend Engineer"
    assert job["company"] == "Acme"
    assert job["location"] == "Shanghai"
    assert job["salary_min"] == 20000
    assert job["salary_max"] == 30000
    assert job["status"] == "draft"  # Bug-12: canonical storage
    assert job["job_function"] is None
    assert job["classification_pending"] == 0
    assert job["final_draft"] is None
    assert job["final_draft_updated_at"] is None

    fetched = store.get_job("tenant-1", job["job_id"])
    assert fetched["jd_text"] == "Python backend engineer. Salary 20-30K."


def test_create_and_update_classification_pending(db_path):
    store = _store(db_path)
    job = store.create_job(**_job_payload())

    pending = store.create_job(
        **_job_payload(
            title="Pending Engineer",
            jd_text="Pending JD text",
            classification_pending=1,
        )
    )
    assert pending["classification_pending"] == 1

    updated = store.update_job(
        "tenant-1", job["job_id"], classification_pending=1
    )
    assert updated["classification_pending"] == 1

    cleared = store.update_job(
        "tenant-1", job["job_id"], classification_pending=0
    )
    assert cleared["classification_pending"] == 0


def test_rejects_invalid_classification_pending(db_path):
    store = _store(db_path)

    with pytest.raises(UserStoreError, match="classification_pending"):
        store.create_job(
            **_job_payload(
                title="Bad pending",
                jd_text="Bad pending JD",
                classification_pending=2,
            )
        )

    job = store.create_job(**_job_payload())
    with pytest.raises(UserStoreError, match="classification_pending"):
        store.update_job(
            "tenant-1", job["job_id"], classification_pending=-1
        )


def test_save_final_draft_increments_version_and_persists(db_path):
    store = _store(db_path)
    job = store.create_job(**_job_payload())

    first = store.save_final_draft(
        "tenant-1", job["job_id"], "Final draft one"
    )
    assert first["draft"] == "Final draft one"
    assert first["version"] == 1
    assert first["updated_at"] > 0

    fetched = store.get_job("tenant-1", job["job_id"])
    assert fetched["final_draft"] == "Final draft one"
    assert fetched["final_draft_updated_at"] == first["updated_at"]
    assert fetched["final_draft_version"] == 1

    second = store.save_final_draft(
        "tenant-1", job["job_id"], "Final draft two"
    )
    assert second["version"] == 2
    assert second["updated_at"] >= first["updated_at"]

    overwritten = store.get_job("tenant-1", job["job_id"])
    assert overwritten["final_draft"] == "Final draft two"
    assert overwritten["final_draft_version"] == 2


def test_save_final_draft_rejects_empty_text_and_missing_job(db_path):
    store = _store(db_path)
    job = store.create_job(**_job_payload())

    with pytest.raises(UserStoreError, match="draft"):
        store.save_final_draft("tenant-1", job["job_id"], "   ")
    assert store.save_final_draft("tenant-1", "missing", "Draft") is None


def test_duplicate_url_rejected(db_path):
    store = _store(db_path)
    store.create_job(
        **_job_payload(
            source_type="url",
            source_url="https://example.com/job/1",
        )
    )

    with pytest.raises(UserStoreError, match="Duplicate job"):
        store.create_job(
            **_job_payload(
                title="Different title",
                source_type="url",
                source_url="https://example.com/job/1",
            )
        )


def test_duplicate_paste_text_rejected(db_path):
    store = _store(db_path)
    store.create_job(**_job_payload(source_type="paste"))

    with pytest.raises(UserStoreError, match="Duplicate job"):
        store.create_job(
            **_job_payload(
                title="Different title",
                jd_text="python backend engineer. salary 20-30k.",
                source_type="paste",
            )
        )


def test_same_text_allowed_across_tenants(db_path):
    store = _store(db_path)
    store.create_job(**_job_payload(tenant_id="tenant-1"))

    job = store.create_job(**_job_payload(tenant_id="tenant-2"))

    assert job["tenant_id"] == "tenant-2"


def test_list_filters_by_function_seniority_status_and_search(db_path):
    store = _store(db_path)
    store.create_job(
        **_job_payload(
            title="Backend Engineer",
            jd_text="Java backend.",
            job_function="后端",
            seniority="高级",
            status="已投递",
        )
    )
    store.create_job(
        **_job_payload(
            title="Frontend Engineer",
            jd_text="React frontend.",
            job_function="前端",
            seniority="中级",
            status="未投递",
        )
    )

    assert len(store.list_jobs("tenant-1", job_function="后端")) == 1
    assert len(store.list_jobs("tenant-1", seniority="中级")) == 1
    assert len(store.list_jobs("tenant-1", status="已投递")) == 1
    assert len(store.list_jobs("tenant-1", search="React")) == 1
    assert len(store.list_jobs("tenant-1")) == 2
    assert store.list_jobs("tenant-2") == []


def test_update_job_fields_and_tags(db_path):
    store = _store(db_path)
    job = store.create_job(**_job_payload())

    updated = store.update_job(
        "tenant-1",
        job["job_id"],
        job_function="后端",
        seniority="高级",
        tech_tags=["Python", "FastAPI"],
        status="面试中",
        salary_min=25000,
    )

    assert updated["job_function"] == "后端"
    assert updated["seniority"] == "高级"
    assert updated["tech_tags"] == ["Python", "FastAPI"]
    assert updated["status"] == "interview"  # Bug-12: canonical storage
    assert updated["salary_min"] == 25000


def test_update_rejects_invalid_enum(db_path):
    store = _store(db_path)
    job = store.create_job(**_job_payload())

    with pytest.raises(UserStoreError, match="job_function"):
        store.update_job("tenant-1", job["job_id"], job_function="nope")


def test_update_rejects_invalid_tailor_prefs(db_path):
    store = _store(db_path)
    job = store.create_job(**_job_payload())

    with pytest.raises(UserStoreError, match="tailor_granularity"):
        store.update_job(
            "tenant-1", job["job_id"], tailor_granularity="wild"
        )
    with pytest.raises(UserStoreError, match="tailor_focus"):
        store.update_job("tenant-1", job["job_id"], tailor_focus="wild")


def test_salary_median_helper(db_path):
    store = _store(db_path)
    store.create_job(
        **_job_payload(
            jd_text="A", job_function="后端", salary_min=20000, salary_max=30000
        )
    )
    store.create_job(
        **_job_payload(
            title="Backend 2",
            jd_text="B",
            job_function="后端",
            salary_min=30000,
            salary_max=40000,
        )
    )
    store.create_job(
        **_job_payload(
            title="Frontend",
            jd_text="C",
            job_function="前端",
            salary_min=10000,
            salary_max=20000,
        )
    )
    store.create_job(
        **_job_payload(
            title="No salary",
            jd_text="D",
            job_function="后端",
            salary_min=None,
            salary_max=None,
        )
    )

    assert store.salary_median("tenant-1") == 25000
    assert store.salary_median("tenant-1", job_function="后端") == 25000
    assert store.salary_median("tenant-1", job_function="数据") is None


def test_delete_job(db_path):
    store = _store(db_path)
    job = store.create_job(**_job_payload())

    assert store.delete_job("tenant-1", job["job_id"]) == (True, None)
    assert store.get_job("tenant-1", job["job_id"]) is None
    assert store.delete_job("tenant-1", job["job_id"]) == (False, None)


def test_delete_job_removes_crawl_tasks_and_reports_analysis(db_path):
    store = _store(db_path)
    crawls = CrawlTaskStore(db_path=db_path)
    job = store.create_job(**_job_payload())
    crawl = crawls.create(
        tenant_id="tenant-1",
        job_id=job["job_id"],
        jd_url="https://example.com/jobs/1",
    )
    store.update_job(
        "tenant-1", job["job_id"], workbench_job_id="analysis-123"
    )

    deleted, workbench_job_id = store.delete_job("tenant-1", job["job_id"])
    assert deleted is True
    assert workbench_job_id == "analysis-123"
    assert store.get_job("tenant-1", job["job_id"]) is None
    assert crawls.get(crawl["crawl_id"], "tenant-1") is None


def test_controlled_vocabularies():
    assert "后端" in JOB_FUNCTIONS
    assert "高级" in SENIORITIES


def test_create_job_rejects_empty_text_and_invalid_choices(db_path):
    store = _store(db_path)

    with pytest.raises(UserStoreError, match="Job description text"):
        store.create_job(**_job_payload(jd_text="   "))
    with pytest.raises(UserStoreError, match="job_function"):
        store.create_job(**_job_payload(job_function="unknown"))
    with pytest.raises(UserStoreError, match="seniority"):
        store.create_job(**_job_payload(seniority="unknown"))
    with pytest.raises(UserStoreError, match="status"):
        store.create_job(**_job_payload(status="unknown"))
    with pytest.raises(UserStoreError, match="Final draft"):
        store.create_job(**_job_payload(final_draft="   "))


def test_create_job_sets_final_draft_defaults(db_path):
    store = _store(db_path)

    job = store.create_job(**_job_payload(final_draft="Draft one"))

    assert job["final_draft"] == "Draft one"
    assert job["final_draft_version"] == 1
    assert job["final_draft_updated_at"] > 0


def test_update_job_rejects_invalid_seniority_status_and_empty_text(db_path):
    store = _store(db_path)
    job = store.create_job(**_job_payload())

    with pytest.raises(UserStoreError, match="seniority"):
        store.update_job("tenant-1", job["job_id"], seniority="unknown")
    with pytest.raises(UserStoreError, match="status"):
        store.update_job("tenant-1", job["job_id"], status="unknown")
    with pytest.raises(UserStoreError, match="Final draft"):
        store.update_job("tenant-1", job["job_id"], final_draft="   ")
    with pytest.raises(UserStoreError, match="Job description text"):
        store.update_job("tenant-1", job["job_id"], jd_text="   ")


def test_update_job_persists_full_editable_field_set(db_path):
    store = _store(db_path)
    job = store.create_job(**_job_payload())

    updated = store.update_job(
        "tenant-1",
        job["job_id"],
        title="Senior Backend Engineer",
        jd_text="Python backend with distributed systems.",
        company="Globex",
        location="Shenzhen",
        salary_max=45000,
        salary_currency="CNY",
        source_type="url",
        source_url="https://example.com/job/2",
        final_draft="Draft v2",
        final_draft_updated_at=1234.5,
        final_draft_version=9,
        posting_date="2026-08-03",
    )

    assert updated["title"] == "Senior Backend Engineer"
    assert updated["jd_text"] == "Python backend with distributed systems."
    assert updated["company"] == "Globex"
    assert updated["location"] == "Shenzhen"
    assert updated["salary_max"] == 45000
    assert updated["salary_currency"] == "CNY"
    assert updated["source_type"] == "url"
    assert updated["source_url"] == "https://example.com/job/2"
    assert updated["final_draft"] == "Draft v2"
    assert updated["final_draft_updated_at"] == 1234.5
    assert updated["final_draft_version"] == 9
    assert updated["posting_date"] == "2026-08-03"


def test_update_job_missing_returns_none(db_path):
    store = _store(db_path)

    assert store.update_job("tenant-1", "missing", title="Anything") is None


_LEGACY_SCHEMA = """
CREATE TABLE library_jobs (
    job_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    title TEXT NOT NULL,
    jd_text TEXT NOT NULL,
    company TEXT,
    location TEXT,
    salary_min REAL,
    salary_max REAL,
    salary_currency TEXT NOT NULL DEFAULT 'CNY',
    source_type TEXT NOT NULL DEFAULT 'paste',
    source_url TEXT,
    job_function TEXT,
    seniority TEXT,
    tech_tags TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT '未投递',
    posting_date TEXT,
    workbench_job_id TEXT,
    workbench_resume_id TEXT,
    tailor_granularity TEXT,
    tailor_focus TEXT,
    custom_prompt TEXT,
    dedupe_key TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(tenant_id, dedupe_key)
);
"""


def test_legacy_database_migrates_three_new_columns(db_path):
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_LEGACY_SCHEMA)

    store = _store(db_path)
    job = store.create_job(
        **_job_payload(title="Legacy", jd_text="Legacy JD text")
    )

    assert job["classification_pending"] == 0
    assert job["final_draft"] is None
    assert job["final_draft_updated_at"] is None
    with sqlite3.connect(db_path) as conn:
        columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(library_jobs)"
            ).fetchall()
        }
    assert {
        "classification_pending",
        "final_draft",
        "final_draft_updated_at",
        "final_draft_version",
    } <= columns
