"""Job description crawler with SSRF-safe fetching and size limits."""

from __future__ import annotations

import base64
import html
import http.client
import http.cookies
import ipaddress
import json
import logging
import os
import random
import re
import socket
import ssl
import threading
import time
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .observability import current_request_id, log_event

HEADERS = {
    "User-Agent": "ResuAlign/1.0",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
DEFAULT_UA_POOL = (
    HEADERS["User-Agent"],
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) "
        "Gecko/20100101 Firefox/126.0"
    ),
)
DEFAULT_MIN_INTERVAL = 1.0
MAX_RETRIES = 2
_RETRYABLE_HTTP_ERRORS = (
    httpx.ConnectError,
    httpx.ReadError,
    httpx.TimeoutException,
)
_DYNAMIC_SITE_TOKENS = (
    "feishu", "moka", "mokahr", "zhipin", "boss", "linkedin",
    "campus-talent",
)

logger = logging.getLogger(__name__)


class _HostRateLimiter:
    """Thread-safe per-host minimum interval limiter."""

    def __init__(self, interval: float = DEFAULT_MIN_INTERVAL):
        self.interval = max(0.0, float(interval))
        self._next_available: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str) -> None:
        if not host or self.interval <= 0:
            return
        now = time.monotonic()
        with self._lock:
            next_available = max(now, self._next_available.get(host, 0.0))
            self._next_available[host] = next_available + self.interval
        delay = next_available - now
        if delay > 0:
            time.sleep(delay)

    def reset(self) -> None:
        with self._lock:
            self._next_available.clear()


def _env_min_interval() -> float:
    raw = os.getenv("RESUALIGN_CRAWL_MIN_INTERVAL", "").strip()
    if not raw:
        return DEFAULT_MIN_INTERVAL
    try:
        return max(0.0, float(raw))
    except ValueError:
        return DEFAULT_MIN_INTERVAL


_crawl_rate_limiter = _HostRateLimiter(_env_min_interval())
_ua_index = 0
_ua_lock = threading.Lock()


class _UARotator:
    """Per-crawl user-agent rotator seeded with the base UA string."""

    def __init__(self):
        self._pool = _ua_pool()
        self._index = 0
        self._env_configured = bool(
            os.getenv("RESUALIGN_CRAWL_UA_POOL", "").strip()
        )

    def next(self) -> str:
        if self._env_configured:
            return _next_user_agent()
        value = self._pool[self._index % len(self._pool)]
        self._index += 1
        return value


def _next_user_agent() -> str:
    global _ua_index
    pool = _ua_pool()
    with _ua_lock:
        value = pool[_ua_index % len(pool)]
        _ua_index += 1
        return value


def _ua_pool() -> list[str]:
    raw = os.getenv("RESUALIGN_CRAWL_UA_POOL", "").strip()
    if not raw:
        return list(DEFAULT_UA_POOL)
    try:
        values = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("Invalid RESUALIGN_CRAWL_UA_POOL; using defaults")
        return list(DEFAULT_UA_POOL)
    pool = [
        str(value).strip()
        for value in values
        if isinstance(value, str) and str(value).strip()
    ]
    return pool or list(DEFAULT_UA_POOL)


def _proxy_url() -> str:
    return os.getenv("RESUALIGN_CRAWL_PROXY", "").strip()


def _playwright_enabled() -> bool:
    value = os.getenv("RESUALIGN_CRAWL_PLAYWRIGHT", "0").strip().lower()
    return value in {"1", "true", "yes", "on"}


# A rendered page that yields less than this many chars of JD text is
# treated as an SPA shell (data loaded by JS), triggering the Playwright
# fallback for known dynamic sites.
_MIN_JD_TEXT = 50


