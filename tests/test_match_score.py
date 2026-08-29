"""Tests for the MVP-01 deterministic match scorer and match API."""

from __future__ import annotations

from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.job_library import JobLibraryStore
from resualign.jobs import JobRegistry
from resualign.match_scorer import (
    clamp100,
    compute_match_score,
    fallback_match_reason,
    snapshot_matches,
)
from resualign.settings_store import SettingsStore
from resualign.workspace import (
    ApplicationStore,
    MasterResumeStore,
    UserStore,
)


def _fixture_inputs():
    jd_text = "需要 Python 与 Redis，处理高并发后端服务"
    jd_profile = {
        "must_have_skills": ["Python", "Redis"],
        "business_scenarios": ["高并发"],
    }
    gap_report = {
        "missing_keywords": ["Redis", "3年经验"],
        "misaligned_emphasis": ["职责描述"],
    }
    eval_score = {"hallucination_detected": True}
    resume_text = "Python 后端工程师\n使用 FastAPI 构建服务"
    return jd_text, jd_profile, gap_report, eval_score, resume_text


def test_deterministic_four_dimension_score():
    jd_text, profile, gap, eval_score, resume = _fixture_inputs()
    detail = compute_match_score(
        jd_text,
        profile,
        gap,
        eval_score,
        resume,
        "resume-1",
    )
    assert detail["hard_skills"] == 70.0
    assert detail["scenario"] == 100.0
    assert detail["expression"] == 75.0
    assert detail["experience"] == 85.0
    assert detail["total"] == 81.5
    assert detail["version"] == 1
    assert detail["inputs_snapshot"]["master_resume_id"] == "resume-1"
    repeated = compute_match_score(
        jd_text,
        profile,
        gap,
        eval_score,
        resume,
        "resume-1",
    )
    assert repeated == detail


def test_clamp100_bounds_and_fallback_reason():
    assert clamp100(-5) == 0.0
    assert clamp100(140) == 100.0
    detail = {"total": 81.5}
    reason = fallback_match_reason(detail, ["Redis"])
    assert "81.5" in reason
    assert "建议优先投递" in reason


def test_snapshot_matches_detects_input_changes():
    jd_text, profile, gap, eval_score, resume = _fixture_inputs()
    detail = compute_match_score(
        jd_text,
        profile,
        gap,
        eval_score,
        resume,
        "resume-1",
    )
    assert snapshot_matches(detail, jd_text, resume, "resume-1")
    assert not snapshot_matches(detail, jd_text + " changed", resume, "resume-1")
    assert not snapshot_matches(detail, jd_text, resume, "resume-2")


def _save_api_state(tmp_path) -> dict:
    saved = {
        "_registry": api_module._registry,
        "_users": api_module._users,
        "_resumes": getattr(api_module, "_resumes", None),
        "_applications": getattr(api_module, "_applications", None),
        "_jobs": api_module._jobs,
        "_settings_store": getattr(api_module, "_settings_store", None),
        "_PERSONAL_MODE": api_module._PERSONAL_MODE,
    }
    db_path = tmp_path / "match-api.db"
    api_module._registry = JobRegistry(db_path=db_path)
    api_module._users = UserStore(db_path=db_path)
    api_module._resumes = MasterResumeStore(db_path=db_path)
    api_module._applications = ApplicationStore(db_path=db_path)
    api_module._jobs = JobLibraryStore(db_path=db_path)
    api_module._settings_store = SettingsStore(db_path=db_path)
    api_module._PERSONAL_MODE = False
    return saved


def _restore_api_state(saved: dict) -> None:
    for name, value in saved.items():
        setattr(api_module, name, value)


