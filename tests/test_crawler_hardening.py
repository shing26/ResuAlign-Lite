import json

import httpx
import pytest

from resualign import crawler
from resualign.crawler import (
    DEFAULT_UA_POOL,
    HEADERS,
    CrawlError,
    _clean_company_name,
    _generic_job_text,
    _HostRateLimiter,
    _json_script_text,
    _meta_from_soup,
    crawl_jd,
)


class _FakeResponse:
    def __init__(
        self,
        content=b"",
        status_code=200,
        headers=None,
        encoding=None,
        charset_encoding=None,
    ):
        if isinstance(content, str):
            content = content.encode("utf-8")
        self.content = content
        self.status_code = status_code
        self.headers = headers or {}
        self.encoding = encoding
        self.charset_encoding = charset_encoding

    def iter_bytes(self):
        yield self.content


class _FlakyReadResponse(_FakeResponse):
    def __init__(self, failures, content):
        super().__init__(content)
        self.failures = failures

    def iter_bytes(self):
        if self.failures > 0:
            self.failures -= 1
            raise httpx.ReadError("read failed")
        yield self.content


class _FakeStream:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self.response

    def __exit__(self, *args):
        return False


class _RecordingLimiter:
    def __init__(self):
        self.waits = []

    def wait(self, host):
        self.waits.append(host)


def _response(text, status_code=200):
    return _FakeResponse(text.encode("utf-8"), status_code=status_code)


def _patch_fetch(monkeypatch, response):
    monkeypatch.setattr(
        "resualign.crawler._fetch_stream",
        lambda *args, **kwargs: _FakeStream(response),
    )


def test_meta_from_soup_cleans_company_and_reads_json_ld():
    from bs4 import BeautifulSoup

    html = """
    <html>
      <head>
        <meta property="og:site_name" content="星河科技招聘官网">
        <title>后端工程师 - 星河科技</title>
      </head>
      <body>
        <script type="application/ld+json">
        {
          "@type": "JobPosting",
          "name": "高级后端工程师",
          "hiringOrganization": {"name": "星河科技"},
          "jobLocation": {
            "address": {"addressLocality": "上海"}
          }
        }
        </script>
      </body>
    </html>
    """
    meta = _meta_from_soup(BeautifulSoup(html, "html.parser"))
    assert meta["title"] == "高级后端工程师"
    assert meta["company"] == "星河科技"
    assert meta["city"] == "上海"


def test_meta_company_fallback_uses_cleaned_site_name():
    from bs4 import BeautifulSoup

    html = """
    <html><head>
      <meta property="og:site_name" content="云帆数据招聘">
      <title>数据平台工程师 | 云帆数据招聘</title>
    </head><body><div class="job-description">岗位职责：负责数据平台建设</div></body></html>
    """
    meta = _meta_from_soup(BeautifulSoup(html, "html.parser"))
    assert meta["company"] == "云帆数据"
    assert meta["title"] == "数据平台工程师"


def test_clean_company_name():
    assert _clean_company_name("Acme 招聘官网") == "Acme"
    assert _clean_company_name("Acme Careers") == "Acme"
    assert _clean_company_name("  ") is None


def test_json_script_text_extracts_ssr_jd():
    from bs4 import BeautifulSoup

    payload = {
        "job": {
            "title": "后端开发",
            "description": (
                "岗位职责：负责高并发服务设计与开发，"
                "深入使用 Python 与 FastAPI 构建稳定可靠的后端系统。"
            ),
        },
        "meta": {"site": "example"},
    }
    html = (
        "<html><body>"
        "<script>window.__INITIAL_STATE__ = "
        + json.dumps(payload, ensure_ascii=False)
        + ";</script>"
        "</body></html>"
    )
    text = _json_script_text(BeautifulSoup(html, "html.parser"))
    assert "岗位职责" in text
    assert "FastAPI" in text