def _is_dynamic_site(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(token in host for token in _DYNAMIC_SITE_TOKENS)


def _throttle(url: str) -> None:
    limiter = _crawl_rate_limiter
    if hasattr(limiter, "interval"):
        limiter.interval = _env_min_interval()
    limiter.wait((urlparse(url).hostname or "").lower())
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5
ALLOWED_SCHEMES = ("http", "https")
BOILERPLATE_TAGS = ("script", "style", "nav", "header", "footer", "aside")
_GENERIC_CONTENT_SELECTORS = (
    "main",
    "article",
    "[role='main']",
    "#job-content",
    "#jobContent",
    "#jd-content",
    "#jdContent",
    "#position-detail",
    "#positionDetail",
    "#job-detail",
    "#jobDetail",
    ".job-content",
    ".jobContent",
    ".jd-content",
    ".jdContent",
    ".job-description",
    ".jobDescription",
    ".jd-description",
    ".jdDescription",
    ".position-info",
    ".positionInfo",
    ".job-detail",
    ".jobDetail",
    ".post-content",
    ".postContent",
    ".content-detail",
    ".contentDetail",
)


class CrawlError(Exception):
    """Raised when a JD URL cannot be fetched or parsed."""

    def __init__(self, message, category="fetch", url=None):
        super().__init__(message)
        self.category = category
        self.url = url

    def __str__(self):
        return f"{self.category}: {super().__str__()}"


def crawl_jd(
    url: str,
    timeout: int = 30,
    selector: str | None = None,
    meta: dict | None = None,
    request_id: str | None = None,
    on_stage=None,
) -> str:
    """Fetch a JD URL and return cleaned text with hardening applied."""
    request_id = request_id or current_request_id()
    started = time.monotonic()
    ua_rotator = _UARotator()
    try:
        if on_stage is not None:
            on_stage("fetching", "Fetching JD")
        fetched = _static_fetch(
            url, timeout=timeout, ua_rotator=ua_rotator, request_id=request_id
        )
        if on_stage is not None:
            on_stage("parsing", "Parsing JD content")
        text = _parse_html(
            fetched.content,
            fetched.encoding,
            fetched.url,
            selector,
            meta,
            ip=fetched.ip,
            timeout=timeout,
            cookies=fetched.cookies,
        )
    except CrawlError as exc:
        if exc.category in ("empty", "fetch", "http") and _is_dynamic_site(url):
            fallback_text = _playwright_fallback(
                url, timeout=timeout, selector=selector, meta=meta,
                request_id=request_id,
            )
            if fallback_text is not None:
                log_event(
                    logger,
                    "crawler.playwright_success",
                    request_id=request_id,
                    duration_ms=(time.monotonic() - started) * 1000,
                    extra={"url": url},
                )
                return fallback_text
        log_event(
            logger,
            "crawler.failed",
            level="warning",
            request_id=request_id,
            duration_ms=(time.monotonic() - started) * 1000,
            extra={"url": url, "category": exc.category},
        )
        raise
    log_event(
        logger,
        "crawler.success",
        request_id=request_id,
        duration_ms=(time.monotonic() - started) * 1000,
        extra={"url": url},
    )
    # SPA shells (e.g. Alibaba campus-talent) return 200 with near-empty
    # static HTML; the JD text only exists after JS renders. When a known
    # dynamic site yields too little text, retry with a rendered browser.
    if len(text.strip()) < _MIN_JD_TEXT and _is_dynamic_site(url):
        fallback_text = _playwright_fallback(
            url, timeout=timeout, selector=selector, meta=meta,
            request_id=request_id, force=True,
        )
        if fallback_text and len(fallback_text.strip()) > len(text.strip()):
            text = fallback_text
            log_event(
                logger,
                "crawler.playwright_success",
                request_id=request_id,
                duration_ms=(time.monotonic() - started) * 1000,
                extra={"url": url, "reason": "short_static_text"},
            )
    return text


class _StaticFetchResult:
    def __init__(
        self,
        content: bytes,
        encoding: str,
        url: str,
        ip: str | None,
        cookies: dict[str, str],
    ):
        self.content = content
        self.encoding = encoding
        self.url = url
        self.ip = ip
        self.cookies = cookies


def _static_fetch(
    url: str,
    timeout: int,
    ua_rotator: _UARotator,
    request_id: str | None,
) -> _StaticFetchResult:
    """Fetch through redirects while throttling and validating every hop."""
    current_url = url
    cookies: dict[str, str] = {}
    for _ in range(MAX_REDIRECTS + 1):
        _validate_target(current_url)
        proxy = _proxy_url()
        pinned_ip = (
            None
            if proxy
            else _resolve_public_host(urlparse(current_url).hostname or "")
        )
        headers = _headers_for_cookies(cookies, ua_rotator)
        try:
            response = _fetch_with_retry(
                current_url,
                timeout=timeout,
                ip=pinned_ip,
                headers=headers,
                request_id=request_id,
            )
            _merge_cookies(cookies, response)
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("location")
                if not location:
                    raise CrawlError(
                        f"Redirect without location at {current_url}",
                        category="http",
                        url=current_url,
                    )
                current_url = urljoin(current_url, location)
                continue
            if response.status_code >= 400:
                raise CrawlError(
                    f"Failed to fetch {current_url}: "
                    f"HTTP {response.status_code}",
                    category="http",
                    url=current_url,
                )
            encoding = (
                response.encoding
                or response.charset_encoding
                or "utf-8"
            )
            return _StaticFetchResult(
                response.content,
                encoding,
                current_url,
                pinned_ip,
                cookies,
            )
        except CrawlError:
            raise
        except httpx.HTTPError as exc:
            raise CrawlError(
                f"Failed to fetch {current_url}: {exc}",
                category="fetch",
                url=current_url,
            ) from exc
    raise CrawlError(
        f"Too many redirects at {url}",
        category="http",
        url=url,
    )


def _headers_for_cookies(
    cookies: dict[str, str],
    ua_rotator: _UARotator | None = None,
) -> dict[str, str]:
    headers = dict(HEADERS)
    if ua_rotator is not None:
        headers["User-Agent"] = ua_rotator.next()
    if cookies:
        headers["Cookie"] = "; ".join(
            f"{name}={value}" for name, value in cookies.items()
        )
    return headers


class _FetchedResponse:
    def __init__(
        self,
        status_code: int,
        headers,
        content: bytes,
        encoding: str,
        charset_encoding: str | None,
    ):
        self.status_code = status_code
        self.headers = headers
        self.content = content
        self.encoding = encoding
        self.charset_encoding = charset_encoding


def _backoff_delay(attempt: int) -> float:
    base = 0.5 * (2 ** attempt)
    return random.uniform(base * 0.5, base)


def _fetch_with_retry(
    url: str,
    timeout: int,
    ip: str | None = None,
    headers: dict | None = None,
    method: str = "GET",
    json_body: dict | None = None,
    request_id: str | None = None,
) -> _FetchedResponse:
    """Fetch one response with bounded exponential-backoff retries."""
    request_id = request_id or current_request_id()
    last_error: httpx.HTTPError | None = None
    for attempt in range(MAX_RETRIES + 1):
        _throttle(url)
        try:
            with _fetch_stream(
                url,
                timeout=timeout,
                ip=ip,
                headers=headers or HEADERS,
                method=method,
                json_body=json_body,
            ) as response:
                content = _read_limited(response, MAX_RESPONSE_BYTES, url)
                encoding = (
                    getattr(response, "encoding", None)
                    or getattr(response, "charset_encoding", None)
                    or "utf-8"
                )
                return _FetchedResponse(
                    response.status_code,
                    response.headers,
                    content,
                    encoding,
                    getattr(response, "charset_encoding", None),
                )
        except _RETRYABLE_HTTP_ERRORS as exc:
            last_error = exc
            if attempt < MAX_RETRIES:
                delay = _backoff_delay(attempt)
                log_event(
                    logger,
                    "crawler.retry",
                    level="warning",
                    request_id=request_id,
                    duration_ms=delay * 1000,
                    extra={
                        "url": url,
                        "attempt": attempt + 1,
                        "error": str(exc),
                    },
                )
                time.sleep(delay)
        except CrawlError:
            raise
        except httpx.HTTPError:
            raise
    assert last_error is not None
    raise last_error


def _parse_html(
    content: bytes | str,
    encoding: str,
    url: str,
    selector: str | None,
    meta: dict | None,
    ip: str | None = None,
    timeout: int = 30,
    cookies: dict[str, str] | None = None,
) -> str:
    """Clean and extract JD text from fetched HTML."""
    decoded = (
        _decode_content(content, encoding)
        if isinstance(content, bytes)
        else content
    )
    soup = BeautifulSoup(decoded, "html.parser")

    if selector is not None:
        for tag in soup(BOILERPLATE_TAGS):
            tag.decompose()
        nodes = soup.select(selector)
        if not nodes:
            raise CrawlError(
                f"No elements matched selector {selector!r} at {url}",
                category="selector",
                url=url,
            )
        raw_text = "\n".join(node.get_text(separator="\n") for node in nodes)
    else:
        raw_text = _extract_site_text(
            url, soup, ip, timeout, meta, cookies or {}
        )

    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    text = "\n".join(lines).strip()
    if not text:
        raise CrawlError(f"Empty content at {url}", category="empty", url=url)
    return text


def _playwright_fetch_html(
    url: str,
    timeout: int = 30,
    request_id: str | None = None,
) -> str | None:
    """Fetch a rendered page with Playwright when it is installed."""
    request_id = request_id or current_request_id()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log_event(
            logger,
            "crawler.playwright_unavailable",
            level="warning",
            request_id=request_id,
            extra={"url": url},
        )
        return None
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(
                    user_agent=_headers_for_cookies({})["User-Agent"]
                )
                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=max(1000, timeout * 1000),
                )
                # SPA pages load the JD body after initial render via XHR;
                # give async data a moment before reading the DOM.
                page.wait_for_timeout(1500)
                return page.content()
            finally:
                browser.close()
    except Exception as exc:
        log_event(
            logger,
            "crawler.playwright_failed",
            level="warning",
            request_id=request_id,
            extra={"url": url, "error": str(exc)},
        )
        return None


