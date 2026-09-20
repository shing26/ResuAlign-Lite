
import csv
import html
import io
import logging
import re
import threading
import time
import urllib.parse
import uuid
from typing import Any

from ...alignment_lifecycle import transition_alignment
from ...app.context import context
from ...contracts.errors import LlmFailureCode
from ...job_library import _normalize_source_url, _text_dedupe_key
from ...llm_usage import reset_llm_tenant, set_llm_tenant
from ...observability import new_request_id, reset_request_id, set_request_id
from ...role_router import usable_active_node
from . import llm_probe
from .alignment_rules import is_noop_diff as _is_noop_diff  # noqa: F401
from .alignment_writer import AlignmentOutcome, persist_alignment

logger = logging.getLogger(__name__)


_LOCAL_HOST_PATTERN = re.compile(
    r'^(localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]|::1)$'
)


def _is_local_node(provider: str, base_url: str | None) -> bool:
    """Return True when a node is local-first (Ollama or localhost URL).

    Phase E: local nodes fast-fail on connectivity errors; remote providers
    tolerate transient network blips (see ``_probe_active_llm_quick``).
    """
    if provider == 'ollama':
        # Ollama defaults to localhost; even a LAN Ollama is close enough
        # that fast-fail is the right behavior.
        return True
    if not base_url:
        return False
    try:
        host = urllib.parse.urlparse(base_url).hostname or ''
    except Exception:
        return False
    return bool(_LOCAL_HOST_PATTERN.match(host))


def _probe_active_llm_quick(tenant_id: str) -> tuple[bool, str]:
    """Pre-flight probe of the node that would actually serve the run.

    Phase A1 (2026-08-30): before queueing a workbench run, probe the
    resolved node (persisted active node, else .env/default config) with a
    minimal one-token request. Only *definitive* auth/quota failures
    (HTTP 401/402/403) block the request with an actionable message;
    network errors / timeouts are non-blocking so the job can still be
    queued and its failure surfaced via ``last_alignment_error`` (A3).

    Phase E (2026-08-30): local nodes (Ollama or localhost base_url) also
    fast-fail on network_error/timeout because a down local provider is a
    definitive failure, not a transient blip. Remote providers stay
    non-blocking so a cloud flake never blocks a queued run.

    Returns ``(ok, message)``; ok=True means "proceed".
    """
    try:
        node = usable_active_node(context._llm_nodes, tenant_id)
        provider = ''
        base_url = None
        if node is not None:
            provider = node.get("provider", '')
            api_key = node.get("api_key")
            model = node.get("model", '')
            base_url = node.get("base_url")
        else:
            config = context.build_config()
            provider = config.provider
            api_key = config.api_key
            model = config.model
            base_url = config.base_url
        if not api_key and provider != 'ollama':
            # Missing key is caught upstream by is_llm_configured (503).
            return True, ''
        probe = llm_probe.probe_llm_connection(
            provider=provider,
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout=5.0,
        )
        status = probe.get('status', '')
        # 虚假感修复（#81）：预检结果回写节点健康徽标——欠费/掉线实锤后，
        # 设置页不再显示陈旧的绿点「连通正常」；探测成功也刷新时间戳。
        node_id = node.get("node_id") if node is not None else None
        if node_id and status == 'ok':
            try:
                context._llm_nodes.record_node_health(
                    tenant_id, node_id, 'ok', probe.get('latency_ms')
                )
            except Exception:  # noqa: BLE001 - telemetry must not block runs
                pass
        if status in ('http_401', 'http_402', 'http_403'):
            if node_id:
                try:
                    context._llm_nodes.record_node_health(
                        tenant_id, node_id, status, probe.get('latency_ms')
                    )
                except Exception:  # noqa: BLE001 - telemetry must not block runs
                    pass
            return False, probe.get('message', '模型服务鉴权失败，请检查设置')
        if (
            status in ('network_error', 'timeout')
            and _is_local_node(provider, base_url)
        ):
            return False, probe.get(
                'message', '本地模型服务未就绪，请检查服务是否启动'
            )
        return True, ''
    except Exception:
        # Non-blocking: never let a probe failure block a queued run.
        return True, ''


_tenant_run_gates: dict[str, threading.Lock] = {}
_tenant_gates_lock = threading.Lock()
# P2（2026-09-06 安全审查 #78）：内存生命周期有界化——gate/payload 缓存
# 不再无界增长（多租户长驻进程下 _payloads 还含简历文本与 config）。
_MAX_TENANT_GATES = 4096
_MAX_CACHED_PAYLOADS = 512


def _get_tenant_run_gate(tenant_id: str) -> threading.Lock:
    """Return the per-tenant gate that serializes that tenant's runs.

    Phase E: at most one analysis run per tenant executes at a time so a
    slow local node (Ollama qwen2.5:7b) is never thrashed by concurrent
    alignments from the same account.
    """
    with _tenant_gates_lock:
        gate = _tenant_run_gates.get(tenant_id)
        if gate is None:
            if len(_tenant_run_gates) >= _MAX_TENANT_GATES:
                # 先清未被持有的 gate（不在运行中的租户可安全重建）。
                idle = [
                    key
                    for key, value in _tenant_run_gates.items()
                    if not value.locked()
                ]
                for key in idle:
                    _tenant_run_gates.pop(key, None)
                if len(_tenant_run_gates) >= _MAX_TENANT_GATES:
                    _tenant_run_gates.pop(next(iter(_tenant_run_gates)), None)
            gate = _tenant_run_gates.setdefault(tenant_id, threading.Lock())
        return gate


def _prune_payload_cache() -> None:
    """Bound the in-memory payload cache (P2 #78).

    Completed jobs pop their own entry; queued-backlog or crashed-run
    entries otherwise grow without bound. Overflow entries fall back to the
    registry's stored payload on execution (``_run_job`` reads it when the
    in-memory entry is gone), so pruning never loses a runnable job.
    """
    while len(context._payloads) > _MAX_CACHED_PAYLOADS:
        oldest = next(iter(context._payloads))
        context._payloads.pop(oldest, None)


