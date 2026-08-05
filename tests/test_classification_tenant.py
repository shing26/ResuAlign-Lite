"""S1: classification cache keys are tenant-scoped."""

from __future__ import annotations

from unittest.mock import patch

import pytest

import resualign.api as api_module
from resualign.cache import ContentCache
from resualign.job_library import JobLibraryStore
from resualign.settings_store import SettingsStore


class _CountingLLM:
    """Fake OpenAIClient that counts classification calls."""

    shared_calls: list[str] = []

    def __init__(self, config, timeout: float = 45.0) -> None:
        self.config = config
        self.timeout = timeout

    def __enter__(self) -> "_CountingLLM":
        return self

    def __exit__(self, *args: object) -> bool:
        return False

    def chat_structured(self, system, user, schema_model, model=None):
        _CountingLLM.shared_calls.append(user[:40])
        return {
            "job_function": "后端",
            "seniority": "高级",
            "tech_tags": ["Python"],
        }


@pytest.fixture(autouse=True)
def reset_calls():
    _CountingLLM.shared_calls = []
    yield
    _CountingLLM.shared_calls = []


def test_classification_cache_isolated_per_tenant(tmp_path):
    cache = ContentCache(db_path=tmp_path / "classify.db")
    jd_text = "Backend engineer role using Python and FastAPI"
    with patch.object(api_module, "OpenAIClient", _CountingLLM), patch.object(
        api_module, "_cache", cache
    ):
        first = api_module._classify_job(jd_text, tenant="tenant-a")
        second = api_module._classify_job(jd_text, tenant="tenant-b")
        third = api_module._classify_job(jd_text, tenant="tenant-a")

    assert first == second == third
    # tenant-a cache miss, tenant-b miss, tenant-a hit -> exactly 2 LLM calls
    assert len(_CountingLLM.shared_calls) == 2


def test_create_job_from_source_passes_tenant_to_classifier(tmp_path):
    db_path = tmp_path / "source.db"
    jobs = JobLibraryStore(db_path=db_path)
    settings = SettingsStore(db_path=db_path)
    with patch.object(
        api_module, "_jobs", jobs
    ), patch.object(
        api_module, "_settings_store", settings
    ), patch.object(
        api_module, "_settings_vocabulary", return_value=([], [])
    ), patch.object(
        api_module, "_classify_job", return_value={}
    ) as mock_classify:
        created = api_module._create_job_from_source(
            {"user_id": "tenant-42"},
            {"jd_text": "Backend role", "title": "Backend"},
        )

    assert created["tenant_id"] == "tenant-42"
    assert mock_classify.call_args.kwargs["tenant"] == "tenant-42"