def _auth_headers(client: TestClient) -> dict[str, str]:
    client.post(
        "/api/auth/signup",
        json={"email": "match@example.com", "password": "password-123"},
    )
    token = client.post(
        "/api/auth/login",
        json={"email": "match@example.com", "password": "password-123"},
    ).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_match_api_fallback_recompute_and_stale(tmp_path, monkeypatch):
    client = TestClient(app)
    saved = _save_api_state(tmp_path)
    monkeypatch.setattr(
        "resualign.api.routers.jobs._llm_match_reason",
        lambda *args, **kwargs: None,
    )
    try:
        headers = _auth_headers(client)
        tenant = client.get("/api/auth/me", headers=headers).json()["user_id"]
        resume = api_module._resumes.create_master_resume(
            tenant,
            "Master",
            "Python 后端工程师\n使用 FastAPI 构建服务",
        )
        job = api_module._jobs.create_job(
            tenant_id=tenant,
            title="Backend",
            jd_text="需要 Python 与 Redis，处理高并发后端服务",
        )
        _, profile, gap, eval_score, _ = _fixture_inputs()
        api_module._jobs.update_job(
            tenant,
            job["job_id"],
            workbench_resume_id=resume["resume_id"],
            jd_profile=profile,
            gap_report=gap,
            eval_score=eval_score,
        )
        first = client.post(
            f"/api/jobs/{job['job_id']}/match",
            headers=headers,
        )
        assert first.status_code == 200
        body = first.json()
        assert body["status"] == "fallback"
        assert body["recomputed"] is True
        assert body["match_score"] == 81.5
        assert body["match_reason_source"] == "fallback"
        assert body["match_stale"] is False

        second = client.post(
            f"/api/jobs/{job['job_id']}/match",
            headers=headers,
        )
        assert second.json()["recomputed"] is False

        client.patch(
            f"/api/jobs/{job['job_id']}",
            json={"jd_text": "需要 Python 与 Redis 和高并发实时系统"},
            headers=headers,
        )
        fetched = client.get(
            f"/api/jobs/{job['job_id']}", headers=headers
        ).json()
        assert fetched["match_stale"] is True
        third = client.post(
            f"/api/jobs/{job['job_id']}/match",
            headers=headers,
        )
        assert third.json()["recomputed"] is True
        assert third.json()["match_stale"] is False
    finally:
        _restore_api_state(saved)


def test_match_api_blocked_without_resume(tmp_path):
    client = TestClient(app)
    saved = _save_api_state(tmp_path)
    try:
        headers = _auth_headers(client)
        tenant = client.get("/api/auth/me", headers=headers).json()["user_id"]
        job = api_module._jobs.create_job(
            tenant_id=tenant,
            title="Backend",
            jd_text="Python backend engineer.",
        )
        response = client.post(
            f"/api/jobs/{job['job_id']}/match",
            headers=headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "blocked"
        assert body["match_reason"] == "请先选择主简历并完成 JD 画像与差距分析"
    finally:
        _restore_api_state(saved)


def test_job_list_sort_by_match_score(tmp_path):
    client = TestClient(app)
    saved = _save_api_state(tmp_path)
    try:
        headers = _auth_headers(client)
        tenant = client.get("/api/auth/me", headers=headers).json()["user_id"]
        low = api_module._jobs.create_job(
            tenant_id=tenant,
            title="Low",
            jd_text="Low match role.",
        )
        high = api_module._jobs.create_job(
            tenant_id=tenant,
            title="High",
            jd_text="High match role.",
        )
        api_module._jobs.update_job(tenant, low["job_id"], match_score=40)
        api_module._jobs.update_job(tenant, high["job_id"], match_score=90)
        response = client.get(
            "/api/jobs?sort=match_score_desc",
            headers=headers,
        )
        assert response.status_code == 200
        jobs = response.json()
        assert [item["job_id"] for item in jobs] == [high["job_id"], low["job_id"]]
        assert client.get(
            "/api/jobs?sort=invalid", headers=headers
        ).status_code == 422
    finally:
        _restore_api_state(saved)


def test_keyword_coverage_score_ratio_and_missing():
    from resualign.match_scorer import keyword_coverage_score

    profile = {"must_have_skills": ["Python", "Redis", "Kubernetes"]}
    resume = "熟练使用 Python 与 redis，无容器经验"
    detail = keyword_coverage_score(profile, resume)
    assert detail["required"] == 3
    assert detail["matched"] == 2
    assert detail["ratio"] == 0.667
    assert detail["missing"] == ["Kubernetes"]


def test_keyword_coverage_score_aliases_and_no_skills():
    from resualign.match_scorer import keyword_coverage_score

    # 字面子串匹配（与原 gate 实现一致）：Go 会命中 Golang，属已知局限；
    # 未出现的关键词计入 missing
    assert keyword_coverage_score(
        {"required_skills": ["Go", "Kafka"]}, "Golang 微服务"
    )["missing"] == ["Kafka"]
    assert keyword_coverage_score({"skills": ["FastAPI"]}, "用 FastAPI 写服务")[
        "matched"
    ] == 1
    assert keyword_coverage_score({}, "任意简历") is None
    assert keyword_coverage_score(None, None) is None


def test_compute_match_score_includes_keyword_coverage():
    jd_text, profile, gap, eval_score, resume = _fixture_inputs()
    detail = compute_match_score(jd_text, profile, gap, eval_score, resume, "r1")
    # fixture 简历含 Python 不含 Redis（大小写不敏感命中其一）
    assert detail["keyword_coverage"]["required"] == 2
    assert detail["keyword_coverage"]["matched"] == 1
    assert detail["keyword_coverage"]["missing"] == ["Redis"]
    # 无技能画像时为 None，而不是伪装成零覆盖
    empty = compute_match_score(jd_text, {}, gap, eval_score, resume, "r1")
    assert empty["keyword_coverage"] is None
