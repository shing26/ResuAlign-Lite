
import hashlib
import json
import logging
import queue
import threading
import time
import uuid
from dataclasses import asdict
from typing import Any, Optional

from fastapi import Request

import resualign.api as api_module
from resualign.jd_profiler import JD_PROFILER_PROMPT_VERSION
from resualign.llm_usage import reset_llm_tenant, set_llm_tenant
from resualign.role_router import call_with_role

logger = logging.getLogger(__name__)
SESSION_TTL_SECONDS = 30 * 60
_SESSION_EVENT_QUEUE_SIZE = 512


def _report_to_dict(report: api_module.Report) -> dict:
    """Convert the Report dataclass tree to a plain JSON-safe dict."""
    data = asdict(report)
    profile = data.get("jd_profile")
    if isinstance(profile, dict):
        data["jd_profile"] = {
            **profile,
            "required_skills": profile.get("must_have_skills") or [],
            "nice_to_have": profile.get("nice_to_have_skills") or [],
            "business_scene": profile.get("business_scenarios") or [],
        }
    return data

def _build_diagnosis_section(result: dict[str, Any]) -> dict[str, Any]:
    """Expose the no-JD diagnosis as a dedicated, self-contained section.

    engine.run() only returns score/skills/issues, so the suggestion list is
    derived from the same issues through actionable rewrite templates instead
    of echoing the issue text back to the user.
    """
    issues = result.get('issues') or []
    skills = result.get('skills') or []
    return {
        'score': result.get('score', 0),
        'skills': skills,
        'issues': issues,
        'suggestions': [
            _suggestion_for_issue(issue, skills) for issue in issues
        ],
        'model': result.get('model', ''),
        'elapsed_seconds': result.get('elapsed_seconds', 0),
    }


def _suggestion_for_issue(issue: str, skills: list[str]) -> str:
    """Return a concrete rewrite action that complements the raw issue."""
    text = str(issue or "").lower()
    if (
        "metric" in text
        or "number" in text
        or ("数据" in text and ("指标" in text or "量化" in text))
    ):
        return (
            "用 STAR 结构补结果量化：把“负责”改为“主导/落地”，"
            "给出吞吐量、耗时、覆盖率或营收等具体数字"
        )
    if "keyword" in text or "关键词" in text or "匹配" in text:
        top = "、".join(str(skill) for skill in skills[:3])
        return (
            f"把经历首行重写成岗位关键词句，优先覆盖 {top or '目标技能'} "
            "等目标能力"
        )
    if (
        "length" in text
        or "太长" in text
        or "冗长" in text
        or "篇幅" in text
    ):
        return "每段经历控制在 3 行以内：技术栈与结果前置，删掉与目标岗位无关的细节"
    if "empty" in text or "空白" in text or "缺失" in text:
        return "补齐最近工作的起止时间、公司/项目名称与职责边界，避免信息断层"
    if "educat" in text or "学历" in text or "教育" in text:
        return "补全教育经历、专业和毕业时间，并按岗位突出课程、论文或竞赛成果"
    if "typ" in text or "语法" in text or "错别字" in text or "格式" in text:
        return "统一标题层级、标点和时间格式，逐段检查错别字，导出 PDF 前再校对一遍"
    if "skill" in text or "技术栈" in text or "技能" in text:
        return "技能按熟练度分组展示，弱化“熟悉/了解”等模糊词，优先排目标岗位强相关技能"
    return "把该问题对应的经历重写为结果导向表达，并补充一条可验证的产出证据"

def _gap_match_score(result: dict[str, Any]) -> Optional[float]:
    """Derive a JD-specific match score from gap analysis when no eval ran."""
    gap = result.get('gap_report') or {}
    missing = len(gap.get('missing_keywords') or [])
    if not missing:
        return 90.0
    return max(30.0, 100.0 - missing * 15.0)

async def _read_timeline_extras(request: Request) -> dict[str, Any]:
    """Read additive pipeline timeline fields without changing the frozen schema."""
    try:
        payload = await request.json()
    except Exception:
        return {}
    return {key: payload.get(key) for key in api_module._TIMELINE_FIELDS if key in payload}

def _apply_diffs(base_text: str, diffs: list[dict[str, Any]], accepted_indices: list[int]) -> tuple[str, int]:
    """Apply accepted diffs to base text in a deterministic, ordered way."""
    draft = base_text
    applied = 0
    for index in sorted(set(accepted_indices)):
        if index < 0 or index >= len(diffs):
            continue
        diff = diffs[index]
        diff_type = diff.get('type', 'modify')
        original = diff.get('original') or ''
        proposed = diff.get('proposed') or ''
        if diff_type == 'modify' and original and proposed:
            if original in draft:
                draft = draft.replace(original, proposed, 1)
                applied += 1
        elif diff_type == 'add' and proposed:
            draft = f'{draft}\n{proposed}'
            applied += 1
        elif diff_type == 'remove' and original and (original in draft):
            draft = draft.replace(original, '', 1)
            applied += 1
    return (draft, applied)


