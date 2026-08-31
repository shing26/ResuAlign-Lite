"""A4/A3: versioned migrations converge on _SqliteStore; JobRegistry inherits."""

from __future__ import annotations

import sqlite3

from resualign.job_library import JobLibraryStore
from resualign.jobs import JobRegistry
from resualign.settings_store import SettingsStore
from resualign.store_base import _SqliteStore
from resualign.workspace import MasterResumeStore

_LEGACY_LIBRARY_SCHEMA = """
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
    dedupe_key TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(tenant_id, dedupe_key)
);
"""


def _migrated_versions(store) -> set[int]:
    with store._connect() as conn:
        return {
            row["version"]
            for row in conn.execute("SELECT version FROM schema_migrations")
        }


def test_legacy_shared_journal_is_rebuilt_per_store(tmp_path):
    """A legacy journal (single shared version key) must not suppress
    another store's migrations that happen to use the same version numbers.

    Regression: settings versions 1..3 were skipped because JobLibrary's
    1..25 already occupied the shared journal, so llm_json never got added
    to existing databases.
    """
    db = tmp_path / "legacy-journal.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at REAL NOT NULL
        );
        CREATE TABLE user_settings (
            tenant_id TEXT PRIMARY KEY,
            salary_reference_json TEXT NOT NULL DEFAULT '[]',
            appraisal_weights_json TEXT NOT NULL DEFAULT '{}',
            classification_vocabulary_json TEXT NOT NULL DEFAULT '{}',
            updated_at REAL NOT NULL
        );
        INSERT INTO schema_migrations (version, applied_at)
        VALUES (1, 1.0), (2, 1.0), (3, 1.0);
        INSERT INTO user_settings (tenant_id, updated_at) VALUES ('t1', 1.0);
        """
    )
    conn.commit()
    conn.close()

    store = SettingsStore(db_path=db)
    settings = store.get_settings("t1")
    assert settings["llm"] == {
        "provider": None,
        "model": None,
        "api_key": None,
        "base_url": None,
    }

    with store._connect() as conn:
        columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(schema_migrations)"
            ).fetchall()
        }
        assert "store" in columns
        rows = {
            (row["store"], row["version"])
            for row in conn.execute(
                "SELECT store, version FROM schema_migrations"
            ).fetchall()
        }
    assert ("SettingsStore", 1) in rows
    assert ("SettingsStore", 2) in rows
    assert ("SettingsStore", 3) in rows


def test_job_library_migrates_legacy_db_and_keeps_data(tmp_path):
    db = tmp_path / "legacy-library.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(_LEGACY_LIBRARY_SCHEMA)
    conn.execute(
        "INSERT INTO library_jobs (job_id, tenant_id, title, jd_text, "
        "dedupe_key, created_at, updated_at) "
        "VALUES ('j1', 't1', 'Legacy Backend', 'Python backend', "
        "'text:legacy', 1.0, 1.0)"
    )
    conn.commit()
    conn.close()

    store = JobLibraryStore(db_path=db)
    job = store.get_job("t1", "j1")

    # Data preserved.
    assert job["title"] == "Legacy Backend"
    assert job["jd_text"] == "Python backend"
    # Sprint 3 automation rules live in the same DB and migrate too.
    rule = store.create_rule("t1", "blacklist", "外包")
    assert store.get_rule("t1", rule["rule_id"]) is not None
    # Missing columns added by versioned migrations.
    assert job["alignment_status"] == "idle"
    assert job["classification_pending"] == 0
    assert job["diffs"] == []
    assert job["final_draft_version"] == 0
    assert job["applied_at"] is None
    assert job["next_step_due_at"] is None
    assert job["interview_stage"] is None
    # Every historical ALTER recorded exactly once. De-bloat removed the
    # blocker_queue (29), reminder/refresh (31-34, 36, 40, 41) migrations;
    # the surviving set is 1..28 plus {30, 35, 37, 38, 39, 42} (42: last_alignment_error, Phase 3)
    # {43} (alignment_metrics + application_result, quality attribution) and
    # {44} (deadline) follow.
    assert _migrated_versions(store) == set(range(1, 29)) | {30, 35, 37, 38, 39, 42, 43, 44}


def test_upgrade_keeps_historical_alignment_artifacts(tmp_path):
    """MVP-11: upgrading an old schema preserves diffs, drafts, final drafts,
    match scores and application snapshots through the versioned migrations."""
    db = tmp_path / "upgrade-artifacts.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
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
            dedupe_key TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            diffs_json TEXT NOT NULL DEFAULT '[]',
            invalid_diffs_json TEXT NOT NULL DEFAULT '[]',
            draft TEXT,
            final_draft TEXT,
            final_draft_updated_at REAL,
            final_draft_version INTEGER NOT NULL DEFAULT 0,
            match_score REAL,
            prompt_version TEXT,
            generated_at REAL
        );
        CREATE TABLE application_snapshots (
            snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL,
            job_id TEXT NOT NULL,
            version_index INTEGER NOT NULL,
            final_draft TEXT NOT NULL,
            match_score REAL,
            master_resume_id TEXT,
            applied_at TEXT NOT NULL,
            created_at REAL NOT NULL,
            UNIQUE(tenant_id, job_id, version_index)
        );
        INSERT INTO library_jobs (
            job_id, tenant_id, title, jd_text, dedupe_key, created_at,
            updated_at, diffs_json, invalid_diffs_json, draft, final_draft,
            final_draft_updated_at, final_draft_version, match_score,
            prompt_version, generated_at
        ) VALUES (
            'j1', 't1', 'Backend', 'Python backend', 'text:legacy', 1.0, 2.0,
            '[{"diff_id":"d1","provenance_state":"accepted"}]',
            '[{"diff_id":"bad"}]',
            '# Draft content',
            '# Final content',
            3.0, 2, 81.5,
            'engine.v1', 4.0
        );
        INSERT INTO application_snapshots (
            tenant_id, job_id, version_index, final_draft, match_score,
            applied_at, created_at
        ) VALUES (
            't1', 'j1', 1, '# Snapshot content', 80.0, '2026-08-10', 5.0
        );
        """
    )
    conn.commit()
    conn.close()

    store = JobLibraryStore(db_path=db)
    job = store.get_job("t1", "j1")
    assert job["title"] == "Backend"
    assert job["draft"] == "# Draft content"
    assert job["final_draft"] == "# Final content"
    assert job["final_draft_version"] == 2
    assert job["match_score"] == 81.5
    assert job["prompt_version"] == "engine.v1"
    assert job["diffs"][0]["diff_id"] == "d1"
    assert job["invalid_diffs"][0]["diff_id"] == "bad"

    with store._connect() as conn:
        snapshot = conn.execute(
            "SELECT final_draft, match_score, version_index "
            "FROM application_snapshots WHERE job_id = 'j1'"
        ).fetchone()
        rows = {
            (row["store"], row["version"])
            for row in conn.execute(
                "SELECT store, version FROM schema_migrations"
            )
        }
    assert snapshot["final_draft"] == "# Snapshot content"
    assert snapshot["match_score"] == 80.0
    assert ("JobLibraryStore", 39) in rows
    assert ("JobLibraryStore", 1) in rows


