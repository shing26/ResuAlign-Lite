from pathlib import Path

import httpx
import pytest

from resualign.crawler import (
    CrawlError,
    _decode_content,
    _fetch_stream,
    _merge_cookies,
    _resolve_public_host,
    crawl_jd,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class _FakeResponse:
    """Minimal httpx-like response backed by in-memory bytes."""

    def __init__(
        self,
        content=b"",
        status_code=200,
        encoding=None,
        charset_encoding=None,
        chunk_size=None,
        headers=None,
    ):
        if isinstance(content, str):
            content = content.encode("utf-8")
        self.content = content
        self.status_code = status_code
        self.encoding = encoding
        self.charset_encoding = charset_encoding
        self._chunk_size = chunk_size
        self.headers = headers or {}

    def iter_bytes(self):
        if self._chunk_size is None:
            yield self.content
            return
        for start in range(0, len(self.content), self._chunk_size):
            yield self.content[start:start + self._chunk_size]


class _FakeStream:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self.response

    def __exit__(self, *args):
        return False


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch):
    """Skip real DNS lookups; SSRF DNS checks are tested separately."""
    monkeypatch.setattr(
        "resualign.crawler._resolve_public_host", lambda host: None
    )


def _patch_fetch(monkeypatch, response):
    monkeypatch.setattr(
        "resualign.crawler._fetch_stream",
        lambda *args, **kwargs: _FakeStream(response),
    )


def _response(text, status_code=200):
    return _FakeResponse(text.encode("utf-8"), status_code=status_code)


def test_crawl_jd_linkedin_job_handler(monkeypatch):
    _patch_fetch(monkeypatch, _response(_fixture("linkedin_job.html")))

    text = crawl_jd("https://www.linkedin.com/jobs/view/123")

    assert "Lead design and delivery of the payments platform." in text
    assert "Requirements include Python, FastAPI, and AWS." in text
    assert "Own end-to-end service ownership." in text
    assert "Feed" not in text
    assert "Related jobs" not in text
    assert "Copyright Acme" not in text


def test_crawl_jd_zhipin_job_detail_handler(monkeypatch):
    _patch_fetch(monkeypatch, _response(_fixture("zhipin_job_detail.html")))

    text = crawl_jd("https://www.zhipin.com/job_detail/abc123.html")

    assert "Build scalable backend services for BOSS Zhipin." in text
    assert "Work with Python, Go, and distributed systems." in text
    assert "Backend Engineer at BOSS Zhipin" not in text
    assert "Home" not in text
    assert "Copyright BOSS Zhipin" not in text


def test_crawl_jd_feishu_job_detail_handler(monkeypatch):
    import json

    responses = [
        _response(
            '<html><body>'
            '<script id="js-websiteInfo" type="text/json">'
            '{"tenant_info":{"tenant_name":"Acme Inc"}}'
            "</script>"
            '<div id="app">Loading...</div>'
            "</body></html>"
        ),
        _FakeResponse(
            json.dumps(
                {
                    "code": 0,
                    "data": {
                        "job_post_detail": {
                            "id": "12345",
                            "title": "Backend Engineer",
                            "description": "Build scalable backend services.",
                            "requirement": "Java or C# with SQL.",
                            "city_list": [{"name": "Shenzhen"}],
                        }
                    },
                }
            ).encode("utf-8")
        ),
    ]

    def fake_stream(url, **kwargs):
        return _FakeStream(responses.pop(0))

    monkeypatch.setattr("resualign.crawler._fetch_stream", fake_stream)

    meta = {}
    text = crawl_jd(
        "https://acme.jobs.feishu.cn/campus/position/12345/detail",
        meta=meta,
    )

    assert "Backend Engineer" in text
    assert "Build scalable backend services." in text
    assert "Java or C# with SQL." in text
    assert meta["title"] == "Backend Engineer"
    assert meta["company"] == "Acme Inc"
    assert meta["city"] == "Shenzhen"