def _sync_alignment_status(
    tenant_id: str, payload: dict[str, Any], new_status: str
) -> None:
    """Mirror a registry state change into the library job's alignment_status.

    Best-effort: a sync failure must never flip the analysis outcome; the
    startup recovery sweep (``_recover_stale_alignments``) stays as the
    backstop for anything that slips through.
    """
    library_job_id = payload.get('library_job_id')
    if not library_job_id:
        return
    try:
        transition_alignment(
            context._jobs, tenant_id, library_job_id, new_status
        )
    except Exception:
        logger.exception(
            'Failed to sync alignment_status=%s for library job %s',
            new_status,
            library_job_id,
        )


def _emit_stage_progress(
    payload: dict[str, Any], tenant_id: str, stage: str, message: str
) -> None:
    """Push a stage update to the workbench SSE session, when one is bound."""
    library_id = payload.get('library_job_id')
    if not library_id:
        return
    session = context._session_store.find_by_job(library_id, tenant_id)
    if session is None:
        return
    context._session_store.emit(
        session["session_id"],
        "job.stage",
        {
            "stage": stage,
            "message": message,
            "job_id": library_id,
            "workbench": True,
        },
    )


def _run_local_fallback_report(resume_text: str, jd_text: str) -> "context.Report":
    """Build a deterministic rules-only Report when no LLM is configured.

    Mirrors the LLM-backed surface (score / skills / issues / gap report /
    ATS) with pure-Python heuristics so the app stays usable with zero config
    instead of failing on an unconfigured client. Never raises.
    """
    from ...local_fallback import (
        local_ats_score,
        local_diagnose,
        local_gap_report,
    )
    from ...models import EvalScore, GapReport, Report

    diag = local_diagnose(resume_text)
    report = Report(
        score=int(diag.get("score", 0)),
        skills=list(diag.get("skills") or []),
        issues=list(diag.get("issues") or []),
        model="local-rules",
        fallback="local",
    )
    if (jd_text or "").strip():
        gap = local_gap_report(resume_text, jd_text)
        report.gap_report = GapReport(
            missing_keywords=list(gap.get("missing_keywords") or []),
            misaligned_emphasis=list(gap.get("misaligned_emphasis") or []),
            strength_matches=list(gap.get("strength_matches") or []),
        )
        ats = local_ats_score(
            resume_text,
            {"required_skills": report.gap_report.missing_keywords},
        )
        report.eval_score = EvalScore(
            jd_match_score=int(round(float(ats.get("score", 0.0)) * 100)),
            improvement=0,
            hallucination_detected=False,
            hallucination_details=[],
            gap_coverage=float(ats.get("score", 0.0)),
        )
        # Phase 3: offline path must still yield actionable advice. Build
        # clearly-marked placeholder diffs for the top missing keywords —
        # they never claim facts (provenance_state=pending_review), so the
        # anti-fabrication iron rule holds; the user fills in real content.
        from ...models import DiffItem, TailoredResume

        missing = list((report.gap_report.missing_keywords or []))[:5]
        placeholder_diffs = [
            DiffItem(
                diff_id=uuid.uuid4().hex,
                section="项目经历",
                type="add",
                original="",
                proposed=(
                    f"[离线兜底占位] 补充与「{keyword}」相关的经历与量化结果，"
                    "请人工核对简历后填写"
                ),
                reason="离线兜底模式：未配置 LLM，生成占位建议",
                confidence="low",
                provenance="",
                provenance_quote="",
                source_span=None,
                provenance_state="pending_review",
            )
            for keyword in missing
        ]
        report.tailored_resume = TailoredResume(
            sections={},
            diffs=[],
            invalid_diffs=placeholder_diffs,
        )
    return report


_STAGE_LABELS = {
    "diagnose": "简历诊断",
    "jd_analysis": "JD 画像与差距分析",
    "tailoring": "简历定制",
    "evaluation": "效果评估",
    "overview": "整体分析",
    "polishing": "模块化润色",
    "extract": "JD 内容提取",
}


def _job_failure_detail(
    stage: str, exc: BaseException, elapsed_secs: float | None = None
) -> str:
    """Return a readable, stage-aware failure reason for an analysis job.

    Replaces the old generic ``Analysis failed after an internal error`` so
    the workbench can show *where* the run died and why. P0-1: failures are
    classified into actionable copy — timeouts no longer blame the API Key /
    network (the 2026-08-25 walkthrough proved the Key/connectivity were fine
    while the guardrail timeout was the real cause); ``elapsed_secs`` lets the
    timeout branch quote the actual run duration (the workbench also surfaces
    ``elapsed_seconds`` from the snapshot). Return structure stays a plain str.
    """
    stage_label = _STAGE_LABELS.get(stage, stage or "未知阶段")
    message = str(exc) or exc.__class__.__name__
    if isinstance(exc, context.LLMResponseError):
        # R4 P0-1（03-AIE §③）：结构化 code 优先分支，杜绝 message substring 漂移
        # 误归因；code == "other"（旧调用方/测试构造的无 code 异常）回退文本分类。
        code = getattr(exc, "code", LlmFailureCode.OTHER.value)
        if code != LlmFailureCode.OTHER:
            if code == LlmFailureCode.RATE_LIMIT:
                reason = "模型服务繁忙（限流），请稍后重试"
            elif code == LlmFailureCode.QUOTA:
                reason = "模型账户欠费或余额不足，请充值后重试（可先在设置页更换节点）"
            elif code == LlmFailureCode.AUTH:
                reason = "API Key 无效或权限不足，请检查模型设置"
            elif code == LlmFailureCode.TIMEOUT:
                if elapsed_secs is not None:
                    reason = (
                        "模型响应超时（本次耗时 "
                        f"{elapsed_secs:.1f} 秒），可尝试更换更快的模型或稍后重试"
                    )
                else:
                    reason = "模型响应超时，可尝试更换更快的模型或稍后重试"
            elif code == LlmFailureCode.EMPTY:
                reason = "模型返回为空，请重试"
            elif code in (LlmFailureCode.PARSE, LlmFailureCode.SCHEMA):
                reason = "模型返回内容格式异常，请重试或更换模型"
            else:
                reason = "模型服务暂时不可用，请稍后重试"
        else:
            lowered = message.lower()
            if "429" in message or "rate limit" in lowered:
                reason = "模型服务繁忙（限流），请稍后重试"
            elif (
                "401" in message
                or "403" in message
                or "unauthorized" in lowered
                or "authentication" in lowered
                or "invalid api key" in lowered
                or "api key" in lowered
            ):
                # P0-1: 只有 auth 类失败才引导用户检查 API Key（2026-08-25 走查实测
                # Key 有效+连通正常时，超时才是真因，不能一概归因到 Key/网络）。
                reason = "API Key 无效或缺少权限，请检查模型设置"
            elif (
                "timeout" in lowered
                or "timed out" in lowered
                or "time-out" in lowered
            ):
                if elapsed_secs is not None:
                    reason = (
                        "模型响应超时（本次耗时 "
                        f"{elapsed_secs:.1f} 秒），可尝试更换更快的模型或稍后重试"
                    )
                else:
                    reason = "模型响应超时，可尝试更换更快的模型或稍后重试"
            elif (
                "empty response" in lowered
                or "empty content" in lowered
                or "returned empty" in lowered
                or "was empty" in lowered
                or "empty after" in lowered
            ):
                reason = "模型返回为空，请重试"
            elif (
                "expecting value" in lowered
                or "no json object found" in lowered
                or "not a json object" in lowered
                or "invalid json" in lowered
                or "schema validation" in lowered
                or "failed validation" in lowered
            ):
                reason = "模型返回内容格式异常，请重试或更换模型"
            else:
                # P0-1: 未分类失败不再归因 API Key/网络（仅 auth 分支引导查 Key）。
                reason = "模型服务暂时不可用，请稍后重试"
    else:
        reason = message[:300] or "内部错误"
    return f"对齐分析在「{stage_label}」阶段失败：{reason}"

