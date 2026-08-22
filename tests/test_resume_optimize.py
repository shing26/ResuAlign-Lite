"""Tests for the xzjobs-style resume optimization flow.

Covers:
- ``extract_project_modules`` entry splitting (Chinese multi-project resume)
- ``build_overview`` local, zero-LLM overall analysis (with/without JD)
- ``polish_project_module`` per-module LLM polish (success + failure modes)
- ``module_failure_detail`` readable per-module error messages (402/401/429)
- ``run_resume_optimize`` job runner: per-module failure isolation
- API: queue -> run -> poll (overview + modular polish), apply -> new version,
  apply 422/404 scenarios
"""

import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.jobs import JobRegistry
from resualign.llm import LLMResponseError
from resualign.resume_optimize import (
    POLISH_PROMPT,
    build_overview,
    extract_project_modules,
    module_failure_detail,
    polish_project_module,
    polish_timeout,
)
from resualign.settings_store import SettingsStore
from resualign.workspace import UserStore

from .conftest import MockLLMClient
from .test_api import _config

client = TestClient(app)
_auth_cache = None

SAMPLE_RESUME = (
    "张三\n"
    "13800138000\n"
    "zhangsan@example.com\n"
    "\n"
    "个人简介\n"
    "五年后端开发经验，专注高并发服务。\n"
    "\n"
    "教育背景\n"
    "2015-2019 某某大学 计算机科学与技术 本科\n"
    "\n"
    "技能\n"
    "Python, Redis, Docker, Kubernetes\n"
    "\n"
    "项目经历\n"
    "2023.01 - 2024.06 订单中台 | 后端负责人\n"
    "- 负责订单服务模块开发，使用 Redis 缓存热点数据，QPS 提升 30%，接口耗时降低 40%\n"
    "- 使用 Docker 部署服务，通过 CI/CD 流水线发布\n"
    "- 参与数据库索引优化，慢查询数量下降 50%\n"
    "\n"
    "2022.01 - 2022.12 数据分析平台 | 核心开发\n"
    "- 使用 Python 搭建数据处理流水线，日处理数据 1000 万条\n"
    "\n"
    "工作经历\n"
    "2021.01 - 2022.01 某某科技 | 后端工程师\n"
    "- 负责用户权限模块设计与开发\n"
)


@pytest.fixture(autouse=True)
def temp_job_store(tmp_path):
    """Same store isolation as test_api.py so API tests never touch real data."""
    global _auth_cache
    saved_registry = api_module._registry
    saved_users = api_module._users
    saved_personal_mode = api_module._PERSONAL_MODE
    saved_payloads = getattr(api_module, "_payloads", {})
    saved_settings = getattr(api_module, "_settings_store", None)
    db_path = tmp_path / "api.db"
    api_module._registry = JobRegistry(db_path=db_path)
    api_module._users = UserStore(db_path=db_path)
    api_module._settings_store = SettingsStore(db_path=db_path)
    api_module._PERSONAL_MODE = False
    api_module._payloads = {}
    api_module._import_batches = {}
    for limiter in (
        api_module._auth_rate_limiter,
        api_module._analyze_rate_limiter,
        api_module._import_rate_limiter,
    ):
        limiter.reset()
    _auth_cache = None
    yield
    api_module._registry = saved_registry
    api_module._users = saved_users
    api_module._PERSONAL_MODE = saved_personal_mode
    api_module._payloads = saved_payloads
    api_module._settings_store = saved_settings
    api_module._import_batches = {}
    for limiter in (
        api_module._auth_rate_limiter,
        api_module._analyze_rate_limiter,
        api_module._import_rate_limiter,
    ):
        limiter.reset()
    _auth_cache = None


def _auth_headers():
    """Sign up a fresh user for this module's tests and return bearer headers."""
    global _auth_cache
    if _auth_cache is not None:
        return _auth_cache
    r = client.post(
        "/api/auth/signup",
        json={"email": "tester@example.com", "password": "password-123"},
    )
    assert r.status_code == 201
    r = client.post(
        "/api/auth/login",
        json={"email": "tester@example.com", "password": "password-123"},
    )
    assert r.status_code == 200
    _auth_cache = {"Authorization": f"Bearer {r.json()['token']}"}
    return _auth_cache