def test_crawl_jd_cleans_text(monkeypatch):
    html = """
    <html><body>
      <nav><a href="/menu">Menu</a></nav>
      <script>alert('tracking')</script>
      <style>.hidden { color: red; }</style>
      <div>
        <h1>Senior Python Engineer</h1>
        <p>Build APIs with FastAPI.</p>
        <p>   </p>
        <p>Work with Docker.</p>
      </div>
    </body></html>
    """
    _patch_fetch(monkeypatch, _response(html))

    text = crawl_jd("https://example.com/job")

    assert "Senior Python Engineer" in text
    assert "Build APIs with FastAPI." in text
    assert "Work with Docker." in text
    assert "Menu" not in text
    assert "tracking" not in text
    assert "color: red" not in text
    assert text == text.strip()
    assert "\n\n" not in text


def test_crawl_jd_with_selector(monkeypatch):
    html = """
    <html><body>
      <div class="sidebar">Sidebar text</div>
      <div class="jd-body">
        <h1>Backend Engineer</h1>
        <p>Kubernetes experience required.</p>
      </div>
      <footer>Footer text</footer>
    </body></html>
    """
    _patch_fetch(monkeypatch, _response(html))

    text = crawl_jd("https://example.com/job", selector=".jd-body")

    assert "Backend Engineer" in text
    assert "Kubernetes experience required." in text
    assert "Sidebar text" not in text
    assert "Footer text" not in text


def test_crawl_jd_selector_no_match(monkeypatch):
    _patch_fetch(
        monkeypatch,
        _response("<html><body><p>No match</p></body></html>"),
    )

    with pytest.raises(CrawlError, match="No elements matched selector"):
        crawl_jd("https://example.com/job", selector=".missing")


def test_crawl_jd_http_error(monkeypatch):
    _patch_fetch(monkeypatch, _response("Not Found", status_code=404))

    with pytest.raises(CrawlError, match="HTTP 404"):
        crawl_jd("https://example.com/missing")


