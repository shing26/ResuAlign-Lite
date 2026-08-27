import time

from resualign.cache import ContentCache, content_sha256
from resualign.classifier import classify_job
from resualign.jd_profiler import profile_jd
from resualign.llm import diagnose_resume


class _CountingClient:
    model = "test-model"

    def __init__(self, response):
        self.response = response
        self.call_count = 0

    def chat_json(self, system, user, model=None):
        self.call_count += 1
        return self.response


def test_content_cache_hit_miss_and_key_isolation(tmp_path):
    path = tmp_path / "cache.sqlite3"
    with ContentCache(path) as cache:
        payload = {"score": 80, "issues": [], "skills": ["Python"]}
        assert cache.get("tenant", "model", "v1", "content") is None
        cache.put("tenant", "model", "v1", "content", payload)
        assert cache.get("tenant", "model", "v1", "content") == payload
        assert cache.get("other", "model", "v1", "content") is None
        assert cache.get("tenant", "other", "v1", "content") is None
        assert cache.get("tenant", "model", "v2", "content") is None
        assert cache.get("tenant", "model", "v1", "different") is None


def test_content_cache_ttl_expires(tmp_path):
    path = tmp_path / "ttl.sqlite3"
    with ContentCache(path, ttl_seconds=0.05) as cache:
        cache.put("tenant", "model", "v1", "content", {"ok": True})
        assert cache.get("tenant", "model", "v1", "content") == {"ok": True}
        time.sleep(0.06)
        assert cache.get("tenant", "model", "v1", "content") is None


def test_profile_jd_cache_hit_skips_llm(tmp_path):
    client = _CountingClient(
        {
            "must_have_skills": ["Python"],
            "nice_to_have_skills": [],
            "soft_skills": [],
            "business_scenarios": [],
            "min_years_experience": None,
            "education_requirements": [],
        }
    )
    with ContentCache(tmp_path / "jd.sqlite3") as cache:
        first = profile_jd(
            client, "JD text", cache=cache, tenant="tenant", model="model"
        )
        second = profile_jd(
            client, "JD text", cache=cache, tenant="tenant", model="model"
        )
    assert first == second
    assert client.call_count == 1


def test_classifier_cache_hit_skips_llm(tmp_path):
    client = _CountingClient(
        {
            "job_function": "Backend",
            "seniority": "Senior",
            "tech_tags": ["FastAPI"],
        }
    )
    with ContentCache(tmp_path / "classifier.sqlite3") as cache:
        first = classify_job(
            client,
            "JD text",
            job_functions=["Backend"],
            seniorities=["Senior"],
            cache=cache,
            tenant="tenant",
            model="model",
        )
        second = classify_job(
            client,
            "JD text",
            job_functions=["Backend"],
            seniorities=["Senior"],
            cache=cache,
            tenant="tenant",
            model="model",
        )
    assert first == second
    assert client.call_count == 1


def test_diagnosis_cache_hit_skips_llm(tmp_path):
    client = _CountingClient(
        {"score": 90, "issues": [], "skills": ["Python"]}
    )
    with ContentCache(tmp_path / "diag.sqlite3") as cache:
        first = diagnose_resume(
            client, "Resume", cache=cache, tenant="tenant", model="model"
        )
        second = diagnose_resume(
            client, "Resume", cache=cache, tenant="tenant", model="model"
        )
    assert first == second
    assert client.call_count == 1


def test_prune_expired_removes_only_stale_rows(tmp_path):
    path = tmp_path / "prune.sqlite3"
    with ContentCache(path) as cache:
        cache.put("tenant", "model", "v1", "fresh", {"ok": True})
        stale_created = time.time() - cache.ttl_seconds - 10
        with cache._lock:
            cache._conn.execute(
                """
                INSERT OR REPLACE INTO content_cache (
                    tenant, model, prompt_version, content_sha256,
                    payload, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "tenant",
                    "model",
                    "v1",
                    "stale-sha",
                    "{}",
                    stale_created,
                    stale_created + 1,
                ),
            )
            cache._conn.commit()

        removed = cache.prune_expired()
        assert removed == 1
        # 未过期条目不受影响；再清一次幂等（0 行）
        assert cache.get("tenant", "model", "v1", "fresh") == {"ok": True}
        assert cache.prune_expired() == 0


def test_init_prunes_rows_expired_from_previous_runs(tmp_path):
    """启动即清理：上次运行遗留的过期行在 ContentCache 初始化时回收。"""
    path = tmp_path / "startup.sqlite3"
    with ContentCache(path) as cache:
        cache.put("tenant", "model", "v1", "old", {"v": 1})
        stale_created = time.time() - cache.ttl_seconds - 10
        with cache._lock:
            cache._conn.execute(
                "UPDATE content_cache SET created_at = ?, expires_at = ? "
                "WHERE content_sha256 = ?",
                (stale_created, stale_created + 1, content_sha256("old")),
            )
            cache._conn.commit()

    with ContentCache(path) as reopened:
        assert reopened.get("tenant", "model", "v1", "old") is None
        with reopened._lock:
            count = reopened._conn.execute(
                "SELECT COUNT(*) FROM content_cache"
            ).fetchone()[0]
        assert count == 0
