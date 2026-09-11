"""CORS：油猴抓取脚本跨源访问的预检与响应头契约。

根因背景（2026-09-10 实测）：resualign-collector.user.js 运行在外部招聘
网站页面上，用浏览器 fetch 跨源 POST /api/jobs/local-ingest（自定义
X-ResuAlign-Token 头）。无 CORSMiddleware 时预检 OPTIONS 直接 405，
请求在到达业务逻辑前被浏览器掐死——curl/pytest 全绿但只有真实浏览器死。
"""

import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.settings_store import SettingsStore
from resualign.workspace import JobLibraryStore, UserStore

client = TestClient(app)

ORIGIN = "https://www.shixiseng.com"
PREFLIGHT_HEADERS = {
    "Origin": ORIGIN,
    "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": "content-type,x-resualign-token",
}


@pytest.fixture(autouse=True)
def temp_stores(tmp_path):
    saved = {
        "users": api_module._users,
        "jobs": api_module._jobs,
        "settings": getattr(api_module, "_settings_store", None),
        "import_batches": getattr(api_module, "_import_batches", {}),
    }
    db_path = tmp_path / "cors.db"
    api_module._users = UserStore(db_path=db_path)
    api_module._jobs = JobLibraryStore(db_path=db_path)
    api_module._settings_store = SettingsStore(db_path=db_path)
    api_module._import_batches = {}
    for limiter in (api_module._import_rate_limiter,):
        limiter.reset()
    yield
    api_module._users = saved["users"]
    api_module._jobs = saved["jobs"]
    api_module._settings_store = saved["settings"]
    api_module._import_batches = saved["import_batches"]
    for limiter in (api_module._import_rate_limiter,):
        limiter.reset()


def _token() -> str:
    body = client.get("/api/settings").json()
    return body["local_ingest_token"]


def test_preflight_options_returns_200_with_token_header_allowed():
    """浏览器预检必须 200 且放行 X-ResuAlign-Token，否则油猴永远发不出 POST。"""
    response = client.options(
        "/api/jobs/local-ingest", headers=PREFLIGHT_HEADERS
    )
    assert response.status_code == 200
    allow_origin = response.headers.get("access-control-allow-origin")
    assert allow_origin in ("*", ORIGIN)
    allow_headers = response.headers.get("access-control-allow-headers", "")
    assert "x-resualign-token" in allow_headers.lower()
    assert "content-type" in allow_headers.lower()


def test_cors_headers_present_on_actual_post_response():
    """真实 POST 的响应也要带 allow-origin，浏览器才会把 body 交给油猴脚本。"""
    response = client.post(
        "/api/jobs/local-ingest",
        headers={
            "Origin": ORIGIN,
            "X-ResuAlign-Token": _token(),
        },
        json={
            "title": "CORS 后端工程师",
            "jd_text": "负责高并发后端服务开发，熟悉 Python 与 FastAPI。",
            "site": "shixiseng",
        },
    )
    assert response.status_code == 200, response.text
    assert response.headers.get("access-control-allow-origin") in ("*", ORIGIN)
    assert response.json()["status"] in ("created", "exists")


def test_missing_token_still_401_under_cors():
    """CORS 放行的是浏览器通道，不是业务鉴权：无 token 依旧 401。"""
    response = client.post(
        "/api/jobs/local-ingest",
        headers={"Origin": ORIGIN},
        json={"jd_text": "x"},
    )
    assert response.status_code == 401
    detail = response.json()["detail"]
    assert detail["code"] == "missing_token"
    assert response.headers.get("access-control-allow-origin") in ("*", ORIGIN)


def test_preflight_rejects_unlisted_methods():
    """未放行的方法（如 DELETE 跨源）预检不予通过。"""
    response = client.options(
        "/api/jobs/local-ingest",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "DELETE",
        },
    )
    assert response.status_code == 400
