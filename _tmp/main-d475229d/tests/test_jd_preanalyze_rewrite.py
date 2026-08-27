"""T5: JD-only preanalyze, bullet rewrite, and provenance states."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.cache import ContentCache
from resualign.jobs import JobRegistry
from resualign.models import (
    DiffItem,
    GapReport,
    JDProfile,
    ResuAlignConfig,
)
from resualign.settings_store import SettingsStore
from resualign.tailor import (
    parse_diff_with_provenance,
    tailor_resume,
)
from resualign.workspace import (
    ApplicationStore,
    JobLibraryStore,
    MasterResumeStore,
    UserStore,
)

client = TestClient(app)
_auth_cache = None


def _config(api_key: str = "sk-test") -> ResuAlignConfig:
    return ResuAlignConfig(
        provider="deepseek",
        api_key=api_key,
        model="test-model",
    )


@pytest.fixture(autouse=True)
def temp_stores(tmp_path):
    global _auth_cache
    saved = {
        name: getattr(api_module, name)
        for name in (
            "_registry",
            "_users",
            "_resumes",
            "_applications",
            "_jobs",
            "_settings_store",
            "_session_store",
            "_PERSONAL_MODE",
            "_payloads",
        )
    }
    db_path = tmp_path / "preanalyze.db"
    api_module._registry = JobRegistry(db_path=db_path)
    api_module._users = UserStore(db_path=db_path)
    api_module._resumes = MasterResumeStore(db_path=db_path)
    api_module._applications = ApplicationStore(db_path=db_path)
    api_module._jobs = JobLibraryStore(db_path=db_path)
    api_module._settings_store = SettingsStore(db_path=db_path)
    api_module._session_store = api_module._workbench_service.WorkstationSessionStore()
    api_module._PERSONAL_MODE = False
    api_module._payloads = {}
    _auth_cache = None
    yield
    for name, value in saved.items():
        setattr(api_module, name, value)
    _auth_cache = None


def _auth_headers() -> dict[str, str]:
    global _auth_cache
    if _auth_cache is not None:
        return _auth_cache
    client.post(
        "/api/auth/signup",
        json={"email": "preanalyze@example.com", "password": "password-123"},
    )
    token = client.post(
        "/api/auth/login",
        json={"email": "preanalyze@example.com", "password": "password-123"},
    ).json()["token"]
    _auth_cache = {"Authorization": f"Bearer {token}"}
    return _auth_cache


def _create_job() -> dict:
    with patch("resualign.api._classify_job", return_value={}):
        return client.post(
            "/api/jobs",
            json={
                "title": "Backend Engineer",
                "jd_text": (
                    "Python backend engineer with Redis "
                    f"{time.time_ns()}."
                ),
            },
            headers=_auth_headers(),
        ).json()


def _create_resume() -> dict:
    return client.post(
        "/api/master-resumes",
        json={
            "title": "Master Resume",
            "content": "Python developer with FastAPI.",
        },
        headers=_auth_headers(),
    ).json()


class _CountingProfileClient:
    """Minimal fake client for cache/provenance unit checks."""

    strict_provenance = True

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def chat_json(self, system, user, model=None):
        self.calls += 1
        return self.responses.pop(0)


def test_diff_provenance_states_and_span_lookup():
    resume = "Python developer.\nBuilt Redis caching."
    verified, ok = parse_diff_with_provenance(
        {
            "type": "modify",
            "original": "Python developer.",
            "proposed": "Python developer with FastAPI.",
            "provenance_quote": "Python\ndeveloper.",
        },
        resume,
    )
    assert ok is True
    assert verified.provenance_state == "verified"
    assert verified.source_span is not None

    missing, ok = parse_diff_with_provenance(
        {
            "type": "modify",
            "original": "Python developer.",
            "proposed": "Java developer.",
            "provenance_quote": "No such sentence.",
        },
        resume,
    )
    assert ok is False
    assert missing.provenance_state == "missing"

    added, ok = parse_diff_with_provenance(
        {"type": "add", "original": "", "proposed": "Led a team."},
        resume,
    )
    assert ok is False
    assert added.provenance_state == "missing"

    pending, ok = parse_diff_with_provenance(
        {"type": "modify", "original": "Python developer.", "proposed": "X."},
        resume,
    )
    assert ok is False
    assert pending.provenance_state == "pending_review"


def test_tailor_add_without_source_goes_to_invalid_diffs():
    client_fake = _CountingProfileClient(
        responses=[
            {
                "sections": {"experience": "Built services"},
                "diffs": [
                    {
                        "type": "modify",
                        "original": "Python dev",
                        "proposed": "Built services using Java",
                        "reason": "match",
                        "confidence": "high",
                        "provenance_quote": "Python dev",
                    },
                    {
                        "type": "add",
                        "original": "",
                        "proposed": "Invented Kubernetes",
                        "reason": "fill gap",
                        "confidence": "low",
                    },
                ],
            }
        ]
    )
    result = tailor_resume(
        client_fake,
        "Python dev built services.",
        '{"missing_keywords": []}',
    )
    assert len(result.diffs) == 1
    assert result.diffs[0].provenance_state == "verified"
    assert len(result.invalid_diffs) == 1
    assert result.invalid_diffs[0].type == "add"
    assert result.invalid_diffs[0].provenance_state == "missing"


def test_proactive_jd_profile_reuses_cache():
    from resualign.jd_analysis import proactive_jd_profile

    client_fake = _CountingProfileClient(
        [
            {
                "must_have_skills": ["Python"],
                "nice_to_have_skills": ["Redis"],
                "soft_skills": [],
                "business_scenarios": ["high concurrency"],
                "min_years_experience": None,
                "education_requirements": [],
            }
        ]
    )
    cache = ContentCache(db_path=":memory:")
    first = proactive_jd_profile(
        client_fake, "Backend engineer.", cache=cache, tenant="tenant-1"
    )
    second = proactive_jd_profile(
        client_fake, "Backend engineer.", cache=cache, tenant="tenant-1"
    )
    assert first.must_have_skills == ["Python"]
    assert second.required_skills == ["Python"]
    assert second.business_scene == ["high concurrency"]
    assert client_fake.calls == 1


def test_preanalyze_endpoint_idempotent_and_persists():
    job = _create_job()
    resume = _create_resume()
    api_module._jobs.update_job(
        _auth_user_id(),
        job["job_id"],
        workbench_resume_id=resume["resume_id"],
    )
    profile = JDProfile(
        must_have_skills=["Python"],
        nice_to_have_skills=["Redis"],
        business_scenarios=["high concurrency"],
    )
    gap = GapReport(missing_keywords=["Redis"], strength_matches=["Python"])
    calls = {"count": 0}

    def fake_profile_jd(client, jd_text, **kwargs):
        calls["count"] += 1
        return profile

    def fake_analyze_gaps(client, resume_text, jd_profile_text):
        calls["count"] += 1
        return gap

    with patch("resualign.api.build_config", return_value=_config()), patch(
        "resualign.api._classify_job",
        return_value={
            "job_function": "后端",
            "seniority": "中级",
            "tech_tags": ["Python"],
        },
    ), patch(
        "resualign.api.profile_jd", side_effect=fake_profile_jd
    ), patch(
        "resualign.api.analyze_gaps", side_effect=fake_analyze_gaps
    ):
        first = client.post(
            f"/api/jobs/{job['job_id']}/preanalyze",
            headers=_auth_headers(),
        )
        second = client.post(
            f"/api/jobs/{job['job_id']}/preanalyze",
            headers=_auth_headers(),
        )
    assert first.status_code == 200
    assert first.json()["status"] == "ready"
    assert first.json()["jd_profile"]["required_skills"] == ["Python"]
    assert first.json()["jd_profile"]["must_have_skills"] == ["Python"]
    assert first.json()["gap_report"]["missing_keywords"] == ["Redis"]
    assert calls["count"] == 2
    assert second.json()["cache_hit"] is True
    assert second.json()["jd_profile"] == first.json()["jd_profile"]

    persisted = client.get(
        f"/api/jobs/{job['job_id']}", headers=_auth_headers()
    ).json()
    assert persisted["jd_profile"]["business_scene"] == ["high concurrency"]
    assert persisted["classification_pending"] == 0
    assert persisted["match_score"] == 94.8
    assert persisted["match_score_detail"]["total"] == 94.8
    assert persisted["match_reason"].startswith("基于规则评分：")


def test_preanalyze_no_resume_profiles_only():
    job = _create_job()
    profile = JDProfile(
        must_have_skills=["Python"],
        business_scenarios=["low latency"],
    )
    with patch("resualign.api.build_config", return_value=_config()), patch(
        "resualign.api._classify_job",
        return_value={"job_function": "后端", "seniority": "未知", "tech_tags": []},
    ), patch(
        "resualign.api.proactive_jd_profile", return_value=profile
    ):
        response = client.post(
            f"/api/jobs/{job['job_id']}/preanalyze",
            headers=_auth_headers(),
        )
    assert response.status_code == 200
    body = response.json()
    assert body["gap_report"] is None
    assert body["match_score"] is None
    assert body["jd_profile"]["business_scene"] == ["low latency"]


def test_rewrite_bullet_endpoint_persists_replacement():
    job = _create_job()
    job_id = job["job_id"]
    api_module._jobs.update_job(
        _auth_user_id(),
        job_id,
        diffs=[
            {
                "diff_id": "diff-1",
                "type": "modify",
                "original": "Python developer.",
                "proposed": "Python developer with Redis.",
                "provenance_state": "verified",
            }
        ],
    )
    rewritten = DiffItem(
        diff_id="diff-1",
        type="modify",
        original="Python developer.",
        proposed="Python developer with Redis caching for high concurrency.",
        reason="JD scenario match",
        confidence="high",
        provenance="Python developer.",
        provenance_quote="Python developer.",
        source_span=(0, 18),
        provenance_state="verified",
    )
    with patch("resualign.api.build_config", return_value=_config()), patch(
        "resualign.api.rewrite_bullet", return_value=rewritten
    ) as rewrite_mock:
        response = client.post(
            f"/api/jobs/{job_id}/workbench/rewrite",
            json={"diff_id": "diff-1", "instruction": "high_concurrency"},
            headers=_auth_headers(),
        )
    assert response.status_code == 200
    body = response.json()
    assert body["diff_id"] == "diff-1"
    assert body["proposed"].startswith("Python developer with Redis caching")
    assert body["provenance_state"] == "verified"
    rewrite_mock.assert_called_once()
    args = rewrite_mock.call_args
    assert args[0][2] == "high_concurrency"
    assert args[1]["tenant"] == _auth_user_id()

    persisted = client.get(
        f"/api/jobs/{job_id}", headers=_auth_headers()
    ).json()
    updated_diff = next(
        diff for diff in persisted["diffs"] if diff["diff_id"] == "diff-1"
    )
    assert updated_diff["proposed"] == rewritten.proposed
    assert updated_diff["provenance_state"] == "verified"


def test_rewrite_bullet_missing_diff_404():
    job = _create_job()
    with patch("resualign.api.build_config", return_value=_config()):
        response = client.post(
            f"/api/jobs/{job['job_id']}/workbench/rewrite",
            json={"diff_id": "missing", "instruction": "concise"},
            headers=_auth_headers(),
        )
    assert response.status_code == 404


def test_rewrite_invalid_bullet_promotes_and_dedups():
    # Phase 4: retrying a failed bullet must move it out of invalid_diffs so
    # the workbench does not show a duplicate card.
    job = _create_job()
    job_id = job["job_id"]
    api_module._jobs.update_job(
        _auth_user_id(),
        job_id,
        diffs=[],
        invalid_diffs=[
            {
                "diff_id": "diff-fail",
                "type": "modify",
                "original": "Built services with Python.",
                "proposed": "",
                "reason": "生成失败，可单条重试: timeout",
                "provenance_state": "missing",
            }
        ],
    )
    rewritten = DiffItem(
        diff_id="diff-fail",
        type="modify",
        original="Built services with Python.",
        proposed="Built high-concurrency services with Python and Redis.",
        reason="JD scenario match",
        confidence="high",
        provenance="Built services with Python.",
        provenance_quote="Built services with Python.",
        source_span=(0, 26),
        provenance_state="verified",
    )
    with patch("resualign.api.build_config", return_value=_config()), patch(
        "resualign.api.rewrite_bullet", return_value=rewritten
    ):
        response = client.post(
            f"/api/jobs/{job_id}/workbench/rewrite",
            json={"diff_id": "diff-fail", "instruction": "high_concurrency"},
            headers=_auth_headers(),
        )
    assert response.status_code == 200

    persisted = client.get(
        f"/api/jobs/{job_id}", headers=_auth_headers()
    ).json()
    assert any(
        diff["diff_id"] == "diff-fail" for diff in persisted["diffs"]
    )
    assert not any(
        diff["diff_id"] == "diff-fail"
        for diff in (persisted.get("invalid_diffs") or [])
    )


def _auth_user_id() -> str:
    return client.get("/api/auth/me", headers=_auth_headers()).json()["user_id"]