def test_crawl_jd_network_error(monkeypatch):
    def boom(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("resualign.crawler._fetch_stream", boom)

    with pytest.raises(CrawlError, match="connection refused"):
        crawl_jd("https://example.com/job")


def test_crawl_jd_request_options(monkeypatch):
    captured = {}

    def fake_stream(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["kwargs"] = kwargs
        return _FakeStream(
            _response("<html><body><p>JD text</p></body></html>")
        )

    monkeypatch.setattr("resualign.crawler.httpx.stream", fake_stream)

    text = crawl_jd("https://example.com/job", timeout=5)

    assert text == "JD text"
    assert captured["method"] == "GET"
    assert captured["url"] == "https://example.com/job"
    assert captured["kwargs"]["timeout"] == 5
    assert captured["kwargs"]["follow_redirects"] is False
    assert captured["kwargs"]["headers"]["User-Agent"] == "ResuAlign/1.0"
    assert captured["kwargs"]["headers"]["Accept"].startswith(
        "text/html,application/xhtml+xml"
    )
    assert captured["kwargs"]["headers"]["Accept-Language"].startswith(
        "zh-CN"
    )


def test_crawl_jd_unknown_host_uses_generic_extraction(monkeypatch):
    html = """
    <html><body>
      <main><p>Unknown site JD body.</p></main>
    </body></html>
    """
    _patch_fetch(monkeypatch, _response(html))

    text = crawl_jd("https://unknown.example/job/1")

    assert "Unknown site JD body." in text


def test_crawl_jd_generic_page_uses_content_selector_and_meta(monkeypatch):
    _patch_fetch(monkeypatch, _response(_fixture("generic_job_page.html")))

    meta = {}
    text = crawl_jd("https://unknown.example/jobs/42", meta=meta)

    assert "负责核心业务后端服务的架构设计与开发。" in text
    assert "熟悉 Python、FastAPI 与 PostgreSQL" in text
    assert "Acme Inc 是国内领先的科技公司。" in text
    assert "首页" not in text
    assert "热门职位推荐" not in text
    assert "Copyright Acme Inc 2026" not in text
    assert meta["title"] == "高级后端工程师"
    assert meta["company"] == "Acme Inc"
    assert meta["city"] == "北京"


def test_crawl_jd_generic_meta_title_falls_back_to_h1(monkeypatch):
    html = """
    <html><head><title>Backend Engineer | Acme Careers</title></head>
    <body><main><h1>Backend Engineer</h1>
    <p>JD text here.</p></main></body></html>
    """
    _patch_fetch(monkeypatch, _response(html))

    meta = {}
    text = crawl_jd("https://unknown.example/job/1", meta=meta)

    assert "JD text here." in text
    assert meta["title"] == "Backend Engineer"


def test_crawl_jd_generic_meta_title_from_title_tag(monkeypatch):
    html = """
    <html><head><title>Frontend Engineer | Jobs</title></head>
    <body><div><p>Frontend JD body.</p></div></body></html>
    """
    _patch_fetch(monkeypatch, _response(html))

    meta = {}
    text = crawl_jd("https://unknown.example/job/2", meta=meta)

    assert "Frontend JD body." in text
    assert meta["title"] == "Frontend Engineer"


def test_crawl_error_http_has_category_and_url(monkeypatch):
    _patch_fetch(monkeypatch, _response("Not Found", status_code=404))

    with pytest.raises(CrawlError) as exc_info:
        crawl_jd("https://example.com/missing")

    assert exc_info.value.category == "http"
    assert exc_info.value.url == "https://example.com/missing"
    assert "HTTP 404" in str(exc_info.value)
    assert "http" in str(exc_info.value)


def test_crawl_error_network_has_category_and_url(monkeypatch):
    def boom(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("resualign.crawler._fetch_stream", boom)

    with pytest.raises(CrawlError) as exc_info:
        crawl_jd("https://example.com/job")

    assert exc_info.value.category == "fetch"
    assert exc_info.value.url == "https://example.com/job"
    assert "connection refused" in str(exc_info.value)
    assert "fetch" in str(exc_info.value)


def test_crawl_error_selector_has_category_and_url(monkeypatch):
    _patch_fetch(
        monkeypatch,
        _response("<html><body><p>No match</p></body></html>"),
    )

    with pytest.raises(CrawlError) as exc_info:
        crawl_jd("https://example.com/job", selector=".missing")

    assert exc_info.value.category == "selector"
    assert exc_info.value.url == "https://example.com/job"
    assert "No elements matched selector" in str(exc_info.value)
    assert "selector" in str(exc_info.value)


def test_crawl_jd_response_size_cap_streams_chunks(monkeypatch):
    oversized = b"<html><body><p>Too large</p></body></html>" + b" " * (
        5 * 1024 * 1024 + 1
    )
    _patch_fetch(
        monkeypatch,
        _FakeResponse(oversized, chunk_size=64 * 1024),
    )

    with pytest.raises(CrawlError) as exc_info:
        crawl_jd("https://example.com/huge")

    assert exc_info.value.category == "fetch"
    assert exc_info.value.url == "https://example.com/huge"
    assert "too large" in str(exc_info.value).lower()
    assert "fetch" in str(exc_info.value)


def test_crawl_jd_decodes_declared_charset(monkeypatch):
    content = "Caf\xe9".encode("iso-8859-1")
    _patch_fetch(
        monkeypatch,
        _FakeResponse(content, charset_encoding="iso-8859-1"),
    )

    text = crawl_jd("https://example.com/charset")

    assert "Caf\u00e9" in text


def test_crawl_jd_respects_httpx_encoding_attribute(monkeypatch):
    content = "Caf\xe9".encode("iso-8859-1")
    _patch_fetch(
        monkeypatch,
        _FakeResponse(content, encoding="iso-8859-1"),
    )

    text = crawl_jd("https://example.com/encoding-attr")

    assert "Caf\u00e9" in text


def test_crawl_jd_utf8_fallback_when_charset_unknown(monkeypatch):
    content = "R\u00e9sum\u00e9".encode("utf-8")
    _patch_fetch(monkeypatch, _FakeResponse(content))

    text = crawl_jd("https://example.com/fallback")

    assert "R\u00e9sum\u00e9" in text


def test_crawl_jd_removes_boilerplate(monkeypatch):
    html = """
    <html><body>
      <header>Site header</header>
      <nav>Navigation links</nav>
      <aside>Aside links</aside>
      <main><p>Actual JD content.</p></main>
      <footer>Copyright example</footer>
    </body></html>
    """
    _patch_fetch(monkeypatch, _response(html))

    text = crawl_jd("https://example.com/job")

    assert "Actual JD content." in text
    assert "Site header" not in text
    assert "Navigation links" not in text
    assert "Aside links" not in text
    assert "Copyright example" not in text


def test_crawl_jd_empty_content(monkeypatch):
    _patch_fetch(
        monkeypatch,
        _response("<html><body><nav>Menu</nav></body></html>"),
    )

    with pytest.raises(CrawlError) as exc_info:
        crawl_jd("https://example.com/empty")

    assert exc_info.value.category == "empty"
    assert exc_info.value.url == "https://example.com/empty"
    assert "Empty content" in str(exc_info.value)
    assert "empty" in str(exc_info.value)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "javascript:alert(1)",
        "ftp://example.com/job",
    ],
)
def test_crawl_jd_rejects_unsupported_schemes(url):
    with pytest.raises(CrawlError) as exc_info:
        crawl_jd(url)
    assert exc_info.value.category == "url"
    assert "scheme" in str(exc_info.value)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/job",
        "http://10.0.0.1/job",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/job",
    ],
)
def test_crawl_jd_rejects_private_ip_literals(url):
    with pytest.raises(CrawlError) as exc_info:
        crawl_jd(url)
    assert exc_info.value.category == "url"
    assert "private or local" in str(exc_info.value)