def _settings_vocabulary(user_id: str) -> tuple[list[str], list[str]]:
    """Return the tenant's editable classification vocabulary."""
    vocabulary = context._settings_store.get_settings(user_id)['classification_vocabulary']
    return ([str(item) for item in vocabulary.get('job_functions') or []], [str(item) for item in vocabulary.get('seniorities') or []])

def _classify_job(jd_text: str, job_functions: list[str] | None=None, seniorities: list[str] | None=None, tenant: str="default") -> dict[str, Any]:
    """Classify a JD using the configured LLM client.

    The ``tenant`` scopes the content cache key so classifications never
    leak across tenants (S1). Callers pass the owning user id.
    """
    config = context.build_config()
    with context.OpenAIClient(
        config,
        timeout=45.0,
        # R4 P0-2：classifier 非 role 直连调用，输出钳制 128（03-AIE §③）。
        max_tokens=128,
    ) as client:
        return context.classify_job(
            client,
            jd_text,
            job_functions=job_functions,
            seniorities=seniorities,
            cache=context._cache,
            tenant=tenant,
        )

_TITLE_JOB_KEYWORDS = (
    "工程师", "开发", "经理", "专员", "主管", "总监", "运营", "设计", "产品",
    "算法", "数据", "架构", "测试", "运维", "前端", "后端", "客户端",
    "嵌入式", "研究员", "专家", "顾问", "实习生", "分析师", "策划", "销售",
    "市场", "客服", "老师", "讲师", "助理", "管培",
    "engineer", "developer", "manager", "analyst", "designer", "intern",
)
_TITLE_NOISE_PREFIXES = (
    "公司简介", "企业简介", "公司介绍", "我们正在", "正在寻找", "诚聘",
    "急聘", "招聘简章", "岗位职责", "职位描述", "任职要求", "工作内容",
    "薪资", "薪酬", "工作地点", "公司名称", "公司：", "企业名称",
    "招聘单位", "用人单位", "地点", "城市",
)
_TITLE_BRACKET_RECRUIT = re.compile(r"^【\s*(招聘|急聘|诚聘|高薪|直招)\s*】")
_TITLE_BRACKET_PREFIX = re.compile(r"^【[^】]*】\s*")
_TITLE_LEAD_RECRUIT = re.compile(
    r"^(?:公司|企业|单位)?\s*(?:招聘|急聘|诚聘|高薪诚聘|直招)\s*"
)
_TITLE_ROLE_PREFIX = re.compile(r"^(岗位|职位|岗位名称|职位名称)\s*[:：]\s*")
_TITLE_SALARY_SUFFIX = re.compile(
    r"\s*\d+(?:\.\d+)?\s*[kK万]?\s*[-—~到]?\s*\d+(?:\.\d+)?\s*[kK万]\S*(?:\s+\S+)*"
    r"|\s*\d+(?:\.\d+)?\s*[kK万]\S*(?:\s+\S+)*"
)
_TITLE_INLINE_SPLIT = re.compile(
    r"[，,；;。]|"
    r"\s*(?:岗位职责|职位描述|任职要求|工作内容|工作职责|岗位要求|"
    r"职位要求|公司简介|企业简介|薪资待遇|薪酬福利|工作地点)\s*"
)
_COMPANY_FIELD_RE = re.compile(
    r"(?:公司|企业|招聘单位|用人单位|单位)\s*(?:名称)?\s*[:：]\s*"
    r"([^\n\r，,；;|]+)"
)
_LOCATION_FIELD_RE = re.compile(
    r"(?:工作地点|工作城市|工作地址|办公地点|办公地址|所在城市|"
    r"工作地|地点|城市)\s*[:：]\s*([^\n\r，,；;|]+)"
)

def _clean_title_candidate(line: str) -> str:
    """Normalize a candidate line into a readable job title."""
    candidate = line.strip().lstrip('#-*·• ').strip()
    candidate = _TITLE_BRACKET_RECRUIT.sub("", candidate)
    candidate = _TITLE_BRACKET_PREFIX.sub("", candidate)
    candidate = _TITLE_LEAD_RECRUIT.sub("", candidate).strip(" 【】")
    candidate = _TITLE_ROLE_PREFIX.sub("", candidate).strip()
    candidate = _TITLE_SALARY_SUFFIX.sub("", candidate).strip(" ，,·-—–")
    return candidate[:120]

def _is_title_noise(line: str) -> bool:
    """Return True for lines that are not plausible job titles."""
    stripped = line.strip().lstrip('#-*·• ').strip()
    if not stripped:
        return True
    if _TITLE_BRACKET_RECRUIT.search(stripped):
        remainder = _TITLE_BRACKET_RECRUIT.sub("", stripped).strip()
        if not any(
            keyword in remainder.lower() for keyword in _TITLE_JOB_KEYWORDS
        ):
            return True
    if any(stripped.startswith(prefix) for prefix in _TITLE_NOISE_PREFIXES):
        return True
    if re.match(r'^https?://', stripped, re.IGNORECASE):
        return True
    if re.match(r'^\d+(?:\.\d+)?\s*[kK万]', stripped):
        return True
    return False

