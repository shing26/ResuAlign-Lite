"""Job-table auto-sync: WorkBuddy CSV intake + duplicate-free re-import."""

import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.api.services import job_table as job_table_service
from resualign.api.services.job_table import (
    JobTableError,
    _job_table_dedupe_key,
    _sync_due,
    read_job_table_rows,
)
from resualign.jobs import JobRegistry
from resualign.settings_store import SettingsStore
from resualign.workspace import (
    ApplicationStore,
    JobLibraryStore,
    MasterResumeStore,
    UserStore,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def temp_stores(tmp_path):
    saved = {
        "registry": api_module._registry,
        "users": api_module._users,
        "resumes": getattr(api_module, "_resumes", None),
        "applications": getattr(api_module, "_applications", None),
        "jobs": getattr(api_module, "_jobs", None),
        "personal_mode": api_module._PERSONAL_MODE,
        "payloads": api_module._payloads,
        "import_batches": getattr(api_module, "_import_batches", {}),
        "settings": getattr(api_module, "_settings_store", None),
    }
    db_path = tmp_path / "job-table.db"
    api_module._registry = JobRegistry(db_path=db_path)
    api_module._users = UserStore(db_path=db_path)
    api_module._resumes = MasterResumeStore(db_path=db_path)
    api_module._applications = ApplicationStore(db_path=db_path)
    api_module._jobs = JobLibraryStore(db_path=db_path)
    api_module._settings_store = SettingsStore(db_path=db_path)
    api_module._PERSONAL_MODE = True
    api_module._payloads = {}
    api_module._import_batches = {}
    for limiter in (
        api_module._auth_rate_limiter,
        api_module._analyze_rate_limiter,
        api_module._import_rate_limiter,
    ):
        limiter.reset()
    yield
    api_module._registry = saved["registry"]
    api_module._users = saved["users"]
    api_module._resumes = saved["resumes"]
    api_module._applications = saved["applications"]
    api_module._jobs = saved["jobs"]
    api_module._PERSONAL_MODE = saved["personal_mode"]
    api_module._payloads = saved["payloads"]
    api_module._import_batches = saved["import_batches"]
    api_module._settings_store = saved["settings"]
    for limiter in (
        api_module._auth_rate_limiter,
        api_module._analyze_rate_limiter,
        api_module._import_rate_limiter,
    ):
        limiter.reset()


def _classify(*args, **kwargs):
    return {
        "job_function": "后端",
        "seniority": "高级",
        "tech_tags": ["Python"],
    }


def _wait_import(import_id, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/jobs/import/{import_id}").json()
        if not body["queued"]:
            return body
        time.sleep(0.01)
    raise AssertionError(f"import {import_id} did not finish")


def _workbuddy_csv(tmp_path: Path) -> Path:
    """Write a small WorkBuddy-style table plus its JD markdown folder."""
    jd_dir = tmp_path / "JD库"
    jd_dir.mkdir(parents=True, exist_ok=True)
    (jd_dir / "1-acme-java.md").write_text(
        "Java 开发实习生\n公司：Acme\n地点：深圳\n要求 Spring Boot。",
        encoding="utf-8",
    )
    (jd_dir / "2-beta-fe.md").write_text(
        "前端工程师\n公司：Beta\n地点：上海\n要求 React。",
        encoding="utf-8",
    )
    table = tmp_path / "岗位总表.csv"
    table.write_text(
        "公司,岗位,薪资,地点,投递入口,JD文件\n"
        "Acme,Java 开发实习生,4-6K/月,深圳,,JD库/1-acme-java.md\n"
        "Beta,前端工程师,20-30K,上海,example.com/job/2,JD库/2-beta-fe.md\n",
        encoding="utf-8-sig",
    )
    return table


def _set_job_table(path: Path, jd_dir: Path | None = None, **extra):
    body = {"path": str(path), "auto_sync": False, "preanalyze": False}
    if jd_dir is not None:
        body["jd_dir"] = str(jd_dir)
    body.update(extra)
    return client.put("/api/settings", json={"job_table": body})


# --- dedupe efficiency ------------------------------------------------------


def test_reimport_duplicate_row_never_calls_the_classifier():
    """The second import of an identical batch must not spend an LLM call."""
    csv_text = "title,jd_text,company\nBackend,Python 后端工程师,Acme\n"
    with patch("resualign.api._classify_job", side_effect=_classify):
        first = client.post(
            "/api/jobs/import", json={"csv_text": csv_text}
        ).json()
        assert _wait_import(first["import_id"])["created"] == 1

    def _boom(*args, **kwargs):
        raise AssertionError("duplicate rows must not reach the classifier")

    with patch("resualign.api._classify_job", side_effect=_boom):
        second = client.post(
            "/api/jobs/import", json={"csv_text": csv_text}
        ).json()
        status = _wait_import(second["import_id"])
    assert status["created"] == 0
    assert status["skipped"] == 1
    assert status["errors"] == ["Backend: Duplicate job already exists"]
    assert len(api_module._jobs.list_jobs("local")) == 1


# --- job-table reading ------------------------------------------------------


def test_read_job_table_inlines_jd_body_and_maps_workbuddy_columns(tmp_path):
    table = _workbuddy_csv(tmp_path)
    rows = read_job_table_rows(table, jd_dir=tmp_path / "JD库")
    assert len(rows) == 2
    first = rows[0]
    assert first["title"] == "Java 开发实习生"
    assert first["company"] == "Acme"
    assert first["location"] == "深圳"
    assert (first["salary_min"], first["salary_max"]) == (4000, 6000)
    assert "Spring Boot" in first["jd_text"]
    # Non-URL 投递入口 falls back to the stable job-table identity.
    assert first["source_type"] == "paste"
    assert first["dedupe_key"].startswith("jobtable:")
    second = rows[1]
    assert second["jd_url"] == "https://example.com/job/2"
    assert second["source_type"] == "url"
    assert (second["salary_min"], second["salary_max"]) == (20000, 30000)


def test_job_table_dedupe_key_survives_jd_body_rewrites():
    before = _job_table_dedupe_key(
        company="Acme", title="Java 开发实习生", location="深圳"
    )
    after = _job_table_dedupe_key(
        company="acme ", title=" java 开发实习生", location="深圳"
    )
    assert before == after


def test_read_job_table_rejects_unrecognized_header(tmp_path):
    table = tmp_path / "岗位总表.csv"
    table.write_text("foo,bar\n1,2\n", encoding="utf-8")
    with pytest.raises(JobTableError):
        read_job_table_rows(table, jd_dir=None)


def test_read_job_table_derives_a_missing_title_from_the_jd(tmp_path):
    jd_dir = tmp_path / "JD库"
    jd_dir.mkdir()
    (jd_dir / "1-acme.md").write_text(
        "资深后端工程师\n公司：Acme\n要求 Python。", encoding="utf-8"
    )
    table = tmp_path / "岗位总表.csv"
    table.write_text(
        "公司,地点,JD文件\nAcme,深圳,JD库/1-acme.md\n", encoding="utf-8-sig"
    )
    rows = read_job_table_rows(table, jd_dir=jd_dir)
    assert rows[0]["title"] == "资深后端工程师"


def test_read_job_table_counts_rows_without_a_jd_body(tmp_path):
    table = _workbuddy_csv(tmp_path)
    with table.open("a", encoding="utf-8") as handle:
        # WorkBuddy adds the row first and writes the JD markdown later.
        handle.write("Gamma,后端工程师,10-20K,北京,,JD库/3-gamma.md\n")
    stats: dict[str, int] = {}
    rows = read_job_table_rows(table, jd_dir=tmp_path / "JD库", stats=stats)
    assert len(rows) == 2
    assert stats == {"total_rows": 3, "importable_rows": 2, "missing_jd": 1}


def test_sync_job_table_reports_rows_missing_a_jd_body(tmp_path):
    table = _workbuddy_csv(tmp_path)
    with table.open("a", encoding="utf-8") as handle:
        handle.write("Gamma,后端工程师,10-20K,北京,,JD库/3-gamma.md\n")
    assert _set_job_table(table, tmp_path / "JD库").status_code == 200
    with patch("resualign.api._classify_job", side_effect=_classify):
        start = client.post("/api/jobs/job-table/sync").json()
        _wait_import(start["import_id"])
    last = client.get("/api/jobs/job-table").json()["job_table"]["last_result"]
    assert last["status"] == "queued"
    assert "缺少 JD 正文" in last["detail"]


# --- job-table API ----------------------------------------------------------


def test_settings_reject_auto_sync_without_path(tmp_path):
    r = client.put(
        "/api/settings", json={"job_table": {"auto_sync": True, "path": None}}
    )
    assert r.status_code == 422


def test_put_settings_persists_job_table_config(tmp_path):
    table = _workbuddy_csv(tmp_path)
    r = _set_job_table(table, tmp_path / "JD库", interval_minutes=30)
    assert r.status_code == 200
    job_table = r.json()["job_table"]
    assert job_table["path"] == str(table)
    assert job_table["interval_minutes"] == 30
    assert client.get("/api/jobs/job-table").json()["job_table"][
        "jd_dir"
    ] == str(tmp_path / "JD库")


def test_sync_job_table_imports_then_reports_a_noop_on_second_run(tmp_path):
    table = _workbuddy_csv(tmp_path)
    assert _set_job_table(table, tmp_path / "JD库").status_code == 200
    with patch("resualign.api._classify_job", side_effect=_classify):
        first = client.post("/api/jobs/job-table/sync").json()
        assert first["queued"] is True
        status = _wait_import(first["import_id"])
    assert (status["created"], status["skipped"]) == (2, 0)

    def _boom(*args, **kwargs):
        raise AssertionError("re-sync of an unchanged table must not call the LLM")

    with patch("resualign.api._classify_job", side_effect=_boom):
        second = client.post("/api/jobs/job-table/sync").json()
    assert second["queued"] is False
    assert second["already_present"] == 2
    assert "已在库中" in second["errors"][0]
    assert len(api_module._jobs.list_jobs("local")) == 2


def test_sync_recognizes_rows_imported_before_the_stable_identity(tmp_path):
    """A pre-ADR-0054 row is keyed by JD text hash; the sync must still skip it."""
    table = _workbuddy_csv(tmp_path)
    jd_text = (tmp_path / "JD库" / "1-acme-java.md").read_text(encoding="utf-8")
    api_module._jobs.create_job(
        tenant_id="local",
        title="Java 开发实习生",
        jd_text=jd_text,
        company="Acme",
        location="深圳",
        source_type="paste",
    )
    assert _set_job_table(table, tmp_path / "JD库").status_code == 200
    with patch("resualign.api._classify_job", side_effect=_classify):
        body = client.post("/api/jobs/job-table/sync").json()
        _wait_import(body["import_id"])
    assert body["already_present"] == 1
    assert body["total"] == 1  # only the URL-identified Beta row is queued


def test_sync_recognizes_a_rewritten_jd_body_by_identity(tmp_path):
    """A pre-ADR-0054 row whose JD was rewritten still must not duplicate."""
    table = _workbuddy_csv(tmp_path)
    # The library holds the older body; WorkBuddy has since rewritten the file.
    api_module._jobs.create_job(
        tenant_id="local",
        title="Java 开发实习生",
        jd_text="Java 开发实习生\n公司：Acme\n地点：深圳\n旧版要求 JDBC。",
        company="Acme",
        location="深圳",
        source_type="paste",
    )
    assert _set_job_table(table, tmp_path / "JD库").status_code == 200
    with patch("resualign.api._classify_job", side_effect=_classify):
        body = client.post("/api/jobs/job-table/sync").json()
        _wait_import(body["import_id"])
    # 2 of 2 non-URL/identity rows recognized: the Acme row by identity, and
    # the Beta URL row is genuinely new here.
    assert body["already_present"] == 1
    assert body["total"] == 1
    titles = [j["title"] for j in api_module._jobs.list_jobs("local")]
    assert titles.count("Java 开发实习生") == 1


def test_sync_job_table_reports_missing_file(tmp_path):
    missing = tmp_path / "nope.csv"
    assert _set_job_table(missing).status_code == 200
    r = client.post("/api/jobs/job-table/sync")
    assert r.status_code == 422
    assert "不存在" in r.json()["detail"]
    last = client.get("/api/jobs/job-table").json()["job_table"]
    assert last["last_result"]["status"] == "error"


def test_sync_job_table_rejects_non_csv_suffix(tmp_path):
    other = tmp_path / "notes.md"
    other.write_text("x", encoding="utf-8")
    assert _set_job_table(other).status_code == 200
    r = client.post("/api/jobs/job-table/sync")
    assert r.status_code == 422
    assert ".csv" in r.json()["detail"]


def test_sync_job_table_requires_configured_path():
    r = client.post("/api/jobs/job-table/sync")
    assert r.status_code == 422
    assert "岗位表路径" in r.json()["detail"]


# --- schedule ---------------------------------------------------------------


def test_sync_due_respects_interval_and_last_run():
    assert _sync_due({}, now=1000.0) is True
    assert (
        _sync_due(
            {"interval_minutes": 30, "last_sync_at": 1000.0}, now=1000.0
        )
        is False
    )
    assert (
        _sync_due(
            {"interval_minutes": 30, "last_sync_at": 1000.0}, now=2800.0
        )
        is True
    )


def test_sync_once_only_runs_due_tenants(tmp_path):
    table = _workbuddy_csv(tmp_path)
    api_module._settings_store.update_settings(
        "local",
        {
            "job_table": {
                "path": str(table),
                "auto_sync": True,
                "preanalyze": False,
                "last_sync_at": time.time(),
            }
        },
    )
    with patch.object(
        job_table_service, "sync_job_table", side_effect=AssertionError
    ):
        assert job_table_service.sync_once() == 0
