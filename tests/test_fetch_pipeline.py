"""Tests for the Sprint 3 JobFetcherService fetch pipeline."""

from unittest.mock import patch

import pytest

import resualign.api as api_module
from resualign.api.services.fetcher import JobFetcherService
from resualign.crawler import CrawlError
from resualign.job_library import JobLibraryStore
from resualign.workspace import UserStoreError


@pytest.fixture
def store(tmp_path):
    return JobLibraryStore(db_path=tmp_path / "fetch.db")


@pytest.fixture
def service(store):
    # Bind the service to a temp store AND point the package singleton at the
    # same store so _create_job_from_source writes into the temp database.
    saved_jobs = api_module._jobs
    api_module._jobs = store
    yield JobFetcherService(store=store)
    api_module._jobs = saved_jobs


@pytest.fixture(autouse=True)
def no_llm():
    with patch.object(
        api_module, "_settings_vocabulary", return_value=([], [])
    ), patch.object(api_module, "_classify_job", return_value={}):
        yield


def _crawl_ok(text="负责后端服务开发。月薪 25-35K，双休。", city="上海"):
    def _fetch(url, meta=None, **kwargs):
        if meta is not None:
            meta["title"] = "后端开发工程师"
            meta["company"] = "Acme"
            meta["city"] = city
        return text
    return _fetch


def _crawl_error(category, message):
    def _fetch(url, meta=None, **kwargs):
        raise CrawlError(message, category=category, url=url)
    return _fetch


def _created(service, tenant="tenant-1"):
    """Helper to run one successful submit_url and return the result."""
    with patch.object(api_module, "crawl_jd", side_effect=_crawl_ok()):
        return service.submit_url(tenant, "https://example.com/jobs/1")


# -- created / duplicate -----------------------------------------------------


def test_submit_url_creates_job(service, store):
    result = _created(service)
    assert result["status"] == "created"
    assert result["job_id"]

    job = store.get_job("tenant-1", result["job_id"])
    assert job is not None
    assert job["source_type"] == "url"
    assert job["source_url"] == "https://example.com/jobs/1"
    assert job["location"] == "上海"
    assert job["salary_min"] == 25000
    assert job["salary_max"] == 35000
    assert "后端" in job["title"]
    assert store.list_blockers("tenant-1") == []


def test_submit_url_duplicate_returns_existing(service, store):
    first = _created(service)
    with patch.object(api_module, "crawl_jd", side_effect=_crawl_ok()):
        second = service.submit_url("tenant-1", "https://example.com/jobs/1/")
    assert second["status"] == "duplicate"
    assert second["job_id"] == first["job_id"]
    # No blocker is written for a duplicate.
    assert store.list_blockers("tenant-1") == []


# -- invalid / crawl failures ------------------------------------------------


def test_submit_url_invalid_url(service, store):
    result = service.submit_url("tenant-1", "ftp://example.com/jobs/1")
    assert result["status"] == "blocked"
    assert result["category"] == "invalid_url"
    blockers = store.list_blockers("tenant-1", status="pending")
    assert len(blockers) == 1
    assert blockers[0]["category"] == "invalid_url"


def test_submit_url_crawl_login_required(service, store):
    with patch.object(
        api_module,
        "crawl_jd",
        side_effect=_crawl_error("http", "Failed to fetch https://x: HTTP 403"),
    ):
        result = service.submit_url("tenant-1", "https://example.com/jobs/1")
    assert result["status"] == "blocked"
    assert result["category"] == "login_required"
    assert result["blocker_id"]


def test_submit_url_crawl_timeout(service, store):
    with patch.object(
        api_module,
        "crawl_jd",
        side_effect=_crawl_error("fetch", "Request timed out"),
    ):
        result = service.submit_url("tenant-1", "https://example.com/jobs/1")
    assert result["status"] == "blocked"
    assert result["category"] == "timeout"


def test_submit_url_crawl_dns_network_error(service, store):
    with patch.object(
        api_module,
        "crawl_jd",
        side_effect=_crawl_error("dns", "Could not resolve host: x"),
    ):
        result = service.submit_url("tenant-1", "https://example.com/jobs/1")
    assert result["status"] == "blocked"
    assert result["category"] == "network_error"


def test_submit_url_crawl_no_content(service, store):
    with patch.object(
        api_module,
        "crawl_jd",
        side_effect=_crawl_error("empty", "Empty content at https://x"),
    ):
        result = service.submit_url("tenant-1", "https://example.com/jobs/1")
    assert result["status"] == "blocked"
    assert result["category"] == "no_content"


def test_submit_url_crawl_site_error(service, store):
    with patch.object(
        api_module,
        "crawl_jd",
        side_effect=_crawl_error("http", "Failed to fetch https://x: HTTP 500"),
    ):
        result = service.submit_url("tenant-1", "https://example.com/jobs/1")
    assert result["status"] == "blocked"
    assert result["category"] == "site_error"