def _playwright_fallback(
    url: str,
    timeout: int,
    selector: str | None,
    meta: dict | None,
    request_id: str | None,
    force: bool = False,
) -> str | None:
    """Optionally retry a dynamic-site failure with a rendered browser.

    ``force=True`` bypasses the ``RESUALIGN_CRAWL_PLAYWRIGHT`` gate: it is
    used when static extraction returned near-empty text from a known SPA
    shell, where rendering is the only realistic path. If Playwright is not
    installed the fetch helper degrades to None.
    """
    if not _playwright_enabled() and not force:
        return None
    _throttle(url)
    html_content = _playwright_fetch_html(url, timeout=timeout, request_id=request_id)
    if not html_content:
        return None
    proxy = _proxy_url()
    try:
        ip = None if proxy else _resolve_public_host(
            urlparse(url).hostname or ""
        )
    except CrawlError:
        return None
    try:
        return _parse_html(
            html_content,
            "utf-8",
            url,
            selector,
            meta,
            ip=ip,
            timeout=timeout,
            cookies={},
        )
    except CrawlError:
        return None


def _validate_target(url: str) -> None:
    """Reject unsafe schemes, credentials, ports, and private literals."""
    if not isinstance(url, str) or not url.strip():
        raise CrawlError("URL is required", category="url", url=url)
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise CrawlError(
            f"Unsupported URL scheme: {parsed.scheme!r}",
            category="url",
            url=url,
        )
    if parsed.username or parsed.password:
        raise CrawlError(
            "URL must not contain credentials",
            category="url",
            url=url,
        )
    try:
        port = parsed.port
    except ValueError as exc:
        raise CrawlError(
            "URL has an invalid port",
            category="url",
            url=url,
        ) from exc
    if port is not None and port not in (80, 443):
        raise CrawlError(
            "URL port must be 80 or 443",
            category="url",
            url=url,
        )
    host = (parsed.hostname or "").lower()
    if not host:
        raise CrawlError("URL is missing a host", category="url", url=url)
    if _is_private_literal(host):
        raise CrawlError(
            "URL points to a private or local network address",
            category="url",
            url=url,
        )