def _utc_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _etag_for(session: dict[str, Any]) -> str:
    """Return a stable entity tag over the public workstation state."""
    base = {
        key: session.get(key)
        for key in (
            "session_id",
            "status",
            "job",
            "jd",
            "resume",
            "gap",
            "alignment",
        )
    }
    payload = json.dumps(
        base, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return '"' + hashlib.sha1(payload.encode("utf-8")).hexdigest() + '"'


def public_state(session: dict[str, Any]) -> dict[str, Any]:
    """Project an internal session record onto the public WorkstationState."""
    return {
        "session_id": session["session_id"],
        "status": session.get("status", "initializing"),
        "job": session.get("job"),
        "jd": session.get("jd"),
        "resume": session.get("resume"),
        "gap": session.get("gap"),
        "alignment": session.get("alignment"),
        "meta": {
            "etag": session.get("_etag") or _etag_for(session),
            "updated_at": session.get("_updated_at") or "",
            "event_url": session.get("_event_url") or "",
        },
    }


class _SessionEventCursor:
    """Per-subscriber event cursor with history replay and heartbeat timeouts."""

    def __init__(self, store: "WorkstationSessionStore", session_id: str) -> None:
        self._store = store
        self._session_id = session_id
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue(
            maxsize=_SESSION_EVENT_QUEUE_SIZE
        )
        with store._lock:
            session = store._sessions[session_id]
            for event in session["events"]:
                try:
                    self._queue.put_nowait(event)
                except queue.Full:
                    break
            session["subscribers"].append(self._queue)

    def next_item(self, timeout: float = 15.0) -> Optional[dict[str, Any]]:
        """Return the next event, or a heartbeat when the stream is idle."""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return {
                "seq": 0,
                "event": "heartbeat",
                "data": {"status": "alive"},
                "created_at": time.time(),
            }

    def close(self) -> None:
        with self._store._lock:
            session = self._store._sessions.get(self._session_id)
            if session is not None and self._queue in session["subscribers"]:
                session["subscribers"].remove(self._queue)


class WorkstationSessionStore:
    """In-memory session registry with a thread-safe SSE event bus.

    Running sessions, partial profiles, tentative diffs, and event fanout are
    intentionally ephemeral (TTL 30 minutes). Terminal alignment products and
    job envelopes live in SQLite (see ADR-0021).
    """

    def __init__(self, ttl_seconds: float = SESSION_TTL_SECONDS) -> None:
        self.ttl_seconds = ttl_seconds
        self._lock = threading.RLock()
        self._sessions: dict[str, dict[str, Any]] = {}

    def create(
        self,
        tenant_id: str,
        session_id: str | None = None,
        **fields: Any,
    ) -> dict[str, Any]:
        with self._lock:
            self._prune()
            sid = session_id or uuid.uuid4().hex
            now = time.time()
            session: dict[str, Any] = {
                "session_id": sid,
                "tenant_id": tenant_id,
                "status": "initializing",
                "job": None,
                "jd": {"profile": None, "status": "queued", "error": None},
                "resume": {
                    "selected_resume_id": None,
                    "available_resumes": [],
                    "content_ref": None,
                },
                "gap": {
                    "status": "queued",
                    "score": None,
                    "gap_report": None,
                    "cache_hit": False,
                    "error": None,
                },
                "alignment": {
                    "status": "idle",
                    "stage": "",
                    "diffs": [],
                    "invalid_diffs": [],
                    "draft": None,
                    "eval_score": None,
                },
                "events": [],
                "subscribers": [],
                "_created_at": now,
                "_updated_at": "",
                "_etag": "",
                "_event_url": f"/api/workbench/session/{sid}/events",
            }
            session.update(fields)
            self._refresh(session)
            self._sessions[sid] = session
            return session

    def get(
        self, session_id: str, tenant_id: str | None = None
    ) -> Optional[dict[str, Any]]:
        with self._lock:
            self._prune()
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if tenant_id is not None and session["tenant_id"] != tenant_id:
                return None
            return session

    def find_by_job(
        self, job_id: str, tenant_id: str
    ) -> Optional[dict[str, Any]]:
        with self._lock:
            self._prune()
            for session in self._sessions.values():
                if session["tenant_id"] != tenant_id:
                    continue
                job = session.get("job") or {}
                if job.get("job_id") == job_id:
                    return session
            return None

    def find_by_idempotency(
        self, tenant_id: str, key: str | None
    ) -> Optional[dict[str, Any]]:
        if not key:
            return None
        with self._lock:
            self._prune()
            for session in self._sessions.values():
                if (
                    session["tenant_id"] == tenant_id
                    and session.get("idempotency_key") == key
                ):
                    return session
            return None

    def update(
        self,
        session_id: str,
        patch: dict[str, Any],
        tenant_id: str | None = None,
    ) -> Optional[dict[str, Any]]:
        with self._lock:
            session = self.get(session_id, tenant_id)
            if session is None:
                return None
            for key, value in patch.items():
                session[key] = value
            self._refresh(session)
            return session

    def emit(
        self,
        session_id: str,
        event: str,
        data: dict[str, Any],
        tenant_id: str | None = None,
    ) -> Optional[dict[str, Any]]:
        with self._lock:
            session = self.get(session_id, tenant_id)
            if session is None:
                return None
            item = {
                "seq": len(session["events"]) + 1,
                "event": event,
                "data": data,
                "created_at": time.time(),
            }
            session["events"].append(item)
            self._refresh(session)
            for subscriber in list(session["subscribers"]):
                try:
                    subscriber.put_nowait(item)
                except queue.Full:
                    pass
            return item

    def events_cursor(
        self, session_id: str, tenant_id: str | None = None
    ) -> Optional[_SessionEventCursor]:
        if self.get(session_id, tenant_id) is None:
            return None
        return _SessionEventCursor(self, session_id)

    def _refresh(self, session: dict[str, Any]) -> None:
        session["_updated_at"] = _utc_timestamp()
        session["_etag"] = _etag_for(session)

    def _prune(self) -> None:
        now = time.time()
        expired = [
            sid
            for sid, session in self._sessions.items()
            if now - session["_created_at"] > self.ttl_seconds
        ]
        for sid in expired:
            self._sessions.pop(sid, None)


def _available_resumes(tenant_id: str) -> list[dict[str, Any]]:
    return [
        {
            "resume_id": resume["resume_id"],
            "title": resume["title"],
            "current_version": resume["current_version"],
        }
        for resume in api_module._resumes.list_master_resumes(tenant_id)
    ]


def _create_library_job_without_llm(
    user: dict[str, Any], payload: dict[str, Any]
) -> dict[str, Any]:
    """Create a library job synchronously without any LLM round trip."""
    jd_text = (payload.get("jd_text") or "").strip()
    jd_url = (payload.get("jd_url") or "").strip()
    if not jd_text:
        raise api_module.UserStoreError("Job description text is required")
    title = (payload.get("title") or "").strip() or api_module._derive_title(jd_text)
    company = (payload.get("company") or "").strip() or None
    location = (payload.get("location") or "").strip() or None
    if not company or not location:
        extracted_company, extracted_location = (
            api_module._extract_company_location(jd_text)
        )
        company = company or extracted_company
        location = location or extracted_location
    salary_min = payload.get("salary_min")
    salary_max = payload.get("salary_max")
    job_functions, seniorities = api_module._settings_vocabulary(user["user_id"])
    return api_module._jobs.create_job(
        tenant_id=user["user_id"],
        title=title,
        jd_text=jd_text,
        company=company,
        location=location,
        salary_min=salary_min,
        salary_max=salary_max,
        salary_currency=payload.get("salary_currency") or "CNY",
        source_type=payload.get("source_type") or ("url" if jd_url else "paste"),
        source_url=payload.get("source_url") or (jd_url or None),
        status=payload.get("status") or "draft",
        classification_pending=1,
        posting_date=payload.get("posting_date"),
        allowed_job_functions=job_functions,
        allowed_seniorities=seniorities,
    )


def _library_dedupe_key(jd_text: str) -> str:
    """Mirror the text dedupe key used by JobLibraryStore.create_job."""
    import hashlib as _hashlib
    import re as _re

    normalized = _re.sub(r"\s+", " ", (jd_text or "").strip().lower())
    return "text:" + _hashlib.sha256(
        normalized.encode("utf-8")
    ).hexdigest()


def _gap_score(gap_report: Any) -> Optional[float]:
    if gap_report is None:
        return None
    missing = len(gap_report.missing_keywords or [])
    if not missing:
        return 90.0
    return max(30.0, 100.0 - missing * 15.0)


def alignment_notice(
    diffs: Any, invalid_diffs: Any, draft: Any = None
) -> Optional[str]:
    """Banner text when an alignment "succeeded" with no actionable product.

    Empty-diff successes previously rendered identically to real successes,
    so users read them as "alignment never completes" (2026-08-30 diagnosis:
    5 of 8 succeeded jobs had zero diffs). The notice names the two empty
    shapes: gate-rejected suggestions vs a model that returned no structured
    diffs at all.
    """
    try:
        diff_count = len(diffs or [])
        invalid_count = len(invalid_diffs or [])
    except TypeError:
        return None
    if diff_count:
        return None
    if invalid_count:
        return (
            f"{invalid_count} 条改写建议因溯源未命中原文被硬门禁拦截："
            "可在「建议复核」中逐条检查，或更换更强模型后重新对齐"
        )
    if str(draft or "").strip():
        return (
            "模型未产出结构化改写建议（仅返回了全文重写）。"
            "建议在设置页更换更强模型后重新对齐，或基于 Live Sheet 手工定稿"
        )
    return "本次对齐未产出任何改写建议，建议更换更强模型后重新对齐"


def _session_sections_from_job(
    job: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Hydrate session sections from a library job's persisted products.

    Terminal alignment products live in SQLite (save_alignment); sessions are
    only runtime state. Reopening a job after a restart must render the
    persisted jd/gap/alignment sections instead of empty placeholders (B6).
    """
    alignment_status = job.get("alignment_status") or "idle"
    return {
        "jd": {
            "profile": job.get("jd_profile"),
            # "ready" matches the read-only workspace contract: the job
            # exists; a missing profile simply means nothing was analyzed
            # yet (the analyze endpoint re-queues from this state).
            "status": "ready",
            "error": None,
        },
        "gap": {
            "status": (
                "ready" if job.get("gap_report") else "blocked"
            ),
            "score": job.get("match_score"),
            "gap_report": job.get("gap_report"),
            "cache_hit": False,
            "error": None,
        },
        "alignment": {
            "status": alignment_status,
            "stage": (
                "done" if alignment_status == "succeeded" else ""
            ),
            "diffs": job.get("diffs") or [],
            "invalid_diffs": job.get("invalid_diffs") or [],
            "draft": job.get("draft"),
            "eval_score": job.get("eval_score"),
            "notice": alignment_notice(
                job.get("diffs"),
                job.get("invalid_diffs"),
                job.get("draft"),
            ),
        },
    }


def _profile_cache_hit(jd_text: str) -> bool:
    try:
        config = api_module.build_config()
        cached = api_module._cache.get(
            "default",
            config.model,
            JD_PROFILER_PROMPT_VERSION,
            jd_text,
        )
        return cached is not None
    except Exception:
        return False


def _run_session_pipeline(session_id: str) -> None:
    """Run the session's background classify/profile pipeline.

    Emits job.stage, job.gap_ready, and job.error events into the in-memory
    event bus. Tailor/eval remain explicitly user-triggered.
    """
    session = api_module._session_store.get(session_id)
    if session is None:
        return
    tenant_id = session["tenant_id"]
    _llm_tenant_token = set_llm_tenant(tenant_id)
    job = session.get("job")
    try:
        if job is None:
            # Crawl retirement (2026-08-30): URL-only sessions are rejected
            # at session/init, so a jobless session here is an anomaly.
            api_module._session_store.emit(
                session_id, "job.error", {"error": "Job could not be created"}
            )
            api_module._session_store.update(session_id, {"status": "failed"})
            return

        api_module._session_store.emit(
            session_id,
            "job.stage",
            {"stage": "classifying", "message": "Classifying job"},
        )
        job_functions, seniorities = api_module._settings_vocabulary(tenant_id)
        try:
            classification = api_module._classify_job(
                job["jd_text"], job_functions, seniorities
            )
            api_module._jobs.update_job(
                tenant_id,
                job["job_id"],
                job_function=classification.get("job_function"),
                seniority=classification.get("seniority"),
                tech_tags=classification.get("tech_tags") or [],
                classification_pending=0,
                allowed_job_functions=job_functions,
                allowed_seniorities=seniorities,
            )
        except api_module.LLMResponseError as exc:
            api_module._session_store.emit(
                session_id,
                "job.stage",
                {
                    "stage": "classifying",
                    "message": f"Classification pending: {exc}",
                },
            )
        job = api_module._jobs.get_job(tenant_id, job["job_id"]) or job

        api_module._session_store.emit(
            session_id,
            "job.stage",
            {"stage": "jd_analysis", "message": "Extracting JD profile"},
        )
        resume = None
        master_resume_id = (
            session.get("master_resume_id")
            or (session.get("resume") or {}).get("selected_resume_id")
        )
        if master_resume_id:
            resume = api_module._resumes.get_master_resume(
                tenant_id, master_resume_id
            )
        resume_text = session.get("resume_text") or (
            resume["content"] if resume else ""
        )
        cache_hit = _profile_cache_hit(job["jd_text"])
        config = api_module.build_config()
        profile_dict: Optional[dict[str, Any]] = None
        gap_dict: Optional[dict[str, Any]] = None
        gap_score: Optional[float] = None
        with api_module.OpenAIClient(config, timeout=90.0) as client:
            if resume_text.strip():
                # Role-based: JD profiler + gap analyst
                # Use same client for both (simpler than parallel for SSE)
                try:
                    profile, meta_profile = call_with_role(
                        "profiler", api_module.profile_jd,
                        api_module._llm_nodes, tenant_id,
                        fn_kwargs={
                            "jd_text": job["jd_text"],
                            "cache": api_module._cache,
                            "tenant": tenant_id,
                        },
                    )
                    profile_dict = api_module.jd_profile_to_dict(profile)
                except Exception:
                    # Fallback to single client
                    profile = api_module.profile_jd(
                        client,
                        job["jd_text"],
                        cache=api_module._cache,
                        tenant=tenant_id,
                    )
                    profile_dict = api_module.jd_profile_to_dict(profile)
                import json as _json
                _profile_str = _json.dumps(profile_dict, ensure_ascii=False)
                try:
                    gap, meta_gap = call_with_role(
                        "gap_analyzer", api_module.analyze_gaps,
                        api_module._llm_nodes, tenant_id,
                        fn_kwargs={
                            "resume_text": resume_text,
                            "jd_profile_text": _profile_str,
                        },
                    )
                    gap_dict = asdict(gap)
                except Exception:
                    gap = api_module.analyze_gaps(
                        client,
                        resume_text,
                        _profile_str,
                    )
                    gap_dict = asdict(gap)
                gap_status = "ready"
                gap_score = _gap_score(gap)
            else:
                try:
                    profile, meta_profile = call_with_role(
                        "profiler", api_module.profile_jd,
                        api_module._llm_nodes, tenant_id,
                        fn_kwargs={
                            "jd_text": job["jd_text"],
                            "cache": api_module._cache,
                            "tenant": tenant_id,
                        },
                    )
                    profile_dict = api_module.jd_profile_to_dict(profile)
                except Exception:
                    profile = api_module.profile_jd(
                        client,
                        job["jd_text"],
                        cache=api_module._cache,
                        tenant=tenant_id,
                    )
                    profile_dict = api_module.jd_profile_to_dict(profile)
                gap_status = "blocked"

        try:
            persisted = api_module._jobs.update_job(
                tenant_id,
                job["job_id"],
                jd_profile=profile_dict,
                gap_report=gap_dict,
                match_score=gap_score,
                allowed_job_functions=job_functions,
                allowed_seniorities=seniorities,
            )
            if persisted is not None:
                job = persisted
        except api_module.UserStoreError:
            logger.exception(
                "Could not persist JD profile for library job %s",
                job["job_id"],
            )
        api_module._session_store.update(
            session_id,
            {
                "status": "ready",
                "job": job,
                "jd": {"profile": profile_dict, "status": "ready", "error": None},
                "gap": {
                    "status": gap_status,
                    "score": gap_score,
                    "gap_report": gap_dict,
                    "cache_hit": cache_hit,
                    "error": None,
                },
            },
        )
        api_module._session_store.emit(
            session_id,
            "job.gap_ready",
            {
                "job_id": job["job_id"],
                "jd_profile": profile_dict,
                "gap_report": gap_dict,
                "status": gap_status,
                "cache_hit": cache_hit,
            },
        )
    except api_module.LLMResponseError as exc:
        api_module._session_store.update(
            session_id,
            {
                "status": "failed",
                "jd": {
                    "profile": None,
                    "status": "failed",
                    "error": str(exc),
                },
            },
        )
        api_module._session_store.emit(
            session_id,
            "job.error",
            {"error": f"JD analysis failed: {exc}", "stage": "jd_analysis"},
        )
    except Exception as exc:
        api_module._session_store.update(
            session_id,
            {"status": "failed", "jd": {"profile": None, "status": "failed", "error": str(exc)}},
        )
        api_module._session_store.emit(
            session_id,
            "job.error",
            {"error": f"Session pipeline failed: {exc}", "stage": "pipeline"},
        )
    finally:
        reset_llm_tenant(_llm_tenant_token)