def test_crawl_jd_rejects_private_dns_resolution(monkeypatch):
    def private_resolve(host):
        raise CrawlError(
            "URL resolves to a private or local network address",
            category="dns",
            url=host,
        )

    monkeypatch.setattr(
        "resualign.crawler._resolve_public_host", private_resolve
    )

    with pytest.raises(CrawlError) as exc_info:
        crawl_jd("https://internal.example/job")
    assert exc_info.value.category == "dns"
    assert "private or local" in str(exc_info.value)


def test_resolve_public_host_pins_public_record_when_mixed(monkeypatch):
    import socket

    monkeypatch.setattr(
        "resualign.crawler.socket.getaddrinfo",
        lambda host, port: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("169.254.169.254", 0),
            ),
        ],
    )

    assert _resolve_public_host("mixed.example") == "93.184.216.34"


def test_resolve_public_host_accepts_public_records(monkeypatch):
    import socket

    monkeypatch.setattr(
        "resualign.crawler.socket.getaddrinfo",
        lambda host, port: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.35", 0)),
        ],
    )

    assert _resolve_public_host("public.example") == "93.184.216.34"


def test_resolve_public_host_rejects_all_private_records(monkeypatch):
    import socket

    monkeypatch.setattr(
        "resualign.crawler.socket.getaddrinfo",
        lambda host, port: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0)),
        ],
    )

    with pytest.raises(CrawlError, match="private or local"):
        _resolve_public_host("internal.example")


def test_crawl_jd_follows_redirect_manually(monkeypatch):
    responses = [
        _FakeResponse("", status_code=302, headers={"location": "/final"}),
        _FakeResponse("<html><body><p>Final JD</p></body></html>"),
    ]
    calls = []

    def fake_stream(url, **kwargs):
        calls.append(url)
        return _FakeStream(responses.pop(0))

    monkeypatch.setattr("resualign.crawler._fetch_stream", fake_stream)

    text = crawl_jd("https://example.com/job/start")

    assert text == "Final JD"
    assert calls == [
        "https://example.com/job/start",
        "https://example.com/final",
    ]


def test_crawl_jd_persists_cookies_across_redirects(monkeypatch):
    responses = [
        _FakeResponse(
            "",
            status_code=302,
            headers={"location": "/final", "Set-Cookie": "sid=abc; Path=/"},
        ),
        _response("<html><body><p>Final JD</p></body></html>"),
    ]
    captured = []

    def fake_stream(url, **kwargs):
        captured.append((url, kwargs.get("headers") or {}))
        return _FakeStream(responses.pop(0))

    monkeypatch.setattr("resualign.crawler._fetch_stream", fake_stream)

    text = crawl_jd("https://example.com/job/start")

    assert text == "Final JD"
    assert "sid=abc" in captured[1][1].get("Cookie", "")


