"""Deterministic resume x job ranking (ADR-0065).

Path: SQL filters -> cosine over cached vectors -> stable sort -> why fields.
Zero LLM on the ranking path. A ranking failure degrades (200 + degraded) while
the gate stays fail-closed; the two must never be conflated.

Flag: RESUALIGN_RESUME_RANKING (default off, ADR-0065 decision 6).
Never writes workbench_resume_id: best-resume only suggests (decision 6).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Sequence

from ...engine.embeddings import Embedder, EmbeddingError, build_embedder
from ...prematch import compute_match_signals, detect_skills
from ...vector_index import VectorIndex

logger = logging.getLogger(__name__)

FLAG_ENV = "RESUALIGN_RESUME_RANKING"
DEFAULT_LIMIT = 10
MAX_LIMIT = 50
DEFAULT_BEST_RESUME_LIMIT = 3
NEAR_DUPLICATE_THRESHOLD = 0.90

_index_lock = threading.Lock()
_index: VectorIndex | None = None

_build_states: dict[str, dict[str, Any]] = {}
_build_lock = threading.Lock()


# --------------------------------------------------------------------------- #
# wiring
# --------------------------------------------------------------------------- #
def ranking_enabled() -> bool:
    return os.environ.get(FLAG_ENV, "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def get_index() -> VectorIndex:
    """Process-wide index on the shared jobs database (lazy, thread-safe)."""
    global _index
    with _index_lock:
        if _index is None:
            _index = VectorIndex()
        return _index


def reset_index_for_tests() -> None:
    global _index
    with _index_lock:
        _index = None


def _clamp_limit(limit: int, maximum: int = MAX_LIMIT) -> int:
    try:
        parsed = int(limit)
    except (TypeError, ValueError):
        parsed = DEFAULT_LIMIT
    return max(1, min(parsed, maximum))


def _disabled() -> dict[str, Any]:
    return {
        "enabled": False,
        "degraded": True,
        "reason": "disabled",
        "items": [],
    }


def _degraded(reason: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "enabled": True,
        "degraded": True,
        "reason": reason,
        "items": [],
    }
    payload.update(extra)
    return payload


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def _gap_count(job: dict[str, Any]) -> int | None:
    raw = job.get("gap_report_json")
    if not raw:
        return None
    try:
        report = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(report, dict):
        return None
    missing = report.get("missing_keywords")
    return len(missing) if isinstance(missing, list) else None


def _skill_hits(resume_text: str, jd_text: str, limit: int = 5) -> list[str]:
    """Resume-backed skill names only (ADR-0064/0061 boundary)."""
    if not resume_text or not jd_text:
        return []
    try:
        signals = compute_match_signals(resume_text, jd_text)
    except Exception:  # signals are decorative; never fail the request
        logger.debug("prematch signals failed", exc_info=True)
        return []
    return list(signals.get("matched_skills") or [])[:limit]


def _why(
    job: dict[str, Any],
    resume_text: str,
    rank: int,
    total: int,
) -> dict[str, Any]:
    why: dict[str, Any] = {
        # Percentile, not probability: "higher than N% of the ranked jobs".
        "semantic_percentile": max(0, min(100, round(100 * (1 - rank / max(1, total))))),
        "skill_hits": _skill_hits(resume_text, job.get("jd_text") or ""),
    }
    gap = _gap_count(job)
    if gap is not None:
        why["gap_count"] = gap
    if isinstance(job.get("usable_diffs"), int):
        why["usable_diffs"] = job["usable_diffs"]
    return why


def _job_item(job: dict[str, Any], score: float | None, why: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": job.get("job_id"),
        "title": job.get("title") or "",
        "company": job.get("company") or "",
        "location": job.get("location") or "",
        "status": job.get("status") or "",
        "job_function": job.get("job_function") or "",
        "score": None if score is None else round(float(score), 4),
        "why": why,
    }


def _resume_text(resumes_store: Any, tenant_id: str, resume_id: str) -> str | None:
    resume = resumes_store.get_master_resume(tenant_id, resume_id)
    if resume is None:
        return None
    text = resume.get("content") or ""
    if not text:
        versions = resume.get("versions") or []
        if versions:
            text = versions[-1].get("content") or ""
    return text or None


# --------------------------------------------------------------------------- #
# index build
# --------------------------------------------------------------------------- #
def rebuild_index(
    tenant_id: str,
    jobs_store: Any,
    *,
    index: VectorIndex | None = None,
    embedder: Embedder | None = None,
    force: bool = False,
    batch_size: int = 16,
    progress: Any = None,
) -> dict[str, Any]:
    """Embed every job whose JD changed (sha256), in batches. Idempotent."""
    idx = index or get_index()
    emb = embedder or build_embedder()
    model = emb.storage_model
    jobs = jobs_store.list_jobs(tenant_id, limit=None)
    existing = {} if force else idx.job_shas(tenant_id, model=model)

    pending: list[tuple[dict[str, Any], str, str]] = []
    for job in jobs:
        text = (job.get("jd_text") or "").strip()
        if not text:
            continue
        sha = VectorIndex.text_sha256(text)
        if existing.get(job["job_id"]) == sha:
            continue
        pending.append((job, text, sha))

    embedded = 0
    for start in range(0, len(pending), batch_size):
        chunk = pending[start : start + batch_size]
        vectors = emb.embed_many([text for _, text, _ in chunk])
        for (job, text, sha), vector in zip(chunk, vectors):
            idx.upsert_job(
                tenant_id,
                job["job_id"],
                vector,
                model=model,
                text_sha256=sha,
                skills=detect_skills(text),
            )
        embedded += len(chunk)
        if progress is not None:
            progress(embedded, len(pending))

    return {
        "model": model,
        "dim": emb.dim,
        "embedded": embedded,
        "skipped": len(jobs) - len(pending),
        "total_jobs": len(jobs),
    }


def _snapshot(tenant_id: str) -> dict[str, Any]:
    with _build_lock:
        state = _build_states.get(tenant_id)
        return dict(state) if state else {
            "running": False,
            "embedded": 0,
            "total": 0,
            "error": None,
            "finished_at": None,
        }


def start_rebuild(tenant_id: str, jobs_store: Any) -> dict[str, Any]:
    """Kick off a background rebuild; one in-flight build per tenant."""
    with _build_lock:
        state = _build_states.get(tenant_id)
        if state and state.get("running"):
            return {"started": False, **_snapshot(tenant_id)}
        _build_states[tenant_id] = {
            "running": True,
            "embedded": 0,
            "total": 0,
            "error": None,
            "started_at": time.time(),
            "finished_at": None,
        }

    def run() -> None:
        def progress(done: int, total: int) -> None:
            with _build_lock:
                _build_states[tenant_id]["embedded"] = done
                _build_states[tenant_id]["total"] = total

        try:
            result = rebuild_index(tenant_id, jobs_store, progress=progress)
            with _build_lock:
                _build_states[tenant_id].update(
                    {
                        "running": False,
                        "embedded": result["embedded"],
                        "total": result["total_jobs"],
                        "model": result["model"],
                        "dim": result["dim"],
                        "finished_at": time.time(),
                    }
                )
            logger.info(
                "ranking index rebuilt: tenant=%s embedded=%d skipped=%d",
                tenant_id,
                result["embedded"],
                result["skipped"],
            )
        except Exception as exc:  # degraded, never crashes the app
            logger.exception("ranking index rebuild failed for %s", tenant_id)
            with _build_lock:
                _build_states[tenant_id].update(
                    {
                        "running": False,
                        "error": type(exc).__name__ + ": " + str(exc)[:200],
                        "finished_at": time.time(),
                    }
                )

    threading.Thread(target=run, name="resualign-ranking-index", daemon=True).start()
    return {"started": True, **_snapshot(tenant_id)}


def index_status(tenant_id: str, *, index: VectorIndex | None = None) -> dict[str, Any]:
    idx = index or get_index()
    stats = idx.stats(tenant_id)
    embedder = _try_embedder()
    return {
        "enabled": ranking_enabled(),
        "building": _snapshot(tenant_id)["running"],
        "last_build": _snapshot(tenant_id),
        "model": embedder.storage_model if embedder else None,
        "jobs": stats["jobs"],
        "resumes": stats["resumes"],
        "needs_rebuild": stats["needs_rebuild"],
        "over_limit": stats["over_limit"],
        "limit": VectorIndex.MAX_VECTORS,
    }


def _try_embedder() -> Embedder | None:
    try:
        return build_embedder()
    except EmbeddingError as exc:
        logger.info("embedder unavailable: %s", exc)
        return None


# --------------------------------------------------------------------------- #
# resume -> jobs
# --------------------------------------------------------------------------- #
def recommend_jobs(
    tenant_id: str,
    jobs_store: Any,
    resumes_store: Any,
    *,
    resume_id: str | None = None,
    resume_text: str | None = None,
    limit: int = DEFAULT_LIMIT,
    status: str | None = None,
    job_function: str | None = None,
    seniority: str | None = None,
    index: VectorIndex | None = None,
    embedder: Embedder | None = None,
) -> dict[str, Any]:
    if not ranking_enabled():
        return _disabled()
    limit = _clamp_limit(limit)

    text = resume_text or ""
    if resume_id:
        resolved = _resume_text(resumes_store, tenant_id, resume_id)
        if resolved is None:
            return _degraded("resume_missing", resume_id=resume_id)
        text = resolved
    if not text.strip():
        return _degraded("resume_text_missing")

    jobs = jobs_store.list_jobs(
        tenant_id,
        job_function=job_function,
        seniority=seniority,
        status=status,
        limit=None,
    )
    if not jobs:
        return {"enabled": True, "degraded": False, "reason": None, "items": []}

    emb = embedder or _try_embedder()
    if emb is None:
        return _fallback(jobs, text, limit, "embedder_unavailable")

    idx = index or get_index()
    model = emb.storage_model
    try:
        vector = _resume_vector(idx, emb, tenant_id, resume_id or "inline", text)
    except EmbeddingError as exc:
        logger.warning("resume embedding failed: %s", exc)
        return _fallback(jobs, text, limit, "embedder_failed")

    candidate_ids = [job["job_id"] for job in jobs]
    hits = idx.search_jobs(
        tenant_id, vector, model=model, k=limit, job_ids=candidate_ids
    )
    if not hits:
        return _fallback(jobs, text, limit, "index_empty")

    if fusion_enabled():
        hits = _fuse_with_keyword(idx, embedder=emb, model=model, tenant_id=tenant_id, resume_text=text, vector_hits=hits, limit=limit)

    by_id = {job["job_id"]: job for job in jobs}
    items = [
        _job_item(
            by_id[job_id],
            score,
            _why(by_id[job_id], text, rank, len(hits)),
        )
        for rank, (job_id, score) in enumerate(hits)
        if job_id in by_id
    ]
    return {
        "enabled": True,
        "degraded": False,
        "reason": None,
        "model": model,
        "items": items,
    }


def _resume_vector(
    idx: VectorIndex,
    emb: Embedder,
    tenant_id: str,
    resume_id: str,
    text: str,
) -> list[float]:
    model = emb.storage_model
    sha = VectorIndex.text_sha256(text)
    if idx.resume_sha(tenant_id, resume_id, model=model) == sha:
        cached = idx.get_resume(tenant_id, resume_id, model=model)
        if cached:
            return cached
    vector = emb.embed_many([text])[0]
    idx.upsert_resume(
        tenant_id, resume_id, vector, model=model, text_sha256=sha
    )
    return vector


def fusion_enabled() -> bool:
    """RRF fusion of vector + keyword co-recall (off by default).

    ADR-0065 decision 2 names RRF, but the 2026-10-27 policy evaluation showed
    fusion can hurt when the keyword side is weak (resume A: RRF 0.400 vs
    vector 0.800), so it ships behind its own switch pending re-evaluation.
    """
    return os.environ.get("RESUALIGN_RANKING_FUSION", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _rrf(
    first: Sequence[tuple[str, float]],
    second: Sequence[tuple[str, float]],
    k: int = 60,
) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranking in (first, second):
        for position, (job_id, _score) in enumerate(ranking, 1):
            scores[job_id] = scores.get(job_id, 0.0) + 1.0 / (k + position)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def _keyword_ranking(
    idx: VectorIndex,
    *,
    model: str,
    tenant_id: str,
    resume_text: str,
    job_ids: Sequence[str],
) -> list[tuple[str, float]]:
    """Keyword co-recall from precomputed JD skill sets (no regex per request)."""
    resume_skills = set(detect_skills(resume_text))
    if not resume_skills:
        return []
    jd_skills = idx.job_skills(tenant_id, model=model)
    scored: list[tuple[str, float]] = []
    for job_id in job_ids:
        skills = set(jd_skills.get(job_id) or [])
        if not skills:
            continue
        overlap = len(resume_skills & skills) / len(skills)
        scored.append((job_id, overlap))
    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored


def _fuse_with_keyword(
    idx: VectorIndex,
    *,
    embedder: Embedder,
    model: str,
    tenant_id: str,
    resume_text: str,
    vector_hits: Sequence[tuple[str, float]],
    limit: int,
) -> list[tuple[str, float]]:
    keyword_hits = _keyword_ranking(
        idx,
        model=model,
        tenant_id=tenant_id,
        resume_text=resume_text,
        job_ids=[job_id for job_id, _score in vector_hits],
    )
    if not keyword_hits:
        return list(vector_hits)
    return _rrf(vector_hits, keyword_hits)[:limit]


def _fallback(
    jobs: list[dict[str, Any]], resume_text: str, limit: int, reason: str
) -> dict[str, Any]:
    """No vectors/embedder: order by the stored deterministic match_score."""
    ordered = sorted(
        jobs,
        key=lambda job: (
            job.get("match_score") is None,
            -(job.get("match_score") or 0.0),
            job.get("job_id") or "",
        ),
    )[:limit]
    items = [
        _job_item(
            job,
            job.get("match_score"),
            _why(job, resume_text, rank, len(ordered)),
        )
        for rank, job in enumerate(ordered)
    ]
    return {
        "enabled": True,
        "degraded": True,
        "reason": reason,
        "items": items,
    }


# --------------------------------------------------------------------------- #
# job -> resumes
# --------------------------------------------------------------------------- #
def best_resume(
    tenant_id: str,
    jobs_store: Any,
    resumes_store: Any,
    job_id: str,
    *,
    limit: int = DEFAULT_BEST_RESUME_LIMIT,
    index: VectorIndex | None = None,
    embedder: Embedder | None = None,
) -> dict[str, Any]:
    """Rank the author's master resumes as base drafts for one job.

    Suggestion only: never writes workbench_resume_id (ADR-0065 decision 6).
    """
    job = jobs_store.get_job(tenant_id, job_id)
    if job is None:
        raise KeyError(job_id)
    if not ranking_enabled():
        return _disabled()
    limit = _clamp_limit(limit, maximum=10)

    emb = embedder or _try_embedder()
    if emb is None:
        return _degraded("embedder_unavailable", job_id=job_id)
    idx = index or get_index()
    model = emb.storage_model

    jd_text = (job.get("jd_text") or "").strip()
    if not jd_text:
        return _degraded("job_text_missing", job_id=job_id)
    job_vector = idx.get_job(tenant_id, job_id, model=model)
    if job_vector is None:
        try:
            job_vector = emb.embed_many([jd_text])[0]
        except EmbeddingError as exc:
            logger.warning("job embedding failed: %s", exc)
            return _degraded("embedder_failed", job_id=job_id)
        idx.upsert_job(
            tenant_id,
            job_id,
            job_vector,
            model=model,
            text_sha256=VectorIndex.text_sha256(jd_text),
        )

    scored: list[tuple[dict[str, Any], float]] = []
    for resume in resumes_store.list_master_resumes(tenant_id):
        text = (resume.get("content") or "").strip()
        if not text:
            continue
        try:
            vector = _resume_vector(idx, emb, tenant_id, resume["resume_id"], text)
        except EmbeddingError as exc:
            logger.info("resume embedding skipped (%s): %s", resume["resume_id"], exc)
            continue
        scored.append((resume, _cosine(job_vector, vector)))

    scored.sort(key=lambda item: (-item[1], item[0]["resume_id"]))
    items = [
        {
            "resume_id": resume["resume_id"],
            "title": resume.get("title") or "",
            "current_version": resume.get("current_version"),
            "score": round(score, 4),
            "why": {
                "semantic_percentile": max(
                    0, min(100, round(100 * (1 - rank / max(1, len(scored)))))
                ),
                "skill_hits": _skill_hits(
                    resume.get("content") or "", job.get("jd_text") or ""
                ),
            },
        }
        for rank, (resume, score) in enumerate(scored[:limit])
    ]
    return {
        "enabled": True,
        "degraded": False,
        "reason": None,
        "model": model,
        "job_id": job_id,
        "items": items,
    }


# --------------------------------------------------------------------------- #
# near duplicates (import path)
# --------------------------------------------------------------------------- #
# One embedder call per import batch would be ideal, but the import thread
# already holds the LLM tenant token and this runs after row creation; cap the
# rows that get hints so a 200-row import cannot add minutes of embedding.
IMPORT_HINT_LIMIT = 40


def similar_existing_for_texts(
    tenant_id: str,
    jobs_store: Any,
    texts: Sequence[str],
    *,
    exclude_ids: Sequence[str] | None = None,
    k: int = 5,
    threshold: float = NEAR_DUPLICATE_THRESHOLD,
    index: VectorIndex | None = None,
    embedder: Embedder | None = None,
) -> list[list[dict[str, Any]]]:
    """Batch near-duplicate hints for imported JD texts; never blocks or raises."""
    empty: list[list[dict[str, Any]]] = [[] for _ in texts]
    if not ranking_enabled() or not texts:
        return empty
    payloads = [text if (text or "").strip() else "" for text in texts]
    if not any(payloads):
        return empty
    emb = embedder or _try_embedder()
    if emb is None:
        return empty
    idx = index or get_index()
    if idx.stats(tenant_id)["jobs"]["count"] == 0:
        return empty

    indices = [position for position, text in enumerate(payloads) if text]
    try:
        vectors = emb.embed_many([payloads[position] for position in indices])
    except EmbeddingError:
        logger.info("near-duplicate embedding failed; hints skipped", exc_info=True)
        return empty

    excluded = set(exclude_ids or ())
    results: list[list[dict[str, Any]]] = [[] for _ in texts]
    for position, vector in zip(indices, vectors):
        hits = idx.search_jobs(
            tenant_id,
            vector,
            model=emb.storage_model,
            k=k + len(excluded) + 1,
        )
        rows: list[dict[str, Any]] = []
        for job_id, score in hits:
            if job_id in excluded or score < threshold:
                continue
            job = jobs_store.get_job(tenant_id, job_id)
            if job is None:
                continue
            rows.append(
                {
                    "job_id": job_id,
                    "title": job.get("title") or "",
                    "company": job.get("company") or "",
                    "score": round(score, 4),
                }
            )
        results[position] = rows[:k]
    return results
def similar_existing_jobs(
    tenant_id: str,
    jobs_store: Any,
    jd_text: str,
    *,
    exclude_job_id: str | None = None,
    k: int = 5,
    threshold: float = NEAR_DUPLICATE_THRESHOLD,
    index: VectorIndex | None = None,
    embedder: Embedder | None = None,
) -> list[dict[str, Any]]:
    """Near-duplicate hints for an incoming JD: suggestions only, never blocks."""
    if not ranking_enabled() or not (jd_text or "").strip():
        return []
    emb = embedder or _try_embedder()
    if emb is None:
        return []
    idx = index or get_index()
    try:
        vector = emb.embed_many([jd_text])[0]
    except EmbeddingError:
        return []
    hits = idx.search_jobs(
        tenant_id, vector, model=emb.storage_model, k=k + 1
    )
    results = []
    for job_id, score in hits:
        if job_id == exclude_job_id or score < threshold:
            continue
        job = jobs_store.get_job(tenant_id, job_id)
        if job is None:
            continue
        results.append(
            {
                "job_id": job_id,
                "title": job.get("title") or "",
                "company": job.get("company") or "",
                "score": round(score, 4),
            }
        )
    return results[:k]