# ---------------------------------------------------------------------------
# Entry parsing
# ---------------------------------------------------------------------------

def test_extract_project_modules_splits_chinese_resume():
    modules = extract_project_modules(SAMPLE_RESUME)
    assert len(modules) == 3
    assert modules[0]["module"] == "项目经历"
    assert modules[0]["index"] == 0
    assert "订单中台" in modules[0]["title"]
    assert "QPS 提升 30%" in modules[0]["original"]
    assert modules[1]["module"] == "项目经历"
    assert modules[1]["index"] == 1
    assert "数据分析平台" in modules[1]["title"]
    assert "1000 万条" in modules[1]["original"]
    assert modules[2]["module"] == "工作经历"
    assert modules[2]["index"] == 0
    assert "用户权限模块" in modules[2]["original"]


def test_extract_project_modules_empty_and_headingless():
    assert extract_project_modules("") == []
    assert extract_project_modules("张三\n技能\nPython") == []
    # Non-experience sections never become modules.
    assert extract_project_modules("教育背景\n2015-2019 某某大学 本科") == []


def test_extract_project_modules_keeps_markdown_title():
    text = (
        "项目经历\n"
        "## 智能客服系统\n"
        "2023.01 - 2023.06\n"
        "- 使用 Python 开发意图识别模块\n"
    )
    modules = extract_project_modules(text)
    assert len(modules) == 1
    assert "智能客服系统" in modules[0]["title"]
    assert "意图识别" in modules[0]["original"]


# ---------------------------------------------------------------------------
# Overview (local, deterministic)
# ---------------------------------------------------------------------------

def test_build_overview_local_no_llm():
    result = build_overview(SAMPLE_RESUME)
    assert result["generated_by"] == "local-rules"
    assert isinstance(result["score"], int)
    assert result["verdict"] in ("优秀", "建议优化", "需重点优化")
    assert result["skills"]
    assert isinstance(result["issues"], list)
    assert result["project_count"] == 3
    assert "项目经历" in result["sections_found"]
    assert "工作经历" in result["sections_found"]
    assert result["highlights"]
    assert any("QPS" in h or "30%" in h for h in result["highlights"])
    assert result["jd"] is None


def test_build_overview_empty_resume():
    result = build_overview("")
    assert result["score"] == 0
    assert result["project_count"] == 0
    assert result["sections_found"] == []
    assert result["highlights"] == []
    assert result["issues"]


def test_build_overview_with_jd_keywords():
    result = build_overview(SAMPLE_RESUME, jd_text="Python Redis Kubernetes 微服务")
    jd = result["jd"]
    assert jd is not None
    assert jd["provided"] is True
    assert "Python" in jd["matched_keywords"]
    assert "Redis" in jd["matched_keywords"]
    assert "微服务" in jd["unmatched_keywords"]


# ---------------------------------------------------------------------------
# Module polish
# ---------------------------------------------------------------------------

def _module(original="订单中台\n- 负责订单服务模块开发，QPS 提升 30%"):
    return {
        "module": "项目经历",
        "index": 0,
        "title": "订单中台",
        "original": original,
    }


def test_polish_project_module_success():
    mock = MockLLMClient(
        [
            {
                "optimized": "订单中台\n- 主导订单服务模块开发，使用 Redis 缓存热点数据，QPS 提升 30%",
                "rationale": "将“负责”改为“主导”，动词更有力量",
            }
        ]
    )
    result = polish_project_module(mock, _module())
    assert result["status"] == "ok"
    assert result["error"] is None
    assert result["rationale"] == "将“负责”改为“主导”，动词更有力量"
    assert result["module"] == "项目经历"
    assert result["index"] == 0
    assert mock.call_count == 1


def test_polish_project_module_empty_response_raises():
    mock = MockLLMClient([{}])
    with pytest.raises(LLMResponseError):
        polish_project_module(mock, _module())


def test_polish_project_module_short_content_raises():
    mock = MockLLMClient([{"optimized": "x", "rationale": "y"}])
    with pytest.raises(LLMResponseError):
        polish_project_module(mock, _module(original="太短"))