def _derive_title(jd_text: str) -> str:
    """Derive a job title from JD text, skipping company/recruit noise lines."""
    raw = jd_text or ''
    if '\n' not in raw:
        lines = [
            part.strip()
            for part in _TITLE_INLINE_SPLIT.split(raw)
            if part.strip()
        ]
    else:
        lines = raw.splitlines()
    first_clean: str | None = None
    for line in lines:
        if _is_title_noise(line):
            continue
        candidate = _clean_title_candidate(line)
        if not candidate:
            continue
        if first_clean is None:
            first_clean = candidate
        if any(keyword in candidate.lower() for keyword in _TITLE_JOB_KEYWORDS):
            return candidate
    return first_clean or '未命名岗位'


def _extract_company_location(
    jd_text: str,
) -> tuple[str | None, str | None]:
    """Extract an explicit company and location from labeled JD fields."""
    company: str | None = None
    location: str | None = None
    for line in (jd_text or "").splitlines():
        if company is None:
            match = _COMPANY_FIELD_RE.search(line)
            if match:
                company = match.group(1).strip().strip(" 　，,;；|") or None
        if location is None:
            match = _LOCATION_FIELD_RE.search(line)
            if match:
                location = match.group(1).strip().strip(" 　，,;；|") or None
        if company and location:
            break
    return company, location

def _deterministic_job_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Resolve title/company/location/salary without any LLM round-trip."""
    jd_text = (payload.get('jd_text') or '').strip()
    title = (payload.get('title') or '').strip() or context._derive_title(jd_text)
    company = (payload.get('company') or '').strip() or None
    location = (payload.get('location') or '').strip() or None
    if not company or not location:
        extracted_company, extracted_location = _extract_company_location(jd_text)
        company = company or extracted_company
        location = location or extracted_location
    salary_min = payload.get('salary_min')
    salary_max = payload.get('salary_max')
    return {
        'title': title,
        'company': company,
        'location': location,
        'salary_min': salary_min,
        'salary_max': salary_max,
    }


def _create_job_from_source(user: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Derive/extract/classify one job and store it in the library.

    De-bloat (2026-08-27): backend crawling is retired. A URL-only payload
    (``jd_url`` without ``jd_text``) is rejected with a pointer to the
    collector userscript / paste flow instead of crawling the network.
    """
    payload = dict(payload or {})
    jd_text = (payload.get('jd_text') or '').strip()
    jd_url = (payload.get('jd_url') or '').strip()
    if jd_url and (not jd_text):
        raise context.UserStoreError(
            '该岗位只有链接没有 JD 文本：请用浏览器油猴插件抓取，或用「粘贴 JD」方式录入'
        )
    if not jd_text:
        raise context.UserStoreError('Job description text is required')
    payload['jd_text'] = jd_text
    fields = _deterministic_job_fields(payload)
    title = fields['title']
    company = fields['company']
    location = fields['location']
    salary_min = fields['salary_min']
    salary_max = fields['salary_max']
    job_functions, seniorities = context._settings_vocabulary(user['user_id'])
    classification = {}
    classification_pending = 0
    try:
        classification = context._classify_job(
            jd_text, job_functions, seniorities, tenant=user['user_id']
        )
    except context.LLMResponseError as exc:
        logger.warning('Job classification failed, storing as pending: %s', exc)
        classification_pending = 1
    source_type = payload.get('source_type') or ('url' if jd_url else 'paste')
    job_function = payload.get('job_function') or classification.get('job_function')
    seniority = payload.get('seniority') or classification.get('seniority')
    return context._jobs.create_job(tenant_id=user['user_id'], title=title, jd_text=jd_text, company=company, location=location, salary_min=salary_min, salary_max=salary_max, salary_currency=payload.get('salary_currency') or 'CNY', source_type=source_type, source_url=payload.get('source_url') or (jd_url or None), job_function=job_function, seniority=seniority, tech_tags=payload.get('tech_tags') or classification.get('tech_tags') or [], status=payload.get('status') or '未投递', classification_pending=classification_pending, posting_date=payload.get('posting_date'), applied_at=payload.get('applied_at'), next_step=payload.get('next_step'), notes=payload.get('notes'), offer_at=payload.get('offer_at'), rejected_at=payload.get('rejected_at'), allowed_job_functions=job_functions, allowed_seniorities=seniorities)


def _local_ingest_job(
    user: dict[str, Any], payload: dict[str, Any]
) -> dict[str, Any]:
    """Create a classification-pending library job from the collector script.

    The request path is deterministic only: title/company/location/salary
    come from page fields or the existing regex derivation, and duplicates
    are resolved by URL (specific sites) or normalized JD text (universal).
    """
    jd_text = (payload.get('jd_text') or '').strip()
    if not jd_text:
        raise context.UserStoreError('Job description text is required')
    site = (payload.get('site') or 'universal').strip().lower()
    job_page_url = (payload.get('job_page_url') or '').strip()
    fields = _deterministic_job_fields(payload)
    if site == 'universal':
        dedupe_key = _text_dedupe_key(jd_text)
    else:
        normalized_url = (
            _normalize_source_url(job_page_url) if job_page_url else ''
        )
        dedupe_key = (
            'url:' + normalized_url
            if normalized_url
            else _text_dedupe_key(jd_text)
        )
    existing = context._jobs.find_by_dedupe_key(
        user['user_id'], dedupe_key
    )
    if existing is not None:
        return {
            'status': 'duplicate',
            'job_id': existing['job_id'],
            'job': existing,
        }
    job = context._jobs.create_job(
        tenant_id=user['user_id'],
        title=fields['title'],
        jd_text=jd_text,
        company=fields['company'],
        location=fields['location'],
        salary_min=fields['salary_min'],
        salary_max=fields['salary_max'],
        salary_currency=payload.get('salary_currency') or 'CNY',
        source_type='url' if job_page_url else 'paste',
        source_url=job_page_url or None,
        status='未投递',
        classification_pending=1,
        dedupe_key=dedupe_key,
    )
    return {'status': 'created', 'job_id': job['job_id'], 'job': job}