def _is_private_literal(host: str) -> bool:
    """Return True when host is an IP literal that is not globally routable."""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return not address.is_global


def _resolve_public_host(host: str) -> str | None:
    """Resolve a hostname to a globally routable IP for connection pinning."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise CrawlError(
            f"Could not resolve host: {host}", category="dns", url=host
        ) from exc
    public_addresses = []
    for info in infos:
        try:
            address = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if address.is_global:
            public_addresses.append(str(address))
    if not public_addresses:
        raise CrawlError(
            "URL resolves to a private or local network address",
            category="dns",
            url=host,
        )
    return public_addresses[0]


def _fetch_stream(
    url: str,
    timeout: int,
    ip: str | None = None,
    headers: dict | None = None,
    method: str = "GET",
    json_body: dict | None = None,
):
    """Open a streaming request; redirects are handled by the caller.

    When RESUALIGN_CRAWL_PROXY is set the request goes through the proxy and
    direct IP pinning is skipped because the proxy performs DNS resolution.
    That is an explicit SSRF tradeoff for deployments that require egress
    through a trusted proxy.
    """
    request_headers = headers or HEADERS
    proxy = _proxy_url()
    if ip and not proxy:
        return _PinnedStream(
            url,
            timeout=timeout,
            ip=ip,
            headers=request_headers,
            method=method,
            json_body=json_body,
        )
    stream_kwargs = {
        "method": method,
        "url": url,
        "headers": request_headers,
        "timeout": timeout,
        "follow_redirects": False,
        "json": json_body,
    }
    if proxy:
        stream_kwargs["proxy"] = proxy
    return httpx.stream(
        **stream_kwargs
    )


def _merge_cookies(cookies: dict[str, str], response) -> None:
    """Merge Set-Cookie headers from a response into the cookie jar."""
    headers = getattr(response, "headers", {})
    values: list[str] = []
    if hasattr(headers, "get_all"):
        values = headers.get_all("Set-Cookie") or []
    elif hasattr(headers, "get_list"):
        values = headers.get_list("set-cookie")
    elif isinstance(headers, dict):
        raw = headers.get("Set-Cookie") or headers.get("set-cookie")
        if raw:
            values = [raw]
    for value in values:
        try:
            jar = http.cookies.SimpleCookie()
            jar.load(value)
            for name, morsel in jar.items():
                cookies[name] = morsel.value
        except Exception:
            continue


class _PinnedStream:
    """Stream a request over a pre-resolved public IP with Host/SNI intact."""

    def __init__(
        self,
        url: str,
        timeout: int,
        ip: str,
        headers: dict | None = None,
        method: str = "GET",
        json_body: dict | None = None,
    ):
        self.url = url
        self.timeout = timeout
        self.ip = ip
        self.headers = headers or HEADERS
        self.method = method
        self.json_body = json_body
        self._conn = None

    def __enter__(self):
        parsed = urlparse(self.url)
        scheme = (parsed.scheme or "http").lower()
        host = parsed.hostname or ""
        port = parsed.port or (443 if scheme == "https" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        try:
            raw = socket.create_connection(
                (self.ip, port), timeout=self.timeout
            )
            if scheme == "https":
                context = ssl.create_default_context()
                raw = context.wrap_socket(raw, server_hostname=host)
            conn_cls = (
                http.client.HTTPSConnection
                if scheme == "https"
                else http.client.HTTPConnection
            )
            conn = conn_cls(host, port, timeout=self.timeout)
            conn.sock = raw
            request_headers = dict(self.headers)
            body = None
            if self.json_body is not None:
                body = json.dumps(self.json_body).encode("utf-8")
                request_headers.setdefault("Content-Type", "application/json")
            conn.request(
                self.method, path, body=body, headers=request_headers
            )
            response = conn.getresponse()
            self._conn = conn
            return _PinnedResponse(response)
        except OSError as exc:
            raise httpx.ConnectError(str(exc)) from exc
        except Exception as exc:
            raise httpx.HTTPError(str(exc)) from exc

    def __exit__(self, *args):
        if self._conn is not None:
            self._conn.close()
        return False


class _PinnedResponse:
    """Minimal httpx-like response backed by an http.client response."""

    def __init__(self, response):
        self.status_code = response.status
        self.headers = response.headers
        self.encoding = None
        self.charset_encoding = response.headers.get_content_charset()
        self._content = response.read(MAX_RESPONSE_BYTES + 1)

    def iter_bytes(self):
        yield self._content


def _read_limited(response: httpx.Response, limit: int, url: str) -> bytes:
    """Read the response body while enforcing a streaming byte cap."""
    chunks = []
    size = 0
    for chunk in response.iter_bytes():
        size += len(chunk)
        if size > limit:
            raise CrawlError(
                f"Response too large at {url} (limit {limit} bytes)",
                category="fetch",
                url=url,
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _decode_content(content: bytes, encoding: str) -> str:
    try:
        return content.decode(encoding)
    except (LookupError, UnicodeDecodeError):
        return content.decode("utf-8", errors="replace")


def _extract_site_text(
    url: str,
    soup: BeautifulSoup,
    ip: str | None = None,
    timeout: int = 30,
    meta: dict | None = None,
    cookies: dict[str, str] | None = None,
) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if _moka_init_data(soup) is not None:
        return _moka_job_text(url, soup, ip, timeout, meta, cookies)
    if (
        host == "jobs.feishu.cn"
        or host.endswith(".jobs.feishu.cn")
    ) and re.search(r"/position/\d+", path):
        return _feishu_job_text(url, soup, ip, timeout, meta)
    if (
        host == "jobs.bytedance.com"
        or host.endswith(".jobs.bytedance.com")
    ) and re.search(r"/position/\d+", path):
        return _bytedance_job_text(url, soup, ip, timeout, meta)
    for matcher, handler in SITE_HANDLERS:
        if matcher(host, path):
            text = handler(soup)
            if meta is not None:
                fallback = _meta_from_soup(soup)
                meta.setdefault("title", fallback.get("title"))
                meta.setdefault("company", fallback.get("company"))
                meta.setdefault("city", fallback.get("city"))
            return text
    text = _generic_job_text(soup)
    if meta is not None:
        fallback = _meta_from_soup(soup)
        meta.setdefault("title", fallback.get("title"))
        meta.setdefault("company", fallback.get("company"))
        meta.setdefault("city", fallback.get("city"))
    return text


def _moka_init_data(soup: BeautifulSoup) -> dict | None:
    """Return the Moka ATS bootstrap JSON when present on the page."""
    node = soup.find(id="init-data")
    if node is None:
        return None
    raw = node.get("value")
    if not raw:
        return None
    try:
        return json.loads(html.unescape(raw))
    except (UnicodeDecodeError, ValueError):
        return None


def _moka_job_id(url: str) -> str | None:
    parsed = urlparse(url)
    haystack = f"{parsed.fragment} {parsed.path}"
    match = re.search(
        r"(?:^|/)(?:job|position|job-post)/([0-9a-fA-F-]{8,})",
        haystack,
    )
    return match.group(1) if match else None


def _moka_job_text(
    url: str,
    soup: BeautifulSoup,
    ip: str | None,
    timeout: int,
    meta: dict | None = None,
    cookies: dict[str, str] | None = None,
) -> str:
    """Extract a Moka ATS JD from its encrypted website/job API."""
    data = _moka_init_data(soup)
    if data is None:
        return _generic_job_text(soup)
    job_id = _moka_job_id(url)
    if job_id is None:
        return _generic_job_text(soup)
    org = data.get("org") or {}
    org_id = org.get("id") or org.get("orgId")
    site_id = data.get("siteId") or org.get("siteId")
    aes_iv = data.get("aesIv") or org.get("aesIv") or ""
    if not org_id or not site_id or not aes_iv:
        return _generic_job_text(soup)

    headers = dict(HEADERS)
    if cookies:
        headers["Cookie"] = "; ".join(
            f"{name}={value}" for name, value in cookies.items()
        )
    headers["Referer"] = url
    api_url = f"https://{urlparse(url).netloc}/api/outer/ats-apply/website/job"
    try:
        response = _fetch_with_retry(
            api_url,
            timeout=timeout,
            ip=ip,
            headers=headers,
            method="POST",
            json_body={
                "orgId": org_id,
                "jobId": job_id,
                "siteId": int(site_id),
                "locale": "zh-CN",
            },
        )
        if response.status_code != 200:
            return _generic_job_text(soup)
        content = response.content
    except (httpx.HTTPError, CrawlError):
        return _generic_job_text(soup)

    detail = _moka_detail(content, aes_iv)
    if detail is None:
        return _generic_job_text(soup)
    title = detail.get("title")
    description = _strip_html(detail.get("jobDescription") or "")
    parts = [part for part in (title, description) if part]
    if not parts:
        return _generic_job_text(soup)
    if meta is not None:
        meta["title"] = title
        meta["company"] = org.get("name") or org.get("displayName")
        meta["city"] = _moka_city(data, detail)
    return "\n\n".join(str(part) for part in parts)


def _moka_city(data: dict, detail: dict) -> str | None:
    """Resolve a Moka job's city, preferring a real city over a district."""
    locations = detail.get("locations") or []
    if locations:
        city_name = locations[0].get("cityName") or ""
        if city_name and not city_name.endswith("区"):
            return city_name
    for job in data.get("jobs") or []:
        if job.get("id") != detail.get("id"):
            continue
        for location in job.get("locations") or []:
            address = location.get("address") or ""
            match = re.search(r"([\u4e00-\u9fa5]{2,}市)", address)
            if match:
                city = match.group(1)
                return city[:-1] if city.endswith("市") else city
        break
    if locations:
        first = locations[0]
        return (
            first.get("cityName")
            or first.get("provinceName")
            or first.get("country")
        )
    return None