def test_generic_job_text_falls_back_to_ssr_json():
    from bs4 import BeautifulSoup

    payload = {
        "position": {
            "requirement": (
                "任职要求：熟悉 Redis 缓存与高并发场景，"
                "具备三年以上后端研发经验，能够独立完成模块设计。"
            )
        }
    }
    html = (
        "<html><body>"
        "<script>window.__NUXT__ = "
        + json.dumps(payload, ensure_ascii=False)
        + ";</script>"
        "</body></html>"
    )
    text = _generic_job_text(BeautifulSoup(html, "html.parser"))
    assert "任职要求" in text
    assert "Redis" in text


@pytest.fixture(autouse=True)
def _isolated_crawl_environment(monkeypatch):
    monkeypatch.setattr(
        "resualign.crawler._resolve_public_host", lambda host: None
    )
    monkeypatch.setattr(
        "resualign.crawler._crawl_rate_limiter", _RecordingLimiter()
    )


def test_host_rate_limiter_spaces_calls_per_host(monkeypatch):
    sleeps = []
    monkeypatch.setattr(crawler.time, "sleep", sleeps.append)

    limiter = _HostRateLimiter(0.05)
    limiter.wait("example.com")
    limiter.wait("example.com")
    limiter.wait("other.example")

    assert len(sleeps) == 1
    assert sleeps[0] >= 0.049


def test_crawl_min_interval_env_controls_throttle(monkeypatch):
    monkeypatch.setenv("RESUALIGN_CRAWL_MIN_INTERVAL", "0.01")
    monkeypatch.setattr(
        "resualign.crawler._crawl_rate_limiter", _HostRateLimiter(0)
    )
    sleeps = []
    monkeypatch.setattr(crawler.time, "sleep", sleeps.append)

    crawler._throttle("https://example.com/job/1")
    crawler._throttle("https://example.com/job/2")

    assert len(sleeps) == 1
    assert sleeps[0] >= 0.009


def test_crawl_jd_throttles_every_redirect_hop(monkeypatch):
    responses = [
        _FakeResponse("", status_code=302, headers={"location": "/final"}),
        _response("<html><body><p>Final JD</p></body></html>"),
    ]

    def fake_stream(url, **kwargs):
        return _FakeStream(responses.pop(0))

    monkeypatch.setattr("resualign.crawler._fetch_stream", fake_stream)

    text = crawl_jd("https://example.com/job/start")

    assert text == "Final JD"
    assert crawler._crawl_rate_limiter.waits == [
        "example.com",
        "example.com",
    ]


def test_transient_connect_error_retries_with_backoff(monkeypatch):
    calls = []
    sleeps = []
    monkeypatch.setattr(crawler.time, "sleep", sleeps.append)
    monkeypatch.setattr(
        crawler.random, "uniform", lambda low, high: (low + high) / 2
    )

    def flaky_stream(url, **kwargs):
        calls.append(url)
        if len(calls) < 3:
            raise httpx.ConnectError("connection refused")
        return _FakeStream(
            _response("<html><body><p>Recovered JD</p></body></html>")
        )

    monkeypatch.setattr("resualign.crawler._fetch_stream", flaky_stream)

    text = crawl_jd("https://example.com/job")

    assert text == "Recovered JD"
    assert len(calls) == 3
    assert len(sleeps) == 2
    assert sleeps[1] > sleeps[0]


def test_transient_read_error_retries(monkeypatch):
    calls = []
    sleeps = []
    monkeypatch.setattr(crawler.time, "sleep", sleeps.append)

    response = _FlakyReadResponse(failures=2, content="<p>Read JD</p>")

    def fake_stream(url, **kwargs):
        calls.append(url)
        return _FakeStream(response)

    monkeypatch.setattr("resualign.crawler._fetch_stream", fake_stream)

    text = crawl_jd("https://example.com/job")

    assert "Read JD" in text
    assert len(calls) == 3
    assert len(sleeps) == 2


def test_http_4xx_is_not_retried(monkeypatch):
    calls = []

    def fake_stream(url, **kwargs):
        calls.append(url)
        return _FakeStream(_response("Not Found", status_code=404))

    monkeypatch.setattr("resualign.crawler._fetch_stream", fake_stream)

    with pytest.raises(CrawlError, match="HTTP 404"):
        crawl_jd("https://example.com/missing")

    assert len(calls) == 1


