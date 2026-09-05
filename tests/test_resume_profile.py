"""Structured resume profile: LLM extraction, staleness, manual edit."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.jobs import JobRegistry
from resualign.settings_store import SettingsStore
from resualign.workspace import (
    ApplicationStore,
    JobLibraryStore,
    MasterResumeStore,
    UserStore,
)

client = TestClient(app)
_auth_cache = None

RESUME = """陈振成 后端开发工程师
电话 138-0000-0000 ｜ 邮箱 chen@example.com
教育经历：广东理工学院 计算机科学与技术 本科 2020-2024
工作经历：某电商公司 后端开发工程师 2024-2025
负责订单与库存服务，QPS 峰值 5000。
技能：Java, Spring Boot, MySQL, Redis
"""

PROFILE_OUT = {
    "basic": {"name": "陈振成", "phone": "138-0000-0000",
              "email": "chen@example.com"},
    "education": [{"school": "广东理工学院", "major": "计算机科学与技术",
                   "degree": "本科", "start": "2020", "end": "2024"}],
    "work": [{"company": "某电商公司", "title": "后端开发工程师",
              "start": "2024", "end": "2025",
              "highlights": ["负责订单与库存服务"]}],
    "projects": [],
    "skills": ["Java", "Spring Boot", "MySQL", "Redis"],
    "summary": "",
}


@pytest.fixture(autouse=True)
def temp_api_state(tmp_path):
    global _auth_cache
    saved = {
        name: getattr(api_module, name)
        for name in (
            "_registry", "_users", "_resumes", "_applications", "_jobs",
            "_settings_store", "_PERSONAL_MODE", "_payloads",
            "_import_batches",
        )
    }
    db_path = tmp_path / "profile.db"
    api_module._registry = JobRegistry(db_path=db_path)
    api_module._users = UserStore(db_path=db_path)
    api_module._resumes = MasterResumeStore(db_path=db_path)
    api_module._applications = ApplicationStore(db_path=db_path)
    api_module._jobs = JobLibraryStore(db_path=db_path)
    api_module._settings_store = SettingsStore(db_path=db_path)
    api_module._PERSONAL_MODE = False
    api_module._payloads = {}
    api_module._import_batches = {}
    _auth_cache = None
    yield
    for name, value in saved.items():
        setattr(api_module, name, value)
    _auth_cache = None


def _auth_headers():
    global _auth_cache
    if _auth_cache is not None:
        return _auth_cache
    client.post(
        "/api/auth/signup",
        json={"email": "profile@example.com", "password": "password-123"},
    )
    r = client.post(
        "/api/auth/login",
        json={"email": "profile@example.com", "password": "password-123"},
    )
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _tenant_id():
    return client.get("/api/auth/me", headers=_auth_headers()).json()["user_id"]


def _create_resume():
    r = client.post(
        "/api/master-resumes",
        json={"title": "主简历", "content": RESUME},
        headers=_auth_headers(),
    )
    assert r.status_code == 201
    return r.json()


class _FakeProfileClient:
    """chat_structured 假 client：返回预置档案，记录调用。"""

    calls = 0

    def chat_structured(self, system, user, schema_model, model=None):
        _FakeProfileClient.calls += 1
        return PROFILE_OUT

    def close(self):
        pass


def test_profile_extract_persists_and_marks_fresh(monkeypatch):
    resume = _create_resume()
    fake = _FakeProfileClient()

    class _Factory:
        def __init__(self, config, timeout=None, max_retries=None, **kw):
            pass

        def __enter__(self):
            return fake

        def __exit__(self, *a):
            return False

        def close(self):
            pass

    import resualign.llm as _llm

    monkeypatch.setattr(_llm, "OpenAIClient", lambda *a, **kw: fake)
    monkeypatch.setattr(
        "resualign.api.build_config",
        lambda: type("C", (), {"is_llm_configured": True, "model": "test-m"})(),
    )
    r = client.post(
        f"/api/master-resumes/{resume['resume_id']}/profile/extract",
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    assert r.json()["extracted_with"] == "test-m"

    # GET：档案在且不 stale
    r = client.get(
        f"/api/master-resumes/{resume['resume_id']}/profile",
        headers=_auth_headers(),
    )
    profile = r.json()["profile"]
    assert profile["data"]["basic"]["name"] == "陈振成"
    assert profile["stale"] is False
    # 证件号绝不自动抽取
    assert profile["data"]["basic"]["id_number"] == ""


def test_profile_stale_when_content_changes(monkeypatch):
    resume = _create_resume()
    tenant = _tenant_id()
    api_module._resumes.save_resume_profile(
        tenant,
        resume["resume_id"],
        PROFILE_OUT,
        api_module._content_sha256(RESUME),
        "test-m",
    )
    # 内容变更 → stale
    api_module._resumes.update_master_resume(
        tenant,
        resume["resume_id"],
        content=RESUME + "\n新增一段经历",
    )
    r = client.get(
        f"/api/master-resumes/{resume['resume_id']}/profile",
        headers=_auth_headers(),
    )
    assert r.json()["profile"]["stale"] is True


def test_profile_manual_edit_roundtrip():
    resume = _create_resume()
    edited = {
        "basic": {"name": "陈振成", "phone": "139-1111-2222", "email": "",
                  "gender": "", "birth": "", "location": "", "id_number": "110...X"},
        "education": [],
        "work": [],
        "projects": [],
        "skills": ["Java"],
        "summary": "手动补充的总结",
    }
    r = client.patch(
        f"/api/master-resumes/{resume['resume_id']}/profile",
        json={"profile": edited},
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    assert r.json()["profile"]["data"]["basic"]["phone"] == "139-1111-2222"
    assert r.json()["profile"]["data"]["basic"]["id_number"] == "110...X"

    # GET 反映编辑结果
    r = client.get(
        f"/api/master-resumes/{resume['resume_id']}/profile",
        headers=_auth_headers(),
    )
    assert r.json()["profile"]["data"]["summary"] == "手动补充的总结"


def test_profile_extract_rejects_empty_content():
    # 创建层已拒绝空白内容（422），此处验证 store 直插空内容后抽取仍兜底
    tenant = _tenant_id()
    import time as _time
    job_store = api_module._resumes
    resume_id = "profile-empty-test"
    job_store.save_resume_profile(
        tenant, resume_id, {"basic": {}, "education": [], "work": [],
                            "projects": [], "skills": [], "summary": ""},
        "sha", "m",
    )  # 无此简历 → save 返回 None 不报错
    api_module._payloads = {}
    # 直接构造空内容简历（绕过创建层校验）
    import sqlite3 as _sq
    conn = _sq.connect(str(job_store.db_path))
    now = _time.time()
    conn.execute(
        "INSERT INTO master_resumes (resume_id, tenant_id, title, "
        "current_version, created_at, updated_at) VALUES (?, ?, ?, 1, ?, ?)",
        (resume_id, tenant, "空简历", now, now),
    )
    conn.commit()
    conn.close()
    r = client.post(
        f"/api/master-resumes/{resume_id}/profile/extract",
        headers=_auth_headers(),
    )
    assert r.status_code == 422


def test_enrich_profile_from_text_fills_contact_fields():
    """缺陷 #2 回归：LLM 漏抽 basic 时，规则兜底从简历文本填充电话/邮箱。

    真实格式来源：测试报告里那份「电话 138-0000-0000 ｜ 邮箱 xxx」分隔符行简历。
    """
    from resualign.local_fallback import enrich_profile_from_text

    content = """陈振成 后端开发工程师