def _moka_detail(content: bytes, aes_iv: str) -> dict | None:
    """Decrypt the Moka website/job payload and return the detail dict."""
    try:
        payload = json.loads(content.decode("utf-8", errors="replace"))
    except (UnicodeDecodeError, ValueError):
        return None
    encrypted = payload.get("data")
    key = payload.get("necromancer")
    if not encrypted or not key or not aes_iv:
        return None
    try:
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import unpad

        cipher = AES.new(
            key.encode("utf-8"),
            AES.MODE_CBC,
            iv=aes_iv.encode("utf-8"),
        )
        plain = unpad(cipher.decrypt(base64.b64decode(encrypted)), 16)
        inner = json.loads(plain.decode("utf-8"))
    except Exception:
        return None
    return (inner.get("data") or {}) if isinstance(inner, dict) else None


def _strip_html(text: str) -> str:
    fragment = BeautifulSoup(text, "html.parser")
    return fragment.get_text(separator="\n")


def _feishu_job_text(
    url: str,
    soup: BeautifulSoup,
    ip: str | None,
    timeout: int,
    meta: dict | None = None,
) -> str:
    """Extract a Feishu ATS JD from its JSON detail API."""
    parsed = urlparse(url)
    match = re.search(r"/position/(\d+)", parsed.path)
    if match is None:
        return _generic_job_text(soup)
    post_id = match.group(1)
    api_url = (
        f"https://{parsed.netloc}/api/v1/job/posts/{post_id}"
        "?portal_type=6&with_recommend=false"
    )
    try:
        response = _fetch_with_retry(
            api_url, timeout=timeout, ip=ip
        )
        if response.status_code != 200:
            return _generic_job_text(soup)
        content = response.content
    except (httpx.HTTPError, CrawlError):
        return _generic_job_text(soup)
    try:
        payload = json.loads(content.decode("utf-8", errors="replace"))
    except (UnicodeDecodeError, ValueError):
        return _generic_job_text(soup)
    detail = ((payload.get("data") or {}).get("job_post_detail") or {})
    if meta is not None:
        meta["title"] = detail.get("title")
        meta["company"] = _feishu_tenant_name(soup)
        cities = detail.get("city_list") or detail.get(
            "city_info_list_for_delivery"
        ) or []
        if cities:
            meta["city"] = cities[0].get("name")
    parts = [
        part
        for part in (
            detail.get("title"),
            _strip_html(str(detail.get("description") or "")),
            _strip_html(str(detail.get("requirement") or "")),
        )
        if part
    ]
    if not parts:
        return _generic_job_text(soup)
    return "\n\n".join(str(part) for part in parts)