def test_fresh_job_library_db_records_migrations_as_applied(tmp_path):
    store = JobLibraryStore(db_path=tmp_path / "fresh-library.db")
    job = store.create_job(
        tenant_id="t1", title="Fresh", jd_text="Python backend."
    )
    assert job["alignment_status"] == "idle"
    assert _migrated_versions(store) == set(range(1, 29)) | {30, 35, 37, 38, 39, 42, 43, 44}


def test_migrated_legacy_db_supports_workbench_columns(tmp_path):
    db = tmp_path / "legacy-library-2.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(_LEGACY_LIBRARY_SCHEMA)
    conn.execute(
        "INSERT INTO library_jobs (job_id, tenant_id, title, jd_text, "
        "dedupe_key, created_at, updated_at) "
        "VALUES ('j1', 't1', 'Legacy', 'JD text', 'text:2', 1.0, 1.0)"
    )
    conn.commit()
    conn.close()

    store = JobLibraryStore(db_path=db)
    updated = store.update_job(
        "t1",
        "j1",
        workbench_job_id="reg-1",
        alignment_status="running",
        custom_prompt="focus on metrics",
    )
    assert updated["workbench_job_id"] == "reg-1"
    assert updated["alignment_status"] == "running"
    saved = store.save_alignment("t1", "j1", match_score=88)
    assert saved["match_score"] == 88
    assert saved["alignment_status"] == "succeeded"