def test_crawl_jd_moka_job_detail_handler(monkeypatch):
    import base64
    import html
    import json

    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad

    key = "0123456789abcdef"
    aes_iv = "fedcba9876543210"
    bootstrap = {
        "org": {"id": "xunlei", "name": "Xunlei Inc"},
        "siteId": "26600",
        "aesIv": aes_iv,
        "jobs": [
            {
                "id": "be80745c-6c1b-4bce-82d0-96d10d9ec924",
                "locations": [
                    {
                        "address": "深圳市南山区粤海街道高新区社区"
                        "白石路3709号迅雷大厦21楼"
                    }
                ],
            }
        ],
    }
    page_html = (
        '<html><body>'
        '<input id="init-data" type="hidden" value="'
        + html.escape(json.dumps(bootstrap), quote=True)
        + '">'
        '<div id="app">Loading...</div>'
        "</body></html>"
    )
    detail = {
        "id": "be80745c-6c1b-4bce-82d0-96d10d9ec924",
        "title": "Server Engineer",
        "jobDescription": "<p>Responsibility</p><p>Build servers.</p>",
        "locations": [{"cityName": "南山区"}],
    }
    plain = json.dumps({"code": 0, "data": detail}).encode("utf-8")
    ciphertext = AES.new(key.encode("utf-8"), AES.MODE_CBC, aes_iv.encode(
        "utf-8"
    )).encrypt(pad(plain, 16))
    api_body = {
        "data": base64.b64encode(ciphertext).decode("ascii"),
        "necromancer": key,
    }
    responses = [
        _response(page_html),
        _FakeResponse(json.dumps(api_body).encode("utf-8")),
    ]

    def fake_stream(url, **kwargs):
        return _FakeStream(responses.pop(0))

    monkeypatch.setattr("resualign.crawler._fetch_stream", fake_stream)

    meta = {}
    text = crawl_jd(
        "https://campus.xunlei.com/campus-recruitment/xunlei/26600/"
        "#/job/be80745c-6c1b-4bce-82d0-96d10d9ec924",
        meta=meta,
    )

    assert "Server Engineer" in text
    assert "Build servers." in text
    assert meta["title"] == "Server Engineer"
    assert meta["company"] == "Xunlei Inc"
    assert meta["city"] == "深圳"


def test_crawl_jd_rejects_redirect_to_private_ip(monkeypatch):
    responses = [
        _FakeResponse(
            "",
            status_code=302,
            headers={"location": "http://127.0.0.1/secret"},
        ),
    ]

    def fake_stream(url, **kwargs):
        return _FakeStream(responses.pop(0))

    monkeypatch.setattr("resualign.crawler._fetch_stream", fake_stream)

    with pytest.raises(CrawlError) as exc_info:
        crawl_jd("https://example.com/job")

    assert exc_info.value.category == "url"
    assert "private or local" in str(exc_info.value)


def test_crawl_jd_redirect_without_location(monkeypatch):
    monkeypatch.setattr(
        "resualign.crawler._fetch_stream",
        lambda *args, **kwargs: _FakeStream(
            _FakeResponse("", status_code=302)
        ),
    )

    with pytest.raises(CrawlError, match="Redirect without location"):
        crawl_jd("https://example.com/job")


def test_crawl_jd_redirect_cap(monkeypatch):
    def fake_stream(url, **kwargs):
        return _FakeStream(
            _FakeResponse("", status_code=302, headers={"location": "/next"})
        )

    monkeypatch.setattr("resualign.crawler._fetch_stream", fake_stream)

    with pytest.raises(CrawlError, match="Too many redirects"):
        crawl_jd("https://example.com/job")


class _FakeResponseHeaders:
    def get_content_charset(self):
        return None


class _FakeHTTPResponse:
    status = 200
    headers = _FakeResponseHeaders()

    def __init__(self, content):
        self._content = content

    def read(self, limit):
        return self._content


class _FakeHTTPConnection:
    instances = []

    def __init__(self, host, port, timeout):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = None
        self.closed = False
        self.request_args = None
        type(self).instances.append(self)

    def request(self, method, path, body=None, headers=None):
        self.request_args = (method, path, body, headers)

    def getresponse(self):
        return _FakeHTTPResponse(
            b"<html><body><p>Pinned JD</p></body></html>"
        )

    def close(self):
        self.closed = True


class _FakeSSLContext:
    def wrap_socket(self, sock, server_hostname=None):
        return sock