def test_polish_timeout_is_number():
    assert isinstance(polish_timeout(), float)
    assert polish_timeout() > 0


def test_module_failure_detail_readabilities():
    assert "欠费" in module_failure_detail(
        LLMResponseError("OpenAI error 402: Insufficient Balance"), "订单中台"
    )
    assert "API Key" in module_failure_detail(
        LLMResponseError("401 invalid api key"), "订单中台"
    )
    assert "限流" in module_failure_detail(
        LLMResponseError("429 rate limit exceeded"), "订单中台"
    )
    assert "超时" in module_failure_detail(
        LLMResponseError("request timed out"), "订单中台"
    )
    assert "订单中台" in module_failure_detail(
        LLMResponseError("boom"), "订单中台"
    )


# ---------------------------------------------------------------------------
# Job runner isolation
# ---------------------------------------------------------------------------

class _FakeOptimizeClient:
    """Context-managed chat_json fake; an Exception response raises it."""

    def __init__(self, responses):
        self.responses = responses
        self.call_count = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def chat_json(self, system, user, model=None):
        response = self.responses[min(self.call_count, len(self.responses) - 1)]
        self.call_count += 1
        if isinstance(response, Exception):
            raise response
        return {"optimized": response, "rationale": "ok"}


def _patched_config_client(responses):
    return patch("resualign.api.build_config", return_value=_config()), patch(
        "resualign.api.OpenAIClient", return_value=_FakeOptimizeClient(responses)
    )


def test_run_resume_optimize_isolates_module_failures():
    stages = []
    payload = {"resume_text": SAMPLE_RESUME, "jd_text": "Python Redis"}
    with patch("resualign.api.build_config", return_value=_config()), patch(
        "resualign.api.OpenAIClient",
        return_value=_FakeOptimizeClient(
            [
                "订单中台（润色后）",
                LLMResponseError("OpenAI error 402: Insufficient Balance"),
                "某某科技（润色后）",
            ]
        ),
    ):
        result = api_module._run_resume_optimize(
            payload, lambda stage, message: stages.append((stage, message)), "t1"
        )
    assert result["overview"]["project_count"] == 3
    assert result["overview"]["generated_by"] == "local-rules"
    assert result["llm_used"] is True
    assert result["model"] == "test-model"
    assert any(stage == "overview" for stage, _ in stages)
    assert any(stage == "polishing" for stage, _ in stages)
    oks = [m for m in result["modules"] if m["status"] == "ok"]
    failed = [m for m in result["modules"] if m["status"] == "failed"]
    assert len(oks) == 2
    assert len(failed) == 1
    assert "欠费" in failed[0]["error"]
    assert "订单中台" in oks[0]["optimized"]
    # Failed module still carries basics for a later retry/apply.
    assert failed[0]["module"] == "项目经历"
    assert failed[0]["index"] == 1


def test_run_resume_optimize_no_modules_no_llm():
    payload = {
        "resume_text": "张三\n教育背景\n2015-2019 某某大学 本科\n技能\nPython"
    }
    result = api_module._run_resume_optimize(payload, None, "t1")
    assert result["modules"] == []
    assert result["llm_used"] is False
    assert result["overview"]["project_count"] == 0
    assert "未识别到" in (result["note"] or "")


# ---------------------------------------------------------------------------
# API: queue -> run -> poll
# ---------------------------------------------------------------------------

def _create_resume(content=SAMPLE_RESUME, title="优化测试简历"):
    r = client.post(
        "/api/master-resumes",
        json={"title": title, "content": content},
        headers=_auth_headers(),
    )
    assert r.status_code == 201
    return r.json()


def _queue_optimize(resume_id, jd_text=None):
    with patch("resualign.api._run_job"), patch(
        "resualign.api.build_config", return_value=_config()
    ):
        r = client.post(
            f"/api/master-resumes/{resume_id}/optimize",
            json={"jd_text": jd_text},
            headers=_auth_headers(),
        )
    assert r.status_code == 202
    return r.json()


def _poll_until_finished(job_id, timeout=3.0):
    deadline = time.monotonic() + timeout
    data = None
    while time.monotonic() < deadline:
        r = client.get(f"/api/jobs/{job_id}", headers=_auth_headers())
        assert r.status_code == 200
        data = r.json()
        if data["status"] in ("succeeded", "failed"):
            return data
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not finish in {timeout}s: {data}")