def _bytedance_job_text(
    url: str,
    soup: BeautifulSoup,
    ip: str | None,
    timeout: int,
    meta: dict | None = None,
) -> str:
    """Extract a ByteDance campus JD from its JSON detail API."""
    parsed = urlparse(url)
    match = re.search(r"/position/(\d+)", parsed.path)
    if match is None:
        return _generic_job_text(soup)
    post_id = match.group(1)
    portal_type = 3 if "/campus/" in parsed.path.lower() else 2
    api_url = (
        f"https://{parsed.netloc}/api/v1/job/posts/{post_id}"
        f"?portal_type={portal_type}&with_recommend=false"
    )
    headers = dict(HEADERS)
    headers["Referer"] = url
    headers["Accept"] = "application/json, text/plain, */*"
    try:
        response = _fetch_with_retry(
            api_url, timeout=timeout, ip=ip, headers=headers
        )
        if response.status_code != 200:
            return _generic_job_text(soup)
        content = response.content
    except (httpx.HTTPError, CrawlError):
        return _generic_job_text(soup)
    try:
        payload = json.loads(content.decode("utf-8", errors="replace"))
    except (UnicodeDecodeError, ValueError):
        return _generic_job_text(soup)
    detail = ((payload.get("data") or {}).get("job_post_detail") or {})
    parts = [
        part
        for part in (
            detail.get("title"),
            _strip_html(str(detail.get("description") or "")),
            _strip_html(str(detail.get("requirement") or "")),
        )
        if part
    ]
    if not parts:
        return _generic_job_text(soup)
    if meta is not None:
        meta["title"] = detail.get("title")
        fallback = _meta_from_soup(soup)
        meta.setdefault("company", fallback.get("company"))
        meta.setdefault("company", "字节跳动")
        cities = detail.get("city_list") or detail.get(
            "city_info_list_for_delivery"
        ) or []
        if cities:
            meta["city"] = cities[0].get("name")
    return "\n\n".join(str(part) for part in parts)


