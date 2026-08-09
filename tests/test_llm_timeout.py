"""Q3: LLM timeout / network-exception behavior.

Unit level (pytest-httpx): ``httpx.ReadTimeout`` / ``httpx.ConnectTimeout``
must be retried ``DEFAULT_MAX_RETRIES`` times (default 2, so 3 attempts) and
surface as a readable ``LLMResponseError`` with the underlying cause in the
message. The client must recover when a later attempt succeeds.

API level: a chat method raising a timeout fails the analysis job with a
friendly, non-leaking error string; a follow-up request succeeds (the failure
is retryable by the user).
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.jobs import JobRegistry
from resualign.llm import (
    STRUCTURED_MAX_EXTRA_RETRIES,
    LLMResponseError,
    OpenAIClient,
)
from resualign.models import ResuAlignConfig
from resualign.schema_registry import AnalysisSchema
from resualign.settings_store import SettingsStore
from resualign.workspace import MasterResumeStore, UserStore

DEFAULT_MAX_RETRIES = OpenAIClient.DEFAULT_MAX_RETRIES

client = TestClient(app)
_auth_cache = None


def _config(api_key: str = "sk-test") -> ResuAlignConfig:
    return ResuAlignConfig(
        provider="deepseek",
        api_key=api_key,
        model="test-model",
    )


def _freeze_sleep():
    """Retry backoff is 1s per attempt; freeze it so tests stay fast."""
    return patch("resualign.llm.time.sleep")


@pytest.fixture
def llm_client():
    return OpenAIClient(_config())


@pytest.fixture(autouse=True)
def temp_api_state(tmp_path):
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
            "_PERSONAL_MODE",
            "_payloads",
            "_import_batches",
        )
    }
    db_path = tmp_path / "llm-timeout.db"
    api_module._registry = JobRegistry(db_path=db_path)
    api_module._users = UserStore(db_path=db_path)
    api_module._resumes = MasterResumeStore(db_path=db_path)
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
    for name, value in saved.items():
        setattr(api_module, name, value)
    _auth_cache = None


def _auth_headers() -> dict[str, str]:
    global _auth_cache
    if _auth_cache is not None:
        return _auth_cache
    assert (
        client.post(
            "/api/auth/signup",
            json={"email": "timeout@example.com", "password": "password-123"},
        ).status_code
        == 201
    )
    token = client.post(
        "/api/auth/login",
        json={"email": "timeout@example.com", "password": "password-123"},
    ).json()["token"]
    _auth_cache = {"Authorization": f"Bearer {token}"}
    return _auth_cache


# ---------------------------------------------------------------------------
# Unit level: retry counts and final LLMResponseError
# ---------------------------------------------------------------------------


def test_chat_json_read_timeout_retries_then_raises(httpx_mock, llm_client):
    for _ in range(DEFAULT_MAX_RETRIES + 1):
        httpx_mock.add_exception(httpx.ReadTimeout("read timed out"))

    with _freeze_sleep():
        with pytest.raises(LLMResponseError) as excinfo:
            llm_client.chat_json("system", "user")

    message = str(excinfo.value)
    assert "LLM call failed after 3 attempts" in message
    assert "read timed out" in message  # readable: underlying cause is kept
    assert len(httpx_mock.get_requests()) == DEFAULT_MAX_RETRIES + 1


def test_chat_json_connect_timeout_retries_then_raises(httpx_mock, llm_client):
    for _ in range(DEFAULT_MAX_RETRIES + 1):
        httpx_mock.add_exception(httpx.ConnectTimeout("connection timed out"))

    with _freeze_sleep():
        with pytest.raises(LLMResponseError) as excinfo:
            llm_client.chat_json("system", "user")

    assert "connection timed out" in str(excinfo.value)
    assert len(httpx_mock.get_requests()) == DEFAULT_MAX_RETRIES + 1


def test_chat_json_recovers_after_first_attempt_timeout(httpx_mock, llm_client):
    httpx_mock.add_exception(httpx.ReadTimeout("first attempt timed out"))
    httpx_mock.add_response(
        json={
            "choices": [
                {"message": {"content": '{"score": 84, "skills": ["Python"]}'}}
            ]
        }
    )

    with _freeze_sleep():
        result = llm_client.chat_json("system", "user")

    assert result["score"] == 84
    assert "Python" in result["skills"]
    assert len(httpx_mock.get_requests()) == 2


def test_chat_structured_read_timeout_retries_then_raises(httpx_mock):
    """Deepseek goes through the json-mode structured path: same retry rule."""
    llm_client = OpenAIClient(_config())  # provider deepseek -> not structured outputs
    for _ in range(STRUCTURED_MAX_EXTRA_RETRIES + 1):
        httpx_mock.add_exception(httpx.ReadTimeout("read timed out"))

    with _freeze_sleep():
        with pytest.raises(LLMResponseError) as excinfo:
            llm_client.chat_structured("system", "user", AnalysisSchema)

    message = str(excinfo.value)
    assert "Structured LLM call failed after 3 attempts" in message
    assert "read timed out" in message
    assert len(httpx_mock.get_requests()) == STRUCTURED_MAX_EXTRA_RETRIES + 1


def test_chat_structured_recovers_after_timeout(httpx_mock):
    llm_client = OpenAIClient(_config())
    httpx_mock.add_exception(httpx.ReadTimeout("read timed out"))
    httpx_mock.add_response(
        json={
            "choices": [
                {"message": {"content": '{"score": 77, "skills": ["Go"]}'}}
            ]
        }
    )

    with _freeze_sleep():
        result = llm_client.chat_structured(
            "system", "user", AnalysisSchema
        )

    assert result["score"] == 77
    assert result["skills"] == ["Go"]
    assert len(httpx_mock.get_requests()) == 2


# ---------------------------------------------------------------------------
# API level: analyze endpoint, job failed with readable error, retryable
# ---------------------------------------------------------------------------


def _submit_analyze(payload):
    """Queue an analyze job without letting the daemon thread run it."""
    with patch("resualign.api._run_job"), patch(
        "resualign.api.build_config", return_value=_config()
    ):
        r = client.post("/api/analyze", json=payload, headers=_auth_headers())
    assert r.status_code == 202
    return r.json()["job_id"]


def test_analyze_job_fails_with_readable_error_when_llm_times_out():
    with patch("resualign.api.build_config", return_value=_config()):
        job_id = _submit_analyze({"resume_text": "Python developer."})

    with patch(
        "resualign.llm.OpenAIClient.chat_structured",
        side_effect=httpx.ReadTimeout("read timed out"),
    ):
        api_module._run_job(job_id)

    data = client.get(f"/api/jobs/{job_id}", headers=_auth_headers()).json()
    assert data["status"] == "failed"
    assert isinstance(data["error"], str) and data["error"]
    # Readable: a stable friendly sentence, not a traceback / leaked key.
    assert "Traceback" not in data["error"]
    assert "sk-test" not in data["error"]
    assert data["result"] is None


def test_analyze_job_timeout_failure_is_retryable():
    calls = {"n": 0}

    def flaky_chat(self, system, user, schema_model, model=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ReadTimeout("read timed out")
        return {"score": 82, "skills": ["Python", "FastAPI"], "issues": []}

    with patch("resualign.api.build_config", return_value=_config()):
        first = _submit_analyze({"resume_text": "Python developer."})
        second = _submit_analyze({"resume_text": "Python developer."})

    with patch("resualign.llm.OpenAIClient.chat_structured", flaky_chat):
        api_module._run_job(first)
        api_module._run_job(second)

    first_data = client.get(
        f"/api/jobs/{first}", headers=_auth_headers()
    ).json()
    assert first_data["status"] == "failed"

    second_data = client.get(
        f"/api/jobs/{second}", headers=_auth_headers()
    ).json()
    assert second_data["status"] == "succeeded"
    assert second_data["error"] is None
    assert second_data["result"]["score"] == 82
    assert calls["n"] == 2


def test_diagnosis_job_timeout_error_message_is_user_readable():
    """The no-JD diagnosis flow maps LLM timeouts to a user-actionable message."""
    with patch("resualign.api.build_config", return_value=_config()):
        resume = client.post(
            "/api/master-resumes",
            json={"title": "Timeout resume", "content": "Python developer."},
            headers=_auth_headers(),
        ).json()

    with patch("resualign.api.build_config", return_value=_config()), patch(
        "resualign.api._run_job"
    ):
        r = client.post(
            f"/api/master-resumes/{resume['resume_id']}/diagnose",
            headers=_auth_headers(),
        )
        assert r.status_code == 202
        job_id = r.json()["job_id"]

    with patch(
        "resualign.llm.OpenAIClient.chat_structured",
        side_effect=httpx.ReadTimeout("read timed out"),
    ):
        api_module._run_job(job_id)

    data = client.get(f"/api/jobs/{job_id}", headers=_auth_headers()).json()
    assert data["status"] == "failed"
    assert "模型服务不可用或返回异常" in data["error"]
    assert "请检查 API Key 与网络连接后重试" in data["error"]

def test_timeout_defaults_bound_request_hangs():
    """LLM request timeouts must be tight enough that a stuck provider
    cannot hang the frontend for minutes: 60s read (x3 attempts = 180s
    worst case) and a short 10s connect window."""
    assert OpenAIClient.DEFAULT_TIMEOUT == 60.0
    assert OpenAIClient.DEFAULT_CONNECT_TIMEOUT == 10.0
    client = OpenAIClient(_config())
    timeout = client._client.timeout
    assert timeout.connect == 10.0
    assert timeout.read == 60.0
    client.close()