def test_optimize_api_queues_and_succeeds():
    resume = _create_resume()
    body = _queue_optimize(resume["resume_id"], jd_text="Python Redis")
    job_id = body["job_id"]
    with patch("resualign.api.build_config", return_value=_config()), patch(
        "resualign.api.OpenAIClient",
        return_value=_FakeOptimizeClient(["优化一", "优化二", "优化三"]),
    ):
        api_module._run_job(job_id)
    snapshot = _poll_until_finished(job_id)
    assert snapshot["status"] == "succeeded"
    result = snapshot["result"]
    assert result["overview"]["project_count"] == 3
    assert result["overview"]["jd"]["matched_keywords"] == ["Python", "Redis"]
    assert [m["status"] for m in result["modules"]] == ["ok", "ok", "ok"]


def test_optimize_api_missing_resume_404():
    r = client.post(
        "/api/master-resumes/missing/optimize",
        json={},
        headers=_auth_headers(),
    )
    assert r.status_code == 404


def test_optimize_api_unconfigured_llm_503():
    resume = _create_resume()
    with patch("resualign.api._run_job"), patch(
        "resualign.api.build_config",
        return_value=_config(api_key=""),
    ):
        r = client.post(
            f"/api/master-resumes/{resume['resume_id']}/optimize",
            json={},
            headers=_auth_headers(),
        )
    assert r.status_code == 503
    assert "LLM" in r.json()["detail"]


# ---------------------------------------------------------------------------
# API: apply accepted items
# ---------------------------------------------------------------------------

def test_apply_optimize_saves_new_version():
    resume = _create_resume()
    modules = extract_project_modules(SAMPLE_RESUME)
    items = [
        {
            "module": m["module"],
            "index": m["index"],
            "optimized": m["original"] + "\n- 润色后的补充要点（举例）",
        }
        for m in modules
    ]
    r = client.post(
        f"/api/master-resumes/{resume['resume_id']}/optimize/apply",
        json={"items": items},
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["applied_count"] == len(modules)
    detail = client.get(
        f"/api/master-resumes/{resume['resume_id']}", headers=_auth_headers()
    ).json()
    assert "润色后的补充要点（举例）" in detail["content"]
    # Unrelated text is untouched: contact/education still present.
    assert "13800138000" in detail["content"]


def test_apply_optimize_duplicate_item_422():
    resume = _create_resume()
    items = [
        {"module": "项目经历", "index": 0, "optimized": "A"},
        {"module": "项目经历", "index": 0, "optimized": "B"},
    ]
    r = client.post(
        f"/api/master-resumes/{resume['resume_id']}/optimize/apply",
        json={"items": items},
        headers=_auth_headers(),
    )
    assert r.status_code == 422
    assert "重复" in r.json()["detail"]


def test_apply_optimize_missing_module_422():
    resume = _create_resume()
    items = [{"module": "项目经历", "index": 99, "optimized": "A"}]
    r = client.post(
        f"/api/master-resumes/{resume['resume_id']}/optimize/apply",
        json={"items": items},
        headers=_auth_headers(),
    )
    assert r.status_code == 422
    assert "重新运行优化" in r.json()["detail"]


def test_apply_optimize_ambiguous_original_422():
    # Two entries are byte-identical -> a single apply cannot know which one.
    content = (
        "项目经历\n"
        "项目A\n"
        "- 负责开发\n"
        "\n"
        "项目A\n"
        "- 负责开发\n"
    )
    resume = _create_resume(content=content)
    items = [{"module": "项目经历", "index": 0, "optimized": "替换后内容"}]
    r = client.post(
        f"/api/master-resumes/{resume['resume_id']}/optimize/apply",
        json={"items": items},
        headers=_auth_headers(),
    )
    assert r.status_code == 422
    assert "原文不唯一" in r.json()["detail"]


def test_apply_optimize_empty_items_422():
    resume = _create_resume()
    r = client.post(
        f"/api/master-resumes/{resume['resume_id']}/optimize/apply",
        json={"items": []},
        headers=_auth_headers(),
    )
    assert r.status_code == 422