def _feishu_tenant_name(soup: BeautifulSoup) -> str | None:
    """Return the tenant/company name embedded in a Feishu careers page."""
    node = soup.find("script", id="js-websiteInfo")
    if node is None or not node.string:
        return None
    try:
        info = json.loads(node.string)
    except (UnicodeDecodeError, ValueError):
        return None
    tenant = info.get("tenant_info") or {}
    return tenant.get("tenant_name")


def _meta_from_soup(soup: BeautifulSoup) -> dict[str, str | None]:
    """Extract title/company/city hints from JSON-LD and HTML meta tags."""
    company: str | None = None
    city: str | None = None
    title: str | None = None

    def walk(node):
        nonlocal company, city, title
        if isinstance(node, dict):
            if title is None and isinstance(node.get("title"), str):
                candidate = node["title"].strip()
                if candidate:
                    title = candidate
            elif (
                title is None
                and node.get("@type") == "JobPosting"
                and isinstance(node.get("name"), str)
            ):
                candidate = node["name"].strip()
                if candidate:
                    title = candidate
            org = node.get("hiringOrganization")
            if company is None and isinstance(org, dict):
                company = org.get("name")
            location = node.get("jobLocation")
            if city is None and isinstance(location, dict):
                address = location.get("address") or {}
                if isinstance(address, dict):
                    city = address.get("addressLocality")
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for node in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(node.get_text() or "")
        except (UnicodeDecodeError, ValueError):
            continue
        walk(data)
        if company and city:
            break
    if title is None:
        h1 = soup.find("h1")
        if h1 is not None:
            title = h1.get_text(" ", strip=True) or None
    if title is None:
        og_title = soup.find("meta", attrs={"property": "og:title"})
        if og_title is not None and og_title.get("content"):
            title = og_title["content"].strip() or None
    if title is None:
        title_tag = soup.find("title")
        if title_tag is not None and title_tag.string:
            title = title_tag.string.strip() or None
    if title:
        title = _clean_page_title(title)
    if company is None:
        meta_tag = soup.find(
            "meta", attrs={"property": "og:site_name"}
        ) or soup.find("meta", attrs={"name": "author"})
        if meta_tag is not None and meta_tag.get("content"):
            company = _clean_company_name(meta_tag["content"])
    if company is not None:
        company = _clean_company_name(company)
    return {"title": title, "company": company, "city": city}