def test_settings_store_migrates_legacy_db(tmp_path):
    db = tmp_path / "legacy-settings.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE user_settings (
            tenant_id TEXT PRIMARY KEY,
            salary_reference_json TEXT NOT NULL DEFAULT '[]',
            appraisal_weights_json TEXT NOT NULL DEFAULT '{}',
            classification_vocabulary_json TEXT NOT NULL DEFAULT '{}',
            updated_at REAL NOT NULL
        );
        INSERT INTO user_settings (tenant_id, updated_at) VALUES ('t1', 1.0);
        """
    )
    conn.commit()
    conn.close()

    store = SettingsStore(db_path=db)
    settings = store.get_settings("t1")
    assert settings["llm_provider"] is None
    assert settings["llm_model"] is None
    assert settings["eval_default"] is False
    assert settings["llm"] == {
        "provider": None,
        "model": None,
        "api_key": None,
        "base_url": None,
    }

    updated = store.update_settings(
        "t1", {"llm_provider": "deepseek", "llm_model": "deepseek-chat"}
    )
    assert updated["llm_provider"] == "deepseek"
    assert updated["llm_model"] == "deepseek-chat"
    assert updated["llm"]["provider"] == "deepseek"
    assert updated["llm"]["model"] == "deepseek-chat"
    assert _migrated_versions(store) == {1, 2, 3, 4, 5, 6, 7, 8, 9, 10}


def test_settings_store_backfills_llm_from_legacy_columns(tmp_path):
    """Rows written before the llm_json column still surface as llm dict."""
    db = tmp_path / "legacy-llm-columns.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE user_settings (
            tenant_id TEXT PRIMARY KEY,
            salary_reference_json TEXT NOT NULL DEFAULT '[]',
            appraisal_weights_json TEXT NOT NULL DEFAULT '{}',
            classification_vocabulary_json TEXT NOT NULL DEFAULT '{}',
            llm_provider TEXT,
            llm_model TEXT,
            updated_at REAL NOT NULL
        );
        INSERT INTO user_settings (
            tenant_id, llm_provider, llm_model, updated_at
        ) VALUES ('t1', 'openrouter', 'old-model', 1.0);
        """
    )
    conn.commit()
    conn.close()

    store = SettingsStore(db_path=db)
    settings = store.get_settings("t1")
    assert settings["llm_provider"] == "openrouter"
    assert settings["llm_model"] == "old-model"
    assert settings["llm"]["provider"] == "openrouter"
    assert settings["llm"]["model"] == "old-model"
    assert settings["llm"]["api_key"] is None


def test_master_resume_store_migrates_legacy_db(tmp_path):
    db = tmp_path / "legacy-resume.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE master_resumes (
            resume_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            title TEXT NOT NULL,
            current_version INTEGER NOT NULL DEFAULT 1,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE TABLE resume_versions (
            version_id TEXT PRIMARY KEY,
            resume_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_at REAL NOT NULL,
            UNIQUE(resume_id, version)
        );
        INSERT INTO master_resumes (resume_id, tenant_id, title,
            current_version, created_at, updated_at)
        VALUES ('r1', 't1', 'Legacy Resume', 1, 1.0, 1.0);
        INSERT INTO resume_versions (version_id, resume_id, tenant_id,
            version, content, created_at)
        VALUES ('v1', 'r1', 't1', 1, 'Python developer.', 1.0);
        """
    )
    conn.commit()
    conn.close()

    store = MasterResumeStore(db_path=db)
    resume = store.get_master_resume("t1", "r1")
    assert resume["title"] == "Legacy Resume"
    assert resume["content"] == "Python developer."
    assert resume["latest_diagnosis_job_id"] is None

    store.set_latest_diagnosis_job("t1", "r1", "job-1")
    assert (
        store.get_master_resume("t1", "r1")["latest_diagnosis_job_id"]
        == "job-1"
    )
    assert _migrated_versions(store) == {1, 2, 3}


def test_job_registry_inherits_shared_store(tmp_path):
    registry = JobRegistry(db_path=tmp_path / "registry.db")
    assert isinstance(registry, _SqliteStore)

    job = registry.create({"resume_text": "resume"}, object())
    registry.succeed(job.job_id, {"score": 5})

    with registry._connect() as conn:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        versions = {
            row["version"]
            for row in conn.execute("SELECT version FROM schema_migrations")
        }
    assert {"jobs", "job_payloads", "schema_migrations"} <= tables
    assert versions == {1}
    assert registry.get(job.job_id).status == "succeeded"


def test_job_registry_memory_mode_inherits_connect(tmp_path):
    registry = JobRegistry(db_path=":memory:")
    job = registry.create({"resume_text": "resume"}, object())
    assert registry.get(job.job_id).status == "queued"
    registry.succeed(job.job_id, {"score": 1})
    assert registry.get(job.job_id).status == "succeeded"
