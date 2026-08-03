"""Job description crawler with SSRF-safe fetching and size limits."""

from __future__ import annotations

import base64
import html
import http.client
import http.cookies
import ipaddress
import json
import re
import socket
import ssl
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "ResuAlign/1.0",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
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
) -> str:
    """Fetch a job description URL and return its cleaned plain text."""
    current_url = url
    cookies: dict[str, str] = {}
    for _ in range(MAX_REDIRECTS + 1):
        _validate_target(current_url)
        pinned_ip = _resolve_public_host(
            urlparse(current_url).hostname or ""
        )
        headers = dict(HEADERS)
        if cookies:
            headers["Cookie"] = "; ".join(
                f"{name}={value}" for name, value in cookies.items()
            )
        try:
            with _fetch_stream(
                current_url,
                timeout=timeout,
                ip=pinned_ip,
                headers=headers,
            ) as response:
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
                content = _read_limited(
                    response, MAX_RESPONSE_BYTES, current_url
                )
                encoding = (
                    getattr(response, "encoding", None)
                    or getattr(response, "charset_encoding", None)
                    or "utf-8"
                )
                break
        except CrawlError:
            raise
        except httpx.HTTPError as e:
            raise CrawlError(
                f"Failed to fetch {current_url}: {e}",
                category="fetch",
                url=current_url,
            ) from e
    else:
        raise CrawlError(
            f"Too many redirects at {url}",
            category="http",
            url=url,
        )

    soup = BeautifulSoup(_decode_content(content, encoding), "html.parser")

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
            url, soup, pinned_ip, timeout, meta, cookies
        )

    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    text = "\n".join(lines).strip()
    if not text:
        raise CrawlError(f"Empty content at {url}", category="empty", url=url)
    return text


def _validate_target(url: str) -> None:
    """Reject unsupported schemes, missing hosts, and private literals."""
    if not isinstance(url, str) or not url.strip():
        raise CrawlError("URL is required", category="url", url=url)
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise CrawlError(
            f"Unsupported URL scheme: {parsed.scheme!r}",
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
    """Open a streaming request; redirects are handled by the caller."""
    request_headers = headers or HEADERS
    if ip:
        return _PinnedStream(
            url,
            timeout=timeout,
            ip=ip,
            headers=request_headers,
            method=method,
            json_body=json_body,
        )
    return httpx.stream(
        method,
        url,
        headers=request_headers,
        timeout=timeout,
        follow_redirects=False,
        json=json_body,
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
        with _fetch_stream(
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
        ) as response:
            if response.status_code != 200:
                return _generic_job_text(soup)
            content = _read_limited(response, MAX_RESPONSE_BYTES, api_url)
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
        with _fetch_stream(api_url, timeout=timeout, ip=ip) as response:
            if response.status_code != 200:
                return _generic_job_text(soup)
            content = _read_limited(response, MAX_RESPONSE_BYTES, api_url)
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
            detail.get("description"),
            detail.get("requirement"),
        )
        if part
    ]
    if not parts:
        return _generic_job_text(soup)
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
            company = meta_tag["content"]
    return {"title": title, "company": company, "city": city}


def _clean_page_title(title: str) -> str:
    """Normalize a page title and keep the job-specific first segment."""
    normalized = re.sub(r"\s+", " ", title).strip()
    for separator in (" | ", " - ", " – ", " · ", " — ", " / "):
        if separator in normalized:
            normalized = normalized.split(separator, 1)[0].strip()
            break
    return normalized or title.strip()


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