def test_submit_url_crawl_blocked_by_policy_maps_to_invalid_url(service, store):
    with patch.object(
        api_module,
        "crawl_jd",
        side_effect=_crawl_error(
            "url", "URL points to a private or local network address"
        ),
    ):
        result = service.submit_url("tenant-1", "http://127.0.0.1/jobs/1")
    assert result["status"] == "blocked"
    assert result["category"] == "invalid_url"


def test_submit_url_unexpected_error_maps_to_fetch_error(service, store):
    def _boom(url, meta=None, **kwargs):
        raise RuntimeError("unexpected")

    with patch.object(api_module, "crawl_jd", side_effect=_boom):
        result = service.submit_url("tenant-1", "https://example.com/jobs/1")
    assert result["status"] == "blocked"
    assert result["category"] == "fetch_error"


# -- rule rejection ----------------------------------------------------------


def test_submit_url_rule_rejected_preflight(service, store):
    service.create_rule("tenant-1", "blacklist", "outsource")
    with patch.object(api_module, "crawl_jd", side_effect=_crawl_ok()):
        result = service.submit_url(
            "tenant-1", "https://outsource.example.com/jobs/1"
        )
    assert result["status"] == "rule_rejected"
    assert result["rule_type"] == "blacklist"
    blockers = store.list_blockers("tenant-1", status="pending")
    assert blockers and blockers[0]["category"] == "rule_rejected"
    # The crawl must never have happened: no library job was created.
    assert store.list_jobs("tenant-1") == []


def test_submit_url_rule_rejected_city_after_crawl(service, store):
    service.create_rule("tenant-1", "city_whitelist", "上海")
    with patch.object(api_module, "crawl_jd", side_effect=_crawl_ok(city="北京")):
        result = service.submit_url("tenant-1", "https://example.com/jobs/1")
    assert result["status"] == "rule_rejected"
    assert result["rule_type"] == "city_whitelist"
    assert store.list_jobs("tenant-1") == []


def test_submit_url_rule_rejected_salary_after_crawl(service, store):
    service.create_rule("tenant-1", "min_salary", "30000")
    with patch.object(
        api_module, "crawl_jd", side_effect=_crawl_ok(text="负责开发。月薪 15-20K。")
    ):
        result = service.submit_url("tenant-1", "https://example.com/jobs/1")
    assert result["status"] == "rule_rejected"
    assert result["rule_type"] == "min_salary"
    assert store.list_jobs("tenant-1") == []


def test_submit_url_rule_rejected_blacklist_after_crawl(service, store):
    service.create_rule("tenant-1", "blacklist", "外包")
    with patch.object(
        api_module, "crawl_jd", side_effect=_crawl_ok(text="负责外包项目交付。")
    ):
        result = service.submit_url("tenant-1", "https://example.com/jobs/1")
    assert result["status"] == "rule_rejected"
    assert result["rule_type"] == "blacklist"
    assert store.list_jobs("tenant-1") == []


def test_submit_url_accepts_when_rules_pass(service, store):
    service.create_rule("tenant-1", "city_whitelist", "上海")
    service.create_rule("tenant-1", "min_salary", "20000")
    result = _created(service)
    assert result["status"] == "created"


def test_submit_url_rules_are_tenant_scoped(service, store):
    service.create_rule("tenant-1", "blacklist", "外包")
    with patch.object(
        api_module, "crawl_jd", side_effect=_crawl_ok(text="负责外包项目交付。")
    ):
        result = service.submit_url("tenant-2", "https://example.com/jobs/1")
    assert result["status"] == "created"


# -- blocker resolution ------------------------------------------------------


def test_resolve_blocker_with_text_creates_job(service, store):
    blocker = service.submit_url("tenant-1", "ftp://bad")
    assert blocker["status"] == "blocked"
    result = service.resolve_blocker_with_text(
        "tenant-1", blocker["blocker_id"], "负责后端开发。月薪 20-30K。"
    )
    assert result["blocker"]["status"] == "resolved"
    assert result["blocker"]["job_id"] == result["job"]["job_id"]
    assert store.get_job("tenant-1", result["job"]["job_id"]) is not None


def test_resolve_blocker_requires_text(service, store):
    blocker = service.submit_url("tenant-1", "ftp://bad")
    with pytest.raises(UserStoreError, match="text"):
        service.resolve_blocker_with_text(
            "tenant-1", blocker["blocker_id"], "   "
        )
    assert store.get_blocker("tenant-1", blocker["blocker_id"])["status"] == "pending"


def test_resolve_blocker_missing_returns_none(service):
    assert service.resolve_blocker_with_text("tenant-1", "missing", "text") is None


def test_resolve_blocker_not_pending_raises(service, store):
    blocker = service.submit_url("tenant-1", "ftp://bad")
    service.ignore_blocker("tenant-1", blocker["blocker_id"])
    with pytest.raises(UserStoreError, match="pending"):
        service.resolve_blocker_with_text(
            "tenant-1", blocker["blocker_id"], "负责后端开发"
        )