def _collect_import_rows(req: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = list(req.jobs or [])
    if (req.csv_text or '').strip():
        reader = csv.DictReader(io.StringIO(req.csv_text))
        for row in reader:
            rows.append({key: value or None for key, value in row.items()})
    return rows

def _run_import(import_id: str) -> None:
    """Process a queued import batch on a daemon worker thread."""
    batch = context._import_batches.get(import_id)
    if batch is None:
        return
    user = {'user_id': batch['user_id']}
    _llm_tenant_token = set_llm_tenant(batch['user_id'])
    try:
        for row in batch['rows']:
            if not (row.get('jd_text') or '').strip() and (not (row.get('jd_url') or '').strip()):
                batch['skipped'] += 1
                batch['errors'].append(f"{row.get('title') or 'Untitled'}: empty JD")
                continue
            try:
                context._create_job_from_source(user, row)
                batch['created'] += 1
            except (context.UserStoreError, context.LLMResponseError) as exc:
                batch['skipped'] += 1
                batch['errors'].append(f"{row.get('title') or 'Untitled'}: {exc}")
    except Exception as exc:
        logger.exception('Import batch %s failed', import_id)
        batch['errors'].append(f'Import batch failed: {exc}')
    finally:
        reset_llm_tenant(_llm_tenant_token)
        batch['done'] = True
        context._prune_import_batches()

def _prune_import_batches(max_kept: int=50) -> None:
    """Drop finished import batches once the in-memory backlog grows."""
    done_ids = [import_id for import_id, batch in context._import_batches.items() if batch.get('done')]
    if len(done_ids) <= max_kept:
        return
    for import_id in sorted(done_ids)[:len(done_ids) - max_kept]:
        context._import_batches.pop(import_id, None)

def _queue_job(user: dict[str, Any], payload: dict[str, Any], application_id: str | None=None, workbench: bool=False) -> str:
    """Create a job row, keep its payload in memory, and start the worker."""
    config = context.build_config()
    # R4 P0-6（03-AIE §③）：入口统一护栏 —— 每日 cap + 同一 job 连续失败熔断
    # （防无脑重试烧额度）。job_ref_key 仅工作台重试携带（library_job_id）。
    # P1-1：enforce 内部已原子预留每日 cap 名额，把预留标记带进 payload，
    # 任务结束时未消费则释放。
    reserved_slot = context.enforce_llm_task_entry(
        user['user_id'], job_ref_key=(payload or {}).get('library_job_id')
    )
    if reserved_slot:
        payload['llm_slot_reserved'] = True
    job = context._registry.create(payload, config, tenant_id=user['user_id'], application_id=application_id)
    payload['workbench'] = workbench
    context._payloads[job.job_id] = (payload, config, application_id, user['user_id'])
    _prune_payload_cache()
    if application_id:
        context._applications.set_application_job(user['user_id'], application_id, job.job_id, 'running')
    threading.Thread(target=context._run_job, args=(job.job_id,), daemon=True).start()
    return job.job_id

def _run_job(job_id: str) -> None:
    """Execute one queued analysis job on a bounded worker thread.

    Phase E (2026-08-30): a per-tenant gate guarantees at most one run per
    tenant at a time (an Ollama 7B node must not be thrashed). The gate is
    acquired before the global worker semaphore so a flooded tenant cannot
    occupy every global slot.

    Ticket #101: the worker runs outside the request context, so restore the
    job row's persisted request_id (minting one for pre-migration rows) for
    the whole run — every structured log on this thread then correlates to
    the triggering click.
    """
    _request_id_token = set_request_id(
        context._registry.request_id_for(job_id) or new_request_id()
    )
    try:
        entry = context._payloads.get(job_id)
        if entry is not None:
            tenant_id = entry[3]
        else:
            stored = context._registry.get_payload(job_id)
            if stored is None:
                return
            tenant_id = stored[1]
        gate = _get_tenant_run_gate(tenant_id)
        gate.acquire()
        try:
            _run_job_holding_gate(job_id)
        finally:
            gate.release()
    finally:
        reset_request_id(_request_id_token)


def _run_job_holding_gate(job_id: str) -> None:
    """Run one queued analysis job; caller already holds the tenant gate."""
    with context._WORKER_SEMAPHORE:
        claimed = _claim_queued_job(job_id)
        if claimed is None:
            return
        payload, config, application_id, tenant_id = claimed
        _llm_tenant_token = set_llm_tenant(tenant_id)
        # P1-1（2026-09-06 安全审查）：入队时若预留了每日 cap 名额，记录
        # 起点调用数；任务结束一次真实 LLM 调用都没发生（缓存全命中或早期
        # 失败）就释放预留，避免缓存重跑逐步吃光当日额度。发生过调用时
        # record_call 已消费预留，无需释放。
        reserved_slot = bool(payload.get('llm_slot_reserved'))
        calls_before = (
            context._llm_usage.get_usage(tenant_id)['calls']
            if reserved_slot
            else None
        )
        failed_stage: str = ''
        # t0 is set once the run phase starts; the shared list lets the
        # failure classifier quote the real elapsed time without NameError
        # for claims that fail before the run phase.
        t0: list[float | None] = [None]

        def on_stage(stage: str, message: str) -> None:
            nonlocal failed_stage
            failed_stage = stage
            context._registry.update_progress(job_id, stage, message)
            _emit_stage_progress(payload, tenant_id, stage, message)

        try:
            result = _execute_claimed_job(
                job_id, payload, config, tenant_id, on_stage, t0
            )
            if result is None:
                return
            library_job_id = payload.get('library_job_id')
            if library_job_id:
                # Persist the library alignment product BEFORE marking the
                # registry job succeeded. If save_alignment crashes, the
                # registry job stays non-terminal and startup recovery can
                # requeue or flag it instead of leaving a succeeded job with
                # no durable product.
                outcome = persist_alignment(
                    tenant_id, job_id, payload, result
                )
                _notify_alignment_outcome(tenant_id, payload, result, outcome)
            context._registry.succeed(job_id, result)
            _link_application_job(
                tenant_id, application_id, job_id, 'succeeded'
            )
        except Exception as exc:
            _fail_claimed_job(
                job_id,
                payload,
                tenant_id,
                application_id,
                failed_stage,
                exc,
                t0[0],
            )
        finally:
            _release_job_resources(
                job_id, tenant_id, calls_before, _llm_tenant_token
            )


def _claim_queued_job(
    job_id: str,
) -> tuple[dict[str, Any], Any, str | None, str] | None:
    """Resolve the payload/config and atomically claim a queued job.

    Returns ``None`` when the payload is gone or another worker already
    claimed the job. Keeps the tenant gate held by the caller.
    """
    entry = context._payloads.get(job_id)
    if entry is not None:
        payload, config, application_id, tenant_id = entry
    else:
        stored = context._registry.get_payload(job_id)
        if stored is None:
            return None
        payload, tenant_id, application_id = stored
        config = context.build_config()
    job = context._registry.get(job_id)
    if job is None or job.status != 'queued':
        return None
    if not context._registry.claim_running(job_id):
        # Another worker already claimed this job; do not double-run.
        return None
    _sync_alignment_status(tenant_id, payload, 'running')
    return payload, config, application_id, tenant_id


def _execute_claimed_job(
    job_id: str,
    payload: dict[str, Any],
    config: Any,
    tenant_id: str,
    on_stage: Any,
    t0: list[float | None],
) -> dict[str, Any] | None:
    """Run the claimed job's actual work; ``None`` means already finalized."""
    jd_text = (payload.get('jd_text') or '').strip()
    # De-bloat: backend crawling retired; a URL-only queued job without JD
    # text cannot be recovered and fails with a clear reason.
    if payload.get('jd_url') and (not jd_text):
        context._registry.fail(
            job_id,
            '该岗位只有链接没有 JD 文本：请用浏览器油猴插件抓取，或用「粘贴 JD」方式重新录入',
        )
        _sync_alignment_status(tenant_id, payload, 'failed')
        return None
    if payload.get('optimize_resume'):
        result = context._run_resume_optimize(payload, on_stage, tenant_id)
        context._registry.succeed(job_id, result)
        return None
    use_local_fallback = (
        not config.is_llm_configured
        and usable_active_node(context._llm_nodes, tenant_id) is None
    )
    t0[0] = time.monotonic()
    if use_local_fallback:
        report = _run_local_fallback_report(payload['resume_text'], jd_text)
    else:
        report = context.run(
            config,
            payload['resume_text'],
            jd_text,
            run_eval=bool(payload.get('run_eval', False)),
            granularity=payload.get('granularity', 'medium'),
            prompt_focus=payload.get('prompt_focus', 'balanced'),
            custom_prompt=payload.get('custom_prompt', ''),
            diagnosis=payload.get('precomputed_diagnosis'),
            on_stage=on_stage,
            cache=context._cache,
            tenant=tenant_id,
            node_store=context._llm_nodes,
            tenant_id=tenant_id,
        )
    report.elapsed_seconds = round(time.monotonic() - t0[0], 1)
    result = context._report_to_dict(report)
    if payload.get('diagnosis'):
        result['diagnosis'] = context._build_diagnosis_section(result)
        result['diagnosis_source_hash'] = context._content_sha256(
            payload.get('resume_text') or ''
        )
        # R4 §3.6：诊断快照内嵌提示词版本（P3，04b-PE 建议），随快照整包
        # JSON 序列化持久化，便于追溯快照对应的提示词文本。
        from resualign.llm import DIAG_PROMPT_VERSION

        result['diagnosis']['prompt_version'] = DIAG_PROMPT_VERSION
        _persist_diagnosis_snapshot(tenant_id, payload, result)
    return result


def _persist_diagnosis_snapshot(
    tenant_id: str, payload: dict[str, Any], result: dict[str, Any]
) -> None:
    """Best-effort diagnosis snapshot persistence for a master resume."""
    master_resume_id = payload.get('master_resume_id')
    if not master_resume_id:
        return
    try:
        context._resumes.set_latest_diagnosis_snapshot(
            tenant_id,
            master_resume_id,
            result['diagnosis'],
            result['diagnosis_source_hash'],
        )
    except Exception:
        logger.exception(
            'Failed to persist diagnosis snapshot for master resume %s',
            master_resume_id,
        )


def _link_application_job(
    tenant_id: str,
    application_id: str | None,
    job_id: str,
    status: str,
) -> None:
    """Best-effort application link update; never flips the analysis outcome."""
    if not application_id:
        return
    try:
        context._applications.set_application_job(
            tenant_id, application_id, job_id, status
        )
    except Exception:
        logger.exception(
            'Failed to link application %s to %s job %s',
            application_id,
            status,
            job_id,
        )


def _fail_claimed_job(
    job_id: str,
    payload: dict[str, Any],
    tenant_id: str,
    application_id: str | None,
    failed_stage: str,
    exc: BaseException,
    started_at: float | None,
) -> None:
    """Classify and persist a failed run, then update linked state."""
    # De-bloat: the CrawlError branch was removed with the crawler; every
    # failure (including LLM/structure errors) now lands here and is
    # classified into a user-readable reason below.
    logger.exception('Analysis job %s failed', job_id)
    elapsed_secs = (
        round(time.monotonic() - started_at, 1)
        if started_at is not None
        else None
    )
    if payload.get('diagnosis'):
        # G4（03-AIE §②-gap G4）：诊断分支不再硬编码「请检查 API Key 与
        # 网络连接」——经由 _job_failure_detail 按结构化 code 分类归因。
        error = context._job_failure_detail(
            failed_stage or 'diagnose', exc, elapsed_secs
        ).replace('对齐分析', '诊断任务')
    elif payload.get('optimize_resume'):
        error = context._job_failure_detail(
            failed_stage, exc, elapsed_secs
        ).replace('对齐分析', '简历优化')
    else:
        error = context._job_failure_detail(failed_stage, exc, elapsed_secs)
    context._registry.fail(job_id, error, stage=failed_stage or None)
    # Phase 3 + A3: persist the failure reason on the library job so a failed
    # alignment stays diagnosable after the in-memory registry restarts.
    # Kept as a direct update_job (instead of _sync_alignment_status) because
    # the sync helper does not carry last_alignment_error; transition
    # legality is not at risk here — failed is a terminal state reachable
    # from any live state.
    library_job_id = payload.get('library_job_id')
    if library_job_id:
        try:
            context._jobs.update_job(
                tenant_id,
                library_job_id,
                alignment_status='failed',
                last_alignment_error=error,
            )
        except Exception:
            logger.exception(
                'Failed to persist alignment error for library job %s',
                library_job_id,
            )
    _link_application_job(tenant_id, application_id, job_id, 'failed')


def _release_job_resources(
    job_id: str,
    tenant_id: str,
    calls_before: int | None,
    llm_tenant_token: Any,
) -> None:
    """Reset LLM tenant state, release an unused daily slot, drop the payload."""
    reset_llm_tenant(llm_tenant_token)
    if calls_before is not None:
        try:
            calls_after = context._llm_usage.get_usage(tenant_id)['calls']
            if calls_after == calls_before:
                context._llm_usage.release_call(tenant_id)
        except Exception:  # noqa: BLE001 - accounting must not break jobs
            logger.exception(
                'Failed to release daily LLM slot for job %s', job_id
            )
    context._registry.delete_payload(job_id)
    context._payloads.pop(job_id, None)


def _notify_alignment_outcome(
    tenant_id: str,
    payload: dict[str, Any],
    result: dict[str, Any],
    outcome: "AlignmentOutcome",
) -> None:
    """Emit the workbench result events for a persisted alignment run."""
    library_job_id = outcome.library_job_id
    session = context._session_store.find_by_job(library_job_id, tenant_id)
    if session is None:
        return
    for index, diff in enumerate(outcome.kept_diffs):
        context._session_store.emit(
            session["session_id"],
            "tailor.diff",
            {
                "job_id": library_job_id,
                "diff_id": diff.get("diff_id"),
                "index": index,
                "tentative": True,
            },
        )
    context._session_store.update(
        session["session_id"],
        {
            "job": context._jobs.get_job(tenant_id, library_job_id),
            "alignment": {
                "status": outcome.alignment_status,
                "stage": "done",
                "diffs": result.get("diffs") or [],
                "invalid_diffs": outcome.invalid_diffs,
                "draft": outcome.draft,
                "eval_score": outcome.eval_score,
                "notice": (
                    context._alignment_notice(
                        result.get("diffs") or [],
                        outcome.invalid_diffs,
                        outcome.draft,
                    )
                ),
            },
        },
    )
    context._session_store.emit(
        session["session_id"],
        "job.result",
        {
            "job_id": library_job_id,
            "result": result,
        },
    )
def _export_filename(job: dict[str, Any], ext: str) -> str:
    """Build a filesystem-friendly suggested export filename."""
    title = re.sub(r'[\\/:*?"<>|]+', "-", (job.get("title") or "job").strip())
    title = re.sub(r"\s+", "-", title).strip("-") or "job"
    version = int(job.get("final_draft_version") or 1)
    return f"resualign-{title}-v{version}.{ext}"


def _accepted_diffs(job: dict[str, Any]) -> list[dict[str, Any]]:
    """Return diffs marked accepted by a persisted final-draft save."""
    return [
        diff
        for diff in (job.get("diffs") or [])
        if isinstance(diff, dict)
        and diff.get("provenance_state") == "accepted"
    ]


def _export_plain_text(draft: str) -> str:
    """Render a Markdown draft as plain text without Markdown markers.

    Bug-03: the JSON export keeps ``content`` as a readable, structure-
    free rendering (heading markers #/##, bullet markers -/* and blank
    lines removed) so downstream consumers never receive raw Markdown.
    """
    lines_out: list[str] = []
    for line in (draft or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("## "):
            lines_out.append(stripped[3:].strip())
        elif stripped.startswith("#"):
            lines_out.append(stripped.lstrip("#").strip())
        elif stripped.startswith(("- ", "* ")):
            lines_out.append(stripped[2:].strip())
        else:
            lines_out.append(stripped)
    return "\n".join(lines_out)


def _iter_sections(draft: str):
    """Yield ``(heading, body_lines)`` for each ``## `` section.

    The aligned draft is authored with ``## `` level-2 headings
    (联系方式/工作经历/项目经历/专业技能...).  The H1 title belongs to
    job_title/meta and is not repeated as a section; the preamble before
    the first heading is skipped.
    """
    heading: str | None = None
    body: list[str] = []
    for line in (draft or "").splitlines():
        if line.startswith("## "):
            if heading is not None:
                yield heading, body
            heading = line[3:].strip()
            body = []
        elif heading is not None:
            body.append(line)
    if heading is not None:
        yield heading, body


def _export_sections(draft: str) -> list[dict[str, Any]]:
    """Split a Markdown final draft into its ordered ``## `` sections."""
    sections: list[dict[str, Any]] = []
    for heading, body in _iter_sections(draft):
        content = "\n".join(line for line in body if line.strip()).strip()
        sections.append({"heading": heading, "content": content})
    return sections


_SKILL_SECTION_HEADING_RE = re.compile(
    r"^(专业技能|技能清单|技能|skills?)$", re.IGNORECASE
)


def _draft_declared_skills(draft: str) -> list[str]:
    """Extract the bullet skills from the final draft's skills section."""
    skills: list[str] = []
    for heading, body in _iter_sections(draft):
        if not _SKILL_SECTION_HEADING_RE.match(heading):
            continue
        for line in body:
            stripped = line.strip()
            if not stripped.startswith("- "):
                continue
            item = stripped[2:].strip()
            if not item:
                continue
            if "：" in item or ":" in item:
                separator = "：" if "：" in item else ":"
                values = item.partition(separator)[2]
                parts = [
                    part.strip()
                    for part in re.split(r"[、，,;；]", values)
                    if part.strip()
                ]
                skills.extend(parts or [item])
            else:
                skills.append(item)
        break
    seen: set[str] = set()
    unique: list[str] = []
    for skill in skills:
        if skill not in seen:
            seen.add(skill)
            unique.append(skill)
    return unique


def _export_skills(job: dict[str, Any], draft: str) -> list[str]:
    """Skill list for the JSON export.

    Declared skills come from the final draft's skills section; when the
    draft has none, fall back to the JD must-have list so downstream
    consumers still get a usable skill set.
    """
    declared = _draft_declared_skills(draft)
    if declared:
        return declared
    jd_profile = job.get("jd_profile") or {}
    return list(jd_profile.get("must_have_skills") or [])

def build_job_export(
    job: dict[str, Any],
    fmt: str,
) -> dict[str, Any]:
    """Build the canonical export payload from persisted library fields."""
    draft = (job.get("final_draft") or "").strip()
    accepted = _accepted_diffs(job)
    # 匹配分双口径修复（#82）：界面与导出统一区分「AI 评估」与「规则四维」
    # 两个口径，同名不同值不再并存。
    match_detail = job.get("match_score_detail")
    eval_score = job.get("eval_score")
    meta = {
        "model": job.get("model"),
        "prompt_version": job.get("prompt_version"),
        "generated_at": job.get("generated_at"),
        "final_draft_updated_at": job.get("final_draft_updated_at"),
        "match_score": job.get("match_score"),
        "eval_match_score": (
            eval_score.get("jd_match_score")
            if isinstance(eval_score, dict)
            else None
        ),
        "rule_match_score": (
            match_detail.get("total")
            if isinstance(match_detail, dict)
            else None
        ),
        "workbench_resume_id": job.get("workbench_resume_id"),
    }
    version = int(job.get("final_draft_version") or 0)
    base = {
        "job_id": job.get("job_id"),
        "job_title": job.get("title") or "未命名岗位",
        "format": fmt,
        "final_draft_version": version,
        "meta": meta,
        "accepted_diff_ids": [
            diff.get("diff_id")
            for diff in accepted
            if diff.get("diff_id")
        ],
        "accepted_diffs": accepted,
    }
    if fmt == "json":
        return {
            **base,
            "sections": _export_sections(draft),
            "skills": _export_skills(job, draft),
            "content": _export_plain_text(draft),
            "filename": _export_filename(job, "json"),
        }
    if fmt == "pdf":
        return {
            **base,
            "content": _export_print_html(job, draft, accepted, meta),
            "filename": _export_filename(job, "pdf"),
            "render": "print-html",
            "print_target": "#print-root",
        }
    return {
        **base,
        "content": _export_markdown(job, draft, accepted, meta),
        "filename": _export_filename(job, "md"),
    }


def _export_meta_lines(meta: dict[str, Any], version: int) -> list[str]:
    """Render human-readable export metadata as Markdown list items."""
    def iso(value: float | None) -> str:
        if value is None:
            return "-"
        try:
            return time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(float(value))
            )
        except (TypeError, ValueError, OSError):
            return "-"

    return [
        f"- 定稿版本：v{version}",
        f"- 模型：{meta.get('model') or '-'}",
        f"- 生成配置版本：{meta.get('prompt_version') or '-'}",
        f"- 生成时间：{iso(meta.get('generated_at'))}",
        f"- 保存时间：{iso(meta.get('final_draft_updated_at'))}",
        *_match_score_meta_lines(meta),
    ]


def _match_score_meta_lines(meta: dict[str, Any]) -> list[str]:
    """匹配分元信息（#82 双口径）：AI 评估分与规则四维分分别标注，不再
    用同一个「匹配分」名字承载两个数值。"""
    lines: list[str] = []
    if meta.get("eval_match_score") is not None:
        lines.append(f"- 匹配分（AI 评估）：{meta['eval_match_score']}")
    if meta.get("rule_match_score") is not None:
        lines.append(f"- 匹配分（规则四维）：{meta['rule_match_score']}")
    if not lines and meta.get("match_score") is not None:
        lines.append(f"- 匹配分：{meta['match_score']}")
    return lines


def _export_markdown(
    job: dict[str, Any],
    draft: str,
    accepted: list[dict[str, Any]],
    meta: dict[str, Any],
) -> str:
    lines = [f"# {job.get('title') or '未命名岗位'}", ""]
    lines.extend(_export_meta_lines(meta, int(job.get("final_draft_version") or 0)))
    lines.extend(["", "## 定稿内容", "", draft, ""])
    if accepted:
        lines.append("## 采纳项")
        lines.append("")
        for diff in accepted:
            lines.append(
                f"- **{diff.get('diff_id') or '未知'}** "
                f"[{diff.get('section') or '未分区'}] "
                f"({diff.get('type') or 'modify'}): "
                f"{diff.get('proposed') or diff.get('original') or ''}"
            )
    else:
        lines.append("## 采纳项")
        lines.append("")
        lines.append("- 无已采纳 diff")
    return "\n".join(lines).rstrip() + "\n"


def _export_print_html(
    job: dict[str, Any],
    draft: str,
    accepted: list[dict[str, Any]],
    meta: dict[str, Any],
) -> str:
    title = html.escape(job.get("title") or "未命名岗位")
    # 匹配分双口径（#82）：分别标注 AI 评估与规则四维。
    match_rows = {"定稿版本": f"v{job.get('final_draft_version') or 0}",
                  "模型": meta.get("model") or "-",
                  "生成配置版本": meta.get("prompt_version") or "-"}
    if meta.get("eval_match_score") is not None:
        match_rows["匹配分（AI 评估）"] = str(meta["eval_match_score"])
    if meta.get("rule_match_score") is not None:
        match_rows["匹配分（规则四维）"] = str(meta["rule_match_score"])
    if "匹配分（AI 评估）" not in match_rows and "匹配分（规则四维）" not in match_rows:
        match_rows["匹配分"] = (
            str(meta.get("match_score"))
            if meta.get("match_score") is not None
            else "-"
        )
    meta_rows = "".join(
        f"<tr><th>{html.escape(str(key))}</th><td>{html.escape(str(value))}</td></tr>"
        for key, value in match_rows.items()
    )
    accepted_html = ""
    if accepted:
        accepted_html = "".join(
            f"<li>{html.escape(str(diff.get('diff_id') or '未知'))} · "
            f"{html.escape(str(diff.get('section') or '未分区'))} · "
            f"{html.escape(str(diff.get('type') or 'modify'))}</li>"
            for diff in accepted
        )
        accepted_html = f"<h2>采纳项</h2><ul>{accepted_html}</ul>"
    return (
        "<article class=\"export-article\">"
        f"<h1>{title}</h1>"
        f"<table>{meta_rows}</table>"
        "<h2>定稿内容</h2>"
        f"<pre>{html.escape(draft)}</pre>"
        f"{accepted_html}"
        "</article>"
    )