def _patch_pinned_connection(monkeypatch):
    _FakeHTTPConnection.instances = []
    monkeypatch.setattr(
        "resualign.crawler.socket.create_connection",
        lambda address, timeout=None: object(),
    )
    monkeypatch.setattr(
        "resualign.crawler.http.client.HTTPConnection",
        _FakeHTTPConnection,
    )
    monkeypatch.setattr(
        "resualign.crawler.http.client.HTTPSConnection",
        _FakeHTTPConnection,
    )
    monkeypatch.setattr(
        "resualign.crawler.ssl.create_default_context",
        lambda: _FakeSSLContext(),
    )


def test_fetch_stream_pinned_http_connection(monkeypatch):
    _patch_pinned_connection(monkeypatch)

    with _fetch_stream(
        "http://example.com/job?page=1", timeout=7, ip="93.184.216.34"
    ) as response:
        assert response.status_code == 200
        assert b"Pinned JD" in b"".join(response.iter_bytes())

    connection = _FakeHTTPConnection.instances[0]
    assert connection.host == "example.com"
    assert connection.port == 80
    assert connection.request_args[:2] == ("GET", "/job?page=1")
    assert connection.closed is True


def test_fetch_stream_pinned_https_connection(monkeypatch):
    _patch_pinned_connection(monkeypatch)

    with _fetch_stream(
        "https://secure.example/job", timeout=5, ip="1.2.3.4"
    ) as response:
        assert response.status_code == 200
        assert response.charset_encoding is None
        assert list(response.iter_bytes())

    connection = _FakeHTTPConnection.instances[0]
    assert connection.host == "secure.example"
    assert connection.port == 443
    assert connection.closed is True


@pytest.mark.parametrize("url", [None, "", "http://"])
def test_crawl_jd_rejects_missing_url_or_host(url):
    with pytest.raises(CrawlError) as exc_info:
        crawl_jd(url)
    assert exc_info.value.category == "url"
    assert exc_info.value.url == url


def test_resolve_public_host_reports_dns_failure(monkeypatch):
    import socket

    def boom(host, port):
        raise socket.gaierror("no such host")

    monkeypatch.setattr("resualign.crawler.socket.getaddrinfo", boom)

    with pytest.raises(CrawlError) as exc_info:
        _resolve_public_host("missing.example")
    assert exc_info.value.category == "dns"
    assert exc_info.value.url == "missing.example"


def test_resolve_public_host_skips_non_ip_records(monkeypatch):
    monkeypatch.setattr(
        "resualign.crawler.socket.getaddrinfo",
        lambda host, port: [
            (0, 0, 0, "", ("not-an-ip", 0)),
            (0, 0, 0, "", ("93.184.216.34", 0)),
        ],
    )

    assert _resolve_public_host("mixed.example") == "93.184.216.34"


def test_merge_cookies_supports_get_all_headers():
    class _GetAllHeaders:
        def get_all(self, name):
            return ["sid=abc; Path=/"]

    cookies = {}
    _merge_cookies(cookies, _FakeResponse(headers=_GetAllHeaders()))
    assert cookies == {"sid": "abc"}


def test_merge_cookies_supports_get_list_headers():
    class _GetListHeaders:
        def get_list(self, name):
            return ["sid=def"]

    cookies = {}
    _merge_cookies(cookies, _FakeResponse(headers=_GetListHeaders()))
    assert cookies == {"sid": "def"}


def test_merge_cookies_ignores_malformed_values(monkeypatch):
    class _BoomCookie:
        def load(self, value):
            raise ValueError("malformed")

    monkeypatch.setattr(
        "resualign.crawler.http.cookies.SimpleCookie", _BoomCookie
    )
    cookies = {}
    _merge_cookies(cookies, {"Set-Cookie": "bad"})
    assert cookies == {}


def test_decode_content_falls_back_on_unknown_encoding():
    text = _decode_content("R\u00e9sum\u00e9".encode("utf-8"), "no-such-codec")
    assert "R\u00e9sum\u00e9" in text


def test_decode_content_replaces_invalid_utf8_bytes():
    text = _decode_content(b"\xff\xfe", "utf-8")
    assert "\ufffd" in text


def test_crawl_jd_site_handler_fills_meta_from_page(monkeypatch):
    _patch_fetch(monkeypatch, _response(_fixture("linkedin_job.html")))
    meta = {}

    text = crawl_jd("https://www.linkedin.com/jobs/view/123", meta=meta)

    assert "Lead design and delivery of the payments platform." in text
    assert meta["title"] == "Senior Python Engineer"