def test_url_validation_errors_do_not_fetch(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "resualign.crawler._fetch_stream",
        lambda *args, **kwargs: calls.append(args) or _FakeStream(
            _response("<p>unused</p>")
        ),
    )

    with pytest.raises(CrawlError, match="credentials"):
        crawl_jd("https://user:pass@example.com/job")
    with pytest.raises(CrawlError, match="port"):
        crawl_jd("http://example.com:8080/job")
    with pytest.raises(CrawlError, match="scheme"):
        crawl_jd("ftp://example.com/job")

    assert calls == []


def test_proxy_skips_direct_ip_pinning(monkeypatch):
    monkeypatch.setenv(
        "RESUALIGN_CRAWL_PROXY", "http://proxy.internal:8080"
    )
    monkeypatch.setattr(
        "resualign.crawler._resolve_public_host",
        lambda host: pytest.fail("pinning should be skipped with a proxy"),
    )
    captured = []

    def fake_httpx_stream(method, url, **kwargs):
        captured.append(kwargs)
        return _FakeStream(_response("<html><body><p>Proxy JD</p></body></html>"))

    monkeypatch.setattr("resualign.crawler.httpx.stream", fake_httpx_stream)

    text = crawl_jd("https://example.com/job")

    assert "Proxy JD" in text
    assert captured[0]["proxy"] == "http://proxy.internal:8080"


def test_playwright_fallback_used_for_dynamic_http_error(monkeypatch):
    monkeypatch.setenv("RESUALIGN_CRAWL_PLAYWRIGHT", "1")
    _patch_fetch(monkeypatch, _response("Blocked", status_code=403))

    def fake_playwright(url, timeout=30, request_id=None):
        return "<html><body><p>Rendered LinkedIn JD</p></body></html>"

    monkeypatch.setattr(
        "resualign.crawler._playwright_fetch_html", fake_playwright
    )

    text = crawl_jd("https://www.linkedin.com/jobs/view/123")

    assert "Rendered LinkedIn JD" in text


def test_playwright_fallback_unavailable_preserves_static_error(monkeypatch):
    monkeypatch.setenv("RESUALIGN_CRAWL_PLAYWRIGHT", "1")
    _patch_fetch(monkeypatch, _response("Blocked", status_code=403))
    monkeypatch.setattr(
        "resualign.crawler._playwright_fetch_html", lambda *args, **kwargs: None
    )

    with pytest.raises(CrawlError) as exc_info:
        crawl_jd("https://www.linkedin.com/jobs/view/123")

    assert exc_info.value.category == "http"


def test_playwright_fallback_does_not_run_for_unknown_site(monkeypatch):
    monkeypatch.setenv("RESUALIGN_CRAWL_PLAYWRIGHT", "1")
    _patch_fetch(monkeypatch, _response("Blocked", status_code=403))

    with pytest.raises(CrawlError):
        crawl_jd("https://example.com/job")

    assert not hasattr(crawler, "_playwright_calls")


def test_ua_pool_from_env_rotates_across_redirects(monkeypatch):
    monkeypatch.setenv(
        "RESUALIGN_CRAWL_UA_POOL", json.dumps(["UA-One", "UA-Two"])
    )
    captured = []
    responses = [
        _FakeResponse("", status_code=302, headers={"location": "/final"}),
        _response("<html><body><p>Rotated JD</p></body></html>"),
    ]

    def fake_stream(url, **kwargs):
        captured.append(kwargs.get("headers", {}).get("User-Agent"))
        return _FakeStream(responses.pop(0))

    monkeypatch.setattr("resualign.crawler._fetch_stream", fake_stream)

    text = crawl_jd("https://example.com/job/start")

    assert "Rotated JD" in text
    assert captured == ["UA-One", "UA-Two"]


def test_default_ua_pool_is_seeded_from_base_headers():
    assert DEFAULT_UA_POOL[0] == HEADERS["User-Agent"]