电话 138-0000-0000 ｜ 邮箱 chen@example.com
坐标 上海
教育经历：广东理工学院 计算机科学与技术 本科 2020-2024
技能：Java, Spring Boot
"""
    profile = {
        "basic": {"name": "", "phone": "", "email": "", "gender": "",
                  "birth": "", "location": "", "id_number": ""},
        "education": [], "work": [], "projects": [], "skills": [], "summary": "",
    }
    enriched = enrich_profile_from_text(content, profile)
    assert enriched["basic"]["phone"] == "138-0000-0000"
    assert enriched["basic"]["email"] == "chen@example.com"
    assert enriched["basic"]["location"] == "上海"


def test_enrich_profile_never_overwrites_llm_values():
    """LLM 已抽到的字段不被规则覆盖（规则只兜底空位）。"""
    from resualign.local_fallback import enrich_profile_from_text

    content = "电话 139-1111-2222 ｜ 邮箱 other@example.com"
    profile = {
        "basic": {"name": "已有名字", "phone": "138-0000-0000", "email": "",
                  "gender": "", "birth": "", "location": "", "id_number": ""},
        "education": [], "work": [], "projects": [], "skills": [], "summary": "",
    }
    enriched = enrich_profile_from_text(content, profile)
    assert enriched["basic"]["phone"] == "138-0000-0000"  # LLM 值保留
    assert enriched["basic"]["email"] == "other@example.com"  # 空位被兜底
    assert enriched["basic"]["name"] == "已有名字"


def test_extract_enriches_basic_from_text_when_llm_misses(monkeypatch):
    """缺陷 #2 端到端：LLM 返回 basic 全空时，落库前被规则兜底填充。"""
    content = """李四 全栈工程师
电话 139-1111-2222 ｜ 邮箱 lisi@example.com
坐标 北京
技能：Vue, FastAPI
"""
    resume = client.post(
        "/api/master-resumes",
        json={"title": "兜底简历", "content": content},
        headers=_auth_headers(),
    ).json()

    # 模拟 LLM 只抽到 skills，basic 全空（漏抽场景）
    class _SparseClient:
        def chat_structured(self, system, user, schema_model, model=None):
            return {"basic": {}, "education": [], "work": [], "projects": [],
                    "skills": ["Vue"], "summary": ""}

        def close(self):
            pass

    import resualign.llm as _llm
    monkeypatch.setattr(_llm, "OpenAIClient", lambda *a, **kw: _SparseClient())
    monkeypatch.setattr(
        "resualign.api.build_config",
        lambda: type("C", (), {"is_llm_configured": True, "model": "test-m"})(),
    )
    r = client.post(
        f"/api/master-resumes/{resume['resume_id']}/profile/extract",
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    basic = r.json()["profile"]["data"]["basic"]
    assert basic["phone"] == "139-1111-2222"
    assert basic["email"] == "lisi@example.com"
    assert basic["location"] == "北京"
