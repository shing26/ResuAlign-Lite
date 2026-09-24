"""Tests for the tenant-scoped Job Library store."""

import sqlite3

import pytest

import resualign.job_library as job_library
from resualign.job_library import (
    JOB_FUNCTIONS,
    SENIORITIES,
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


def test_delete_job_reports_analysis_job(db_path):
    store = _store(db_path)
    job = store.create_job(**_job_payload())
    store.update_job(
        "tenant-1", job["job_id"], workbench_job_id="analysis-123"
    )

    deleted, workbench_job_id = store.delete_job("tenant-1", job["job_id"])
    assert deleted is True
    assert workbench_job_id == "analysis-123"
    assert store.get_job("tenant-1", job["job_id"]) is None


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


_PATCH_EXPECTED = {
    "title": "Staff Platform Engineer",
    "jd_text": "Rust platform role with Kubernetes.",
    "company": "Initech",
    "location": "Beijing",
    "salary_min": 31000,
    "salary_max": 49000,
    "salary_currency": "USD",
    "source_type": "url",
    "source_url": "https://example.com/jobs/patch",
    "job_function": JOB_FUNCTIONS[0],
    "seniority": SENIORITIES[0],
    "tech_tags": ["Rust", "Kubernetes"],
    "status": "已投递",
    "classification_pending": 1,
    "final_draft": "Patched final draft",
    "final_draft_updated_at": 4321.5,
    "final_draft_version": 7,
    "posting_date": "2026-09-01",
    "applied_at": "2026-09-02",
    "next_step": "Technical screen",
    "notes": "Recruiter prefers async.",
    "offer_at": "2026-09-10",
    "rejected_at": "2026-09-11",
    "next_step_due_at": "2026-09-08",
    "interview_stage": "onsite",
    "match_stale": 1,
    "jd_profile": {"title": "Platform Engineer", "skills": ["Rust"]},
    "gap_report": {"missing_keywords": ["Kubernetes"]},
    "match_score": 88.5,
    "match_score_detail": {"skill": 90, "experience": 87},
    "match_reason": "Strong overlap on systems work.",
    "match_updated_at": 8765.5,
    "alignment_status": "succeeded",
    "diffs": [{"section": "summary", "proposed": "Patched"}],
    "invalid_diffs": [{"reason": "noop"}],
    "draft": "Draft body",
    "eval_score": {"overall": 0.91},
    "model": "meta/muse-glimmer-30b",
    "prompt_version": "v3",
    "generated_at": 9999.5,
    "workbench_job_id": "wj-patch",
    "workbench_resume_id": "wr-patch",
    "tailor_granularity": "medium",
    "tailor_focus": "skills",
    "custom_prompt": "Keep it concise.",
    "last_alignment_error": "none",
    "application_result": "screen_pass",
    "deadline": "2026-09-30",
}


def test_update_parameter_whitelist_covers_every_buildable_field():
    covered = {
        field
        for field, _column, _converter in job_library._JOB_UPDATE_SIMPLE_FIELDS
    }
    covered.update(
        field
        for field, _column, _converter in job_library._JOB_UPDATE_JSON_FIELDS
    )
    covered.update(
        field for field, _column in job_library._JOB_UPDATE_CLEARABLE_FIELDS
    )
    persisted = set(job_library._JOB_UPDATE_PARAMETERS) - set(
        job_library._JOB_UPDATE_CONSTRAINT_PARAMETERS
    )
    assert set(_PATCH_EXPECTED) == persisted
    assert covered == persisted


def test_update_whitelist_and_expected_payload_are_in_sync(db_path):
    store = _store(db_path)
    job = store.create_job(**_job_payload())

    assert set(job) <= set(job_library._JOB_UPDATE_PARAMETERS) | {
        "job_id",
        "tenant_id",
        "usable_diffs",
        "has_gap",
        "alignment_reason",
        "analysis_ready",
        "status_canonical",
        "status_label",
        "created_at",
        "updated_at",
    }


_PERSISTED_UPDATE_FIELDS = tuple(
    field
    for field in job_library._JOB_UPDATE_PARAMETERS
    if field not in job_library._JOB_UPDATE_CONSTRAINT_PARAMETERS
)


@pytest.mark.parametrize("field", _PERSISTED_UPDATE_FIELDS)
def test_update_job_patches_each_field_independently(db_path, field):
    store = _store(db_path)
    job = store.create_job(**_job_payload())
    baseline = store.get_job("tenant-1", job["job_id"])
    expected = _PATCH_EXPECTED[field]

    updated = store.update_job("tenant-1", job["job_id"], **{field: expected})

    if field == "status":
        assert updated[field] == "applied"
    elif field == "match_stale":
        assert updated[field] is True
    else:
        assert updated[field] == expected
    derived_changes = {
        "updated_at",
        "status_canonical",
        "status_label",
    }
    if field == "status":
        derived_changes |= {"applied_at", "analysis_ready"}
    if field == "gap_report":
        derived_changes |= {"has_gap", "alignment_reason"}
    if field == "alignment_status":
        derived_changes |= {"alignment_reason", "analysis_ready"}
    for other in baseline:
        if other == field or other in derived_changes:
            continue
        assert updated[other] == baseline[other]


@pytest.mark.parametrize("field", _PERSISTED_UPDATE_FIELDS)
def test_update_job_leaves_each_field_untouched_when_none(db_path, field):
    store = _store(db_path)
    job = store.create_job(**_job_payload())
    baseline = store.get_job("tenant-1", job["job_id"])

    updated = store.update_job("tenant-1", job["job_id"], **{field: None})

    assert updated[field] == baseline[field]


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


class TestSourceUrlNormalization:
    """Posting identity often lives in the query or the hash route."""

    def test_keeps_identity_query_and_drops_tracking_noise(self):
        normalize = job_library._normalize_source_url
        assert normalize(
            "https://join.qq.com/post_detail.html?postid=120079"
        ) == "https://join.qq.com/post_detail.html?postid=120079"
        assert normalize(
            "https://join.qq.com/post_detail.html?utm_source=x&postid=120079"
        ) == "https://join.qq.com/post_detail.html?postid=120079"
        # locale/activity noise is dropped, the identity param survives.
        assert normalize(
            "https://aspire.zhiye.com/campus/detail"
            "?jobAdId=2921&activityGuid=abc&ActivityJumpPage=PortalPage"
        ) == "https://aspire.zhiye.com/campus/detail?jobadid=2921"

    def test_keeps_spa_hash_route(self):
        normalize = job_library._normalize_source_url
        assert normalize(
            "https://campus.xunlei.com/campus-recruitment/xunlei/26600"
            "#/job/1c77fe7e-ce43-4b2f-9b9a-1f2e3d4c5b6a"
        ) == (
            "https://campus.xunlei.com/campus-recruitment/xunlei/26600"
            "#/job/1c77fe7e-ce43-4b2f-9b9a-1f2e3d4c5b6a"
        )

    def test_empty_url_stays_empty(self):
        assert job_library._normalize_source_url("") == ""
        assert job_library._normalize_source_url(None) == ""


class TestSalaryTextParsing:
    def test_requires_a_magnitude_unit(self):
        parse = job_library._parse_salary_text
        assert parse("20-30K") == (20000, 30000)
        assert parse("15-25K·15薪") == (15000, 25000)
        assert parse("1.2万-2万") == (12000, 20000)
        assert parse("面议") == (None, None)
        assert parse("200-300元/天") == (None, None)
        assert parse("8000-12000") == (None, None)
        assert parse(None) == (None, None)


def test_two_postings_on_one_host_both_create(db_path):
    store = _store(db_path)
    first = store.create_job(
        **_job_payload(
            title="岗位 A",
            jd_text="岗位 A 的 JD 正文",
            source_type="url",
            source_url="https://join.qq.com/post_detail.html?postid=AAA",
        )
    )
    second = store.create_job(
        **_job_payload(
            title="岗位 B",
            jd_text="岗位 B 的 JD 正文",
            source_type="url",
            source_url="https://join.qq.com/post_detail.html?postid=BBB",
        )
    )
    assert first["job_id"] != second["job_id"]


def test_reconcile_rekeys_legacy_over_stripped_url_rows(db_path):
    store = _store(db_path)
    job = store.create_job(
        **_job_payload(
            source_type="url",
            source_url="https://join.qq.com/post_detail.html?postid=AAA",
        )
    )
    # Simulate the pre-fix key that stripped everything after "?".
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE library_jobs SET dedupe_key = ? WHERE job_id = ?",
            ("url:https://join.qq.com/post_detail.html", job["job_id"]),
        )

    reopened = _store(db_path)
    reopened.list_jobs("tenant-1")  # first query runs the migrations+reconcile
    with sqlite3.connect(db_path) as conn:
        key = conn.execute(
            "SELECT dedupe_key FROM library_jobs WHERE job_id = ?",
            (job["job_id"],),
        ).fetchone()[0]
    assert key == "url:https://join.qq.com/post_detail.html?postid=aaa"

    # The re-keyed row no longer swallows a distinct posting on the host.
    second = reopened.create_job(
        **_job_payload(
            title="岗位 B",
            jd_text="岗位 B 的 JD 正文",
            source_type="url",
            source_url="https://join.qq.com/post_detail.html?postid=BBB",
        )
    )
    assert second["job_id"] != job["job_id"]