def _clean_company_name(name) -> str | None:
    """Trim hiring-site suffixes so og:site_name reads like a company."""
    if not name:
        return None
    value = str(name).strip()
    value = re.sub(
        r"(人才招聘|招聘官网|官方招聘|校园招聘|社会招聘|招聘|官网|careers?)$",
        "",
        value,
        flags=re.IGNORECASE,
    )
    return value.strip(" |·-—–") or None


def _clean_page_title(title: str) -> str:
    """Normalize a page title and keep the job-specific first segment."""
    normalized = re.sub(r"\s+", " ", title).strip()
    for separator in (" | ", " - ", " – ", " · ", " — ", " / "):
        if separator in normalized:
            normalized = normalized.split(separator, 1)[0].strip()
            break
    return normalized or title.strip()


_JOB_TEXT_KEYWORDS = (
    "职责",
    "要求",
    "岗位",
    "任职",
    "工作内容",
    "responsibilit",
    "requirement",
    "description",
    "qualification",
)


def _collect_long_strings(
    node,
    out: list[str],
    seen: set[str],
    limit: int,
) -> None:
    """Collect long, job-like strings from parsed SSR JSON."""
    if len(out) >= limit:
        return
    if isinstance(node, str):
        text = node.strip()
        if (
            len(text) >= 40
            and any(keyword in text.lower() for keyword in _JOB_TEXT_KEYWORDS)
        ):
            key = text[:200]
            if key not in seen:
                seen.add(key)
                out.append(text)
        return
    if isinstance(node, dict):
        for value in node.values():
            _collect_long_strings(value, out, seen, limit)
    elif isinstance(node, list):
        for value in node:
            _collect_long_strings(value, out, seen, limit)


def _json_script_text(soup: BeautifulSoup) -> str:
    """Extract readable JD text from SSR JSON embedded in script tags."""
    markers = (
        "__INITIAL_STATE__",
        "__NUXT__",
        "__APP_DATA__",
        "__SSR_DATA__",
        "__NEXT_DATA__",
    )
    out: list[str] = []
    seen: set[str] = set()
    for script in soup.find_all("script"):
        content = (script.string or script.get_text() or "").strip()
        if not content:
            continue
        parsed = None
        if content[:1] in ("{", "["):
            try:
                parsed = json.loads(content)
            except (UnicodeDecodeError, ValueError):
                parsed = None
        if parsed is None:
            for marker in markers:
                match = re.search(
                    re.escape(marker) + r"\s*=\s*(\{.*\})",
                    content,
                    re.S,
                )
                if match is None:
                    continue
                try:
                    parsed = json.loads(match.group(1))
                except (UnicodeDecodeError, ValueError):
                    parsed = None
                if parsed is not None:
                    break
        if parsed is None:
            continue
        _collect_long_strings(parsed, out, seen, 40)
        if len(out) >= 40:
            break
    return "\n\n".join(out)


def _select_first(soup: BeautifulSoup, selectors: tuple[str, ...]):
    for selector in selectors:
        node = soup.select_one(selector)
        if node is not None:
            return node
    return None


def _linkedin_job_text(soup: BeautifulSoup) -> str:
    body = _select_first(
        soup, (".show-more-less-html__markup", ".jobs-description__content")
    )
    if body is None:
        return _generic_job_text(soup)
    return body.get_text(separator="\n")


def _zhipin_job_text(soup: BeautifulSoup) -> str:
    body = _select_first(soup, (".job-sec-text", ".job-description"))
    if body is None:
        return _generic_job_text(soup)
    return body.get_text(separator="\n")


def _generic_job_text(soup: BeautifulSoup) -> str:
    ssr_text = _json_script_text(soup).strip()
    clean = BeautifulSoup(str(soup), "html.parser")
    for tag in clean(BOILERPLATE_TAGS):
        tag.decompose()
    candidates = [
        node
        for selector in _GENERIC_CONTENT_SELECTORS
        for node in clean.select(selector)
    ]
    if candidates:
        best = max(
            candidates,
            key=lambda node: len(node.get_text(" ", strip=True)),
        )
        text = best.get_text(separator="\n")
        if text.strip():
            return text
    if ssr_text:
        return ssr_text
    return clean.get_text(separator="\n")


SITE_HANDLERS = (
    (
        lambda host, path: (
            host == "linkedin.com" or host.endswith(".linkedin.com")
        )
        and path.startswith("/jobs/"),
        _linkedin_job_text,
    ),
    (
        lambda host, path: (
            host == "zhipin.com" or host.endswith(".zhipin.com")
        )
        and path.startswith("/job_detail/"),
        _zhipin_job_text,
    ),
)
