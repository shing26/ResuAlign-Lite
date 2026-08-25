"""Q3: LLM timeout / network-exception behavior.

Unit level (pytest-httpx): transport errors (``httpx.ReadTimeout`` /
``httpx.ConnectTimeout`` / connection loss) fail fast after ONE attempt and
surface as a readable ``LLMResponseError`` with the underlying cause kept in
the message. They are NOT retried inside the client: a timeout on a large
prompt rarely succeeds on retry, and retrying only multiplies the wait.
Callers (the role-router fallback node, the job runner, the user) own the
retry decision, and a fresh client call succeeds afterwards. Resumable
failures (HTTP 5xx, schema validation, finish_reason=length) still use the
``max_retries`` budget.

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
    LLMResponseError,
    OpenAIClient,
)
from resualign.models import ResuAlignConfig
from resualign.schema_registry import (
    AnalysisSchema,
    JDProfileSchema,
    TailoredResumeSchema,
)
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
# Unit level: transport failures fail fast; retries are resumable only
# ---------------------------------------------------------------------------


def test_chat_json_read_timeout_fails_fast(httpx_mock, llm_client):
    httpx_mock.add_exception(httpx.ReadTimeout("read timed out"))

    with _freeze_sleep():
        with pytest.raises(LLMResponseError) as excinfo:
            llm_client.chat_json("system", "user")

    message = str(excinfo.value)
    assert "network timeout" in message
    assert "read timed out" in message  # readable: underlying cause is kept
    assert len(httpx_mock.get_requests()) == 1


def test_chat_json_connect_timeout_fails_fast(httpx_mock, llm_client):
    httpx_mock.add_exception(httpx.ConnectTimeout("connection timed out"))

    with _freeze_sleep():
        with pytest.raises(LLMResponseError) as excinfo:
            llm_client.chat_json("system", "user")

    assert "network timeout" in str(excinfo.value)
    assert "connection timed out" in str(excinfo.value)
    assert len(httpx_mock.get_requests()) == 1


def test_chat_json_timeout_fails_fast_but_fresh_call_succeeds(
    httpx_mock, llm_client
):
    """The client does not retry internally, but a fresh call is retryable."""
    httpx_mock.add_exception(httpx.ReadTimeout("first attempt timed out"))

    with _freeze_sleep():
        with pytest.raises(LLMResponseError):
            llm_client.chat_json("system", "user")

    httpx_mock.add_response(
        json={
            "choices": [
                {"message": {"content": '{"score": 84, "skills": ["Python"]}'}}
            ]
        }
    )
    result = llm_client.chat_json("system", "user")

    assert result["score"] == 84
    assert "Python" in result["skills"]
    assert len(httpx_mock.get_requests()) == 2


def test_chat_json_retries_http_errors(httpx_mock):
    """5xx is resumable: it still consumes the retry budget."""
    client_obj = OpenAIClient(_config())
    client_obj.max_retries = 1
    httpx_mock.add_response(status_code=500)
    httpx_mock.add_response(status_code=500)

    with _freeze_sleep():
        with pytest.raises(LLMResponseError) as excinfo:
            client_obj.chat_json("system", "user")

    assert "after 2 attempts" in str(excinfo.value)
    assert len(httpx_mock.get_requests()) == 2


def test_chat_structured_read_timeout_fails_fast(httpx_mock):
    """Deepseek goes through the json-mode structured path: same rule."""
    llm_client = OpenAIClient(_config())  # provider deepseek -> not structured outputs
    httpx_mock.add_exception(httpx.ReadTimeout("read timed out"))

    with _freeze_sleep():
        with pytest.raises(LLMResponseError) as excinfo:
            llm_client.chat_structured("system", "user", AnalysisSchema)

    message = str(excinfo.value)
    assert "Structured LLM call failed after 1 attempt(s) (network timeout)" in message
    assert "read timed out" in message
    assert len(httpx_mock.get_requests()) == 1


def test_chat_structured_timeout_fails_fast_but_fresh_call_succeeds(httpx_mock):
    llm_client = OpenAIClient(_config())
    httpx_mock.add_exception(httpx.ReadTimeout("read timed out"))

    with _freeze_sleep():
        with pytest.raises(LLMResponseError):
            llm_client.chat_structured("system", "user", AnalysisSchema)

    httpx_mock.add_response(
        json={
            "choices": [
                {"message": {"content": '{"score": 77, "skills": ["Go"]}'}}
            ]
        }
    )
    result = llm_client.chat_structured("system", "user", AnalysisSchema)

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
    """Alignment (with JD) still surfaces an LLM timeout as a readable error.

    Diagnosis itself no longer calls the LLM (取舍一方案 A); the first LLM
    stage that can time out is the JD profiler.
    """
    with patch("resualign.api.build_config", return_value=_config()):
        job_id = _submit_analyze({
            "resume_text": "Python developer.",
            "jd_text": "Java backend engineer",
        })

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
    """An alignment whose first LLM call times out fails; a retry succeeds."""
    calls = {"structured": 0, "json": 0}

    def flaky_structured(self, system, user, schema_model, model=None):
        calls["structured"] += 1
        if calls["structured"] == 2:
            raise httpx.ReadTimeout("read timed out")
        if schema_model is AnalysisSchema:
            return {"score": 82, "skills": ["Python", "FastAPI"], "issues": []}
        if schema_model is JDProfileSchema:
            return {
                "must_have_skills": ["Java"],
                "nice_to_have_skills": [],
                "soft_skills": [],
                "business_scenarios": ["Backend"],
                "min_years_experience": None,
                "education_requirements": [],
            }
        if schema_model is TailoredResumeSchema:
            return {
                "sections": {"exp": "Built services"},
                "diffs": [
                    {
                        "type": "modify",
                        "original": "Java, Spring Boot",
                        "proposed": "Java, Spring Boot, and backend services",
                        "reason": "JD match",
                        "confidence": "high",
                        "provenance": "Java, Spring Boot",
                    }
                ],
            }
        return {}

    def flaky_json(self, system, user, model=None):
        calls["json"] += 1
        return {
            "missing_keywords": [],
            "misaligned_emphasis": [],
            "strength_matches": [],
        }

    payload = {
        "resume_text": "Python developer.",
        "jd_text": "Java backend engineer",
    }
    with patch("resualign.api.build_config", return_value=_config()):
        first = _submit_analyze(payload)
        second = _submit_analyze(payload)

    with patch(
        "resualign.llm.OpenAIClient.chat_structured", flaky_structured
    ), patch("resualign.llm.OpenAIClient.chat_json", flaky_json):
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
    assert second_data["result"]["tailored_resume"] is not None
    # Job 1: diagnose succeeds (and is cached), profile times out, the run
    # fails. Job 2: cached diagnosis skips the LLM, profile + gap + tailor
    # succeed.
    assert calls["structured"] == 4
    assert calls["json"] == 1

def test_diagnosis_job_succeeds_with_local_rules_when_llm_is_down():
    """取舍一方案 A: the diagnosis stage never calls the LLM anymore.

    Even with every OpenAIClient call timing out, a no-JD diagnosis job
    succeeds because it is pure local rules (~1ms, no provider).
    """
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
    ), patch(
        "resualign.llm.OpenAIClient.chat_json",
        side_effect=httpx.ReadTimeout("read timed out"),
    ):
        api_module._run_job(job_id)

    data = client.get(f"/api/jobs/{job_id}", headers=_auth_headers()).json()
    assert data["status"] == "succeeded"
    assert data["error"] is None
    diagnosis = data["result"]["diagnosis"]
    assert diagnosis["score"] == 45
    assert "Python" in diagnosis["skills"]

def test_workbench_timeout_error_names_timeout_stage():
    detail = api_module._job_failure_detail(
        "tailoring",
        LLMResponseError(
            "Structured LLM call failed after 1 attempt (network timeout): "
            "The read operation timed out"
        ),
    )
    assert "简历定制" in detail
    assert "模型响应超时" in detail
    assert "模型服务不可用" not in detail


def test_workbench_json_parse_error_gets_actionable_message():
    detail = api_module._job_failure_detail(
        "tailoring",
        LLMResponseError(
            "Structured response failed schema validation after 2 attempts: "
            "Expecting value: line 1 column 1 (char 0)"
        ),
    )
    assert "简历定制" in detail
    assert "格式异常" in detail
    assert "重试" in detail


def test_workbench_rate_limit_error_gets_retry_message():
    detail = api_module._job_failure_detail(
        "tailoring",
        LLMResponseError(
            "LLM call failed after 2 attempts: "
            "Server error '429 Too Many Requests' for url "
            "https://api.deepseek.com/chat/completions"
        ),
    )
    assert "繁忙" in detail
    assert "稍后重试" in detail


def test_workbench_timeout_quotes_elapsed_when_available():
    detail = api_module._job_failure_detail(
        "jd_analysis",
        LLMResponseError(
            "Structured LLM call failed after 1 attempt (network timeout): "
            "The read operation timed out"
        ),
        elapsed_secs=166.2,
    )
    assert "JD 画像与差距分析" in detail
    assert "模型响应超时" in detail
    assert "166.2" in detail
    assert "API Key" not in detail


def test_workbench_empty_response_gets_retry_message():
    detail = api_module._job_failure_detail(
        "tailoring",
        LLMResponseError("Structured response was empty after 2 attempts"),
    )
    assert "模型返回为空" in detail
    assert "API Key" not in detail


def test_workbench_api_key_only_mentioned_for_auth_failures():
    detail = api_module._job_failure_detail(
        "tailoring",
        LLMResponseError(
            "Structured LLM call failed after 2 attempts: "
            "Client error '401 Unauthorized' for url "
            "https://api.openai.com/chat/completions"
        ),
    )
    assert "API Key" in detail

    unknown = api_module._job_failure_detail(
        "tailoring", LLMResponseError("provider exploded mysteriously")
    )
    assert "API Key" not in unknown
    assert "模型服务暂时不可用" in unknown


def test_timeout_defaults_bound_request_hangs():
    """LLM request timeouts must be tight enough that a stuck provider
    cannot hang the frontend for minutes: transport errors fail after one
    attempt (role timeouts now span 30-90s), retries are reserved for
    5xx/schema failures (2 attempts total), and connect has a short window."""
    assert OpenAIClient.DEFAULT_TIMEOUT == 120.0
    assert OpenAIClient.DEFAULT_CONNECT_TIMEOUT == 30.0
    assert OpenAIClient.DEFAULT_MAX_RETRIES == 1
    client = OpenAIClient(_config())
    timeout = client._client.timeout
    assert timeout.connect == 30.0
    assert timeout.read == 120.0
    client.close()
