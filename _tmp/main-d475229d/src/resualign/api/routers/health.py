
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

import resualign.api as api_module

router = APIRouter()

# Probe key for the cache write-read roundtrip. The row is tiny, keyed by a
# fixed INSERT OR REPLACE tuple, and expires with the cache TTL.
_CACHE_PROBE_TENANT = "__health__"
_CACHE_PROBE_MODEL = "__probe__"
_CACHE_PROBE_VERSION = "probe"
_CACHE_PROBE_CONTENT = "health-check"


@router.get('/', response_class=HTMLResponse)
def index():
    """Serve the frontend HTML."""
    if not api_module._static_dir.is_dir():
        return HTMLResponse('<h1>ResuAlign API</h1><p>Frontend not available.</p>')
    return HTMLResponse((api_module._static_dir / 'index.html').read_text(encoding='utf-8'))


def _check_db() -> dict:
    """Readiness: the job database must answer a trivial read."""
    ok = api_module._registry.ping()
    return {"ok": ok, "detail": "database readable" if ok else "database check failed"}


def _check_cache() -> dict:
    """Readiness: the content cache must accept a write-read roundtrip."""
    try:
        cache = api_module._cache
        probe = {"probe": True}
        cache.put(
            _CACHE_PROBE_TENANT,
            _CACHE_PROBE_MODEL,
            _CACHE_PROBE_VERSION,
            _CACHE_PROBE_CONTENT,
            probe,
        )
        value = cache.get(
            _CACHE_PROBE_TENANT,
            _CACHE_PROBE_MODEL,
            _CACHE_PROBE_VERSION,
            _CACHE_PROBE_CONTENT,
        )
        ok = value == probe
    except Exception as exc:
        return {"ok": False, "detail": f"cache check failed: {exc}"}
    return {"ok": ok, "detail": "cache read/write ok" if ok else "cache roundtrip mismatch"}


@router.get('/health')
def health():
    """Liveness probe."""
    # Extended readiness: ``status`` is ``ok`` when every dependency check
    # passes and ``degraded`` otherwise; ``checks`` carries per-dependency
    # detail for operators. Kept out of the docstring so the OpenAPI
    # description stays contract-stable ("Liveness probe.").
    checks = {"db": _check_db(), "cache": _check_cache()}
    status = "degraded" if any(not check["ok"] for check in checks.values()) else "ok"
    return {"status": status, "checks": checks}
