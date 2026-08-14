
import csv
import io
import logging
import re
import threading
import time
from typing import Any

from fastapi import HTTPException

import resualign.api as api_module

from ..schemas import JobImportRequest

logger = logging.getLogger(__name__)

_STAGE_LABELS = {
    "diagnose": "简历诊断",
    "jd_analysis": "JD 画像与差距分析",
    "tailoring": "简历定制",
    "evaluation": "效果评估",
    "extract": "JD 内容提取",
}


def _job_failure_detail(stage: str, exc: BaseException) -> str:
    """Return a readable, stage-aware failure reason for an analysis job.

    Replaces the old generic ``Analysis failed after an internal error`` so
    the workbench can show *where* the run died and why.
    """
    stage_label = _STAGE_LABELS.get(stage, stage or "未知阶段")
    message = str(exc) or exc.__class__.__name__
    if isinstance(exc, api_module.LLMResponseError):
        reason = "模型服务暂时不可用或返回异常，请检查 API Key 与网络连接后重试"
    else:
        reason = message[:300] or "内部错误"
    return f"对齐分析在「{stage_label}」阶段失败：{reason}"

def _settings_vocabulary(user_id: str) -> tuple[list[str], list[str]]:
    """Return the tenant's editable classification vocabulary."""
    vocabulary = api_module._settings_store.get_settings(user_id)['classification_vocabulary']
    return ([str(item) for item in vocabulary.get('job_functions') or []], [str(item) for item in vocabulary.get('seniorities') or []])

def _classify_job(jd_text: str, job_functions: list[str] | None=None, seniorities: list[str] | None=None, tenant: str="default") -> dict[str, Any]:
    """Classify a JD using the configured LLM client.

    The ``tenant`` scopes the content cache key so classifications never
    leak across tenants (S1). Callers pass the owning user id.
    """
    config = api_module.build_config()
    with api_module.OpenAIClient(config, timeout=45.0) as client:
        return api_module.classify_job(
            client,
            jd_text,
            job_functions=job_functions,
            seniorities=seniorities,
            cache=api_module._cache,
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
    "薪资", "薪酬", "工作地点",
)
_TITLE_BRACKET_RECRUIT = re.compile(r"^【\s*(招聘|急聘|诚聘|高薪|直招)\s*】")
_TITLE_ROLE_PREFIX = re.compile(r"^(岗位|职位|岗位名称|职位名称)\s*[:：]\s*")
_TITLE_SALARY_SUFFIX = re.compile(
    r"\s*\d+(?:\.\d+)?\s*[kK万]?\s*[-—~到]?\s*\d+(?:\.\d+)?\s*[kK万]\S*(?:\s+\S+)*"
    r"|\s*\d+(?:\.\d+)?\s*[kK万]\S*(?:\s+\S+)*"
)

def _clean_title_candidate(line: str) -> str:
    """Normalize a candidate line into a readable job title."""
    candidate = line.strip().lstrip('#-*·• ').strip()
    candidate = _TITLE_BRACKET_RECRUIT.sub("", candidate).strip(" 【】")
    candidate = _TITLE_ROLE_PREFIX.sub("", candidate).strip()
    candidate = _TITLE_SALARY_SUFFIX.sub("", candidate).strip(" ，,·-—–")
    return candidate[:120]

def _is_title_noise(line: str) -> bool:
    """Return True for lines that are not plausible job titles."""
    stripped = line.strip().lstrip('#-*·• ').strip()
    if not stripped:
        return True
    if _TITLE_BRACKET_RECRUIT.search(stripped):
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
    lines = (jd_text or '').splitlines()
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

def _crawl_jd_or_502(jd_url: str, meta: dict[str, Any] | None=None) -> str:
    """Crawl a JD URL, mapping crawler failures to a stable 502 response."""
    try:
        return api_module.crawl_jd(jd_url, meta=meta)
    except api_module.CrawlError as exc:
        logger.warning('JD crawl failed for %s: %s', jd_url, exc)
        raise HTTPException(status_code=502, detail=api_module._jd_parse_error_detail(exc)) from exc

def _jd_parse_error_detail(exc: api_module.CrawlError) -> dict[str, str]:
    """Map a crawl failure to a user-actionable, non-leaking classification."""
    message = str(exc.args[0]) if exc.args else str(exc)
    lowered = message.lower()
    if exc.category == 'url':
        if 'private or local' in lowered or 'not globally routable' in lowered:
            return {'code': 'blocked_by_policy', 'reason': '该链接被安全策略拦截，可能是内网地址或非公开招聘页', 'action': '请确认链接为公开职位页，或改用粘贴 JD'}
        return {'code': 'invalid_url', 'reason': '链接格式无效，请输入有效的 https:// 招聘链接', 'action': '请检查链接后重试，或改用粘贴 JD'}
    if exc.category == 'dns':
        return {'code': 'network_error', 'reason': '无法解析目标站点，可能是网络问题或链接已失效', 'action': '请确认链接可访问，或改用粘贴 JD'}
    if exc.category in ('empty', 'selector'):
        return {'code': 'no_content', 'reason': '该站点无法直接读取正文，可能需要登录或动态加载', 'action': '请改用粘贴 JD 或更换链接重试'}
    if exc.category == 'fetch':
        if 'timeout' in lowered or 'timed out' in lowered:
            return {'code': 'timeout', 'reason': '链接解析超时，站点可能暂时不可用', 'action': '请改用粘贴 JD 或稍后重试'}
        return {'code': 'network_error', 'reason': '无法连接到目标站点，可能是网络问题或站点暂时不可用', 'action': '请改用粘贴 JD 或稍后重试'}
    if exc.category == 'http':
        if 'too many redirects' in lowered:
            return {'code': 'site_error', 'reason': '站点重定向异常，无法完成解析', 'action': '请改用粘贴 JD 或更换链接重试'}
        status_match = re.search('HTTP (\\d{3})', message)
        status = int(status_match.group(1)) if status_match else None
        if status in (401, 403):
            return {'code': 'login_required', 'reason': '该站点需要登录或权限，无法直接读取正文', 'action': '请改用粘贴 JD 或更换链接重试'}
        return {'code': 'site_error', 'reason': '目标站点返回错误，暂时无法解析正文', 'action': '请改用粘贴 JD 或稍后重试'}
    return {'code': 'site_error', 'reason': '未能解析该岗位链接', 'action': '请改用粘贴 JD 或稍后重试'}

def _create_job_from_source(user: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Crawl/derive/extract/classify one job and store it in the library."""
    jd_text = (payload.get('jd_text') or '').strip()
    jd_url = (payload.get('jd_url') or '').strip()
    if jd_url and (not jd_text):
        jd_text = api_module.crawl_jd(jd_url)
    if not jd_text:
        raise api_module.UserStoreError('Job description text is required')
    title = (payload.get('title') or '').strip() or api_module._derive_title(jd_text)
    salary_min = payload.get('salary_min')
    salary_max = payload.get('salary_max')
    if salary_min is None or salary_max is None:
        extracted_min, extracted_max = api_module.extract_salary_range(jd_text)
        salary_min = salary_min if salary_min is not None else extracted_min
        salary_max = salary_max if salary_max is not None else extracted_max
    job_functions, seniorities = api_module._settings_vocabulary(user['user_id'])
    classification = {}
    classification_pending = 0
    try:
        classification = api_module._classify_job(
            jd_text, job_functions, seniorities, tenant=user['user_id']
        )
    except api_module.LLMResponseError as exc:
        logger.warning('Job classification failed, storing as pending: %s', exc)
        classification_pending = 1
    source_type = payload.get('source_type') or ('url' if jd_url else 'paste')
    job_function = payload.get('job_function') or classification.get('job_function')
    seniority = payload.get('seniority') or classification.get('seniority')
    return api_module._jobs.create_job(tenant_id=user['user_id'], title=title, jd_text=jd_text, company=payload.get('company'), location=payload.get('location'), salary_min=salary_min, salary_max=salary_max, salary_currency=payload.get('salary_currency') or 'CNY', source_type=source_type, source_url=payload.get('source_url') or (jd_url or None), job_function=job_function, seniority=seniority, tech_tags=payload.get('tech_tags') or classification.get('tech_tags') or [], status=payload.get('status') or '未投递', classification_pending=classification_pending, posting_date=payload.get('posting_date'), applied_at=payload.get('applied_at'), next_step=payload.get('next_step'), notes=payload.get('notes'), offer_at=payload.get('offer_at'), rejected_at=payload.get('rejected_at'), allowed_job_functions=job_functions, allowed_seniorities=seniorities)

def _collect_import_rows(req: JobImportRequest) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = list(req.jobs or [])
    if (req.csv_text or '').strip():
        reader = csv.DictReader(io.StringIO(req.csv_text))
        for row in reader:
            rows.append({key: value or None for key, value in row.items()})
    return rows

def _run_import(import_id: str) -> None:
    """Process a queued import batch on a daemon worker thread."""
    batch = api_module._import_batches.get(import_id)
    if batch is None:
        return
    user = {'user_id': batch['user_id']}
    try:
        for row in batch['rows']:
            if not (row.get('jd_text') or '').strip() and (not (row.get('jd_url') or '').strip()):
                batch['skipped'] += 1
                batch['errors'].append(f"{row.get('title') or 'Untitled'}: empty JD")
                continue
            try:
                api_module._create_job_from_source(user, row)
                batch['created'] += 1
            except (api_module.UserStoreError, api_module.CrawlError, api_module.LLMResponseError) as exc:
                batch['skipped'] += 1
                batch['errors'].append(f"{row.get('title') or 'Untitled'}: {exc}")
    except Exception as exc:
        logger.exception('Import batch %s failed', import_id)
        batch['errors'].append(f'Import batch failed: {exc}')
    finally:
        batch['done'] = True
        api_module._prune_import_batches()

def _prune_import_batches(max_kept: int=50) -> None:
    """Drop finished import batches once the in-memory backlog grows."""
    done_ids = [import_id for import_id, batch in api_module._import_batches.items() if batch.get('done')]
    if len(done_ids) <= max_kept:
        return
    for import_id in sorted(done_ids)[:len(done_ids) - max_kept]:
        api_module._import_batches.pop(import_id, None)

def _queue_job(user: dict[str, Any], payload: dict[str, Any], application_id: str | None=None, workbench: bool=False) -> str:
    """Create a job row, keep its payload in memory, and start the worker."""
    config = api_module.build_config()
    job = api_module._registry.create(payload, config, tenant_id=user['user_id'], application_id=application_id)
    payload['workbench'] = workbench
    api_module._payloads[job.job_id] = (payload, config, application_id, user['user_id'])
    if application_id:
        api_module._applications.set_application_job(user['user_id'], application_id, job.job_id, 'running')
    threading.Thread(target=api_module._run_job, args=(job.job_id,), daemon=True).start()
    return job.job_id

def _run_job(job_id: str) -> None:
    """Execute one queued analysis job on a bounded worker thread."""
    with api_module._WORKER_SEMAPHORE:
        entry = api_module._payloads.get(job_id)
        if entry is not None:
            payload, config, application_id, tenant_id = entry
        else:
            stored = api_module._registry.get_payload(job_id)
            if stored is None:
                return
            payload, tenant_id, application_id = stored
            config = api_module.build_config()
        try:
            job = api_module._registry.get(job_id)
            if job is None or job.status != 'queued':
                return
            if not api_module._registry.claim_running(job_id):
                # Another worker already claimed this job; do not double-run.
                return

            failed_stage: str = ''

            def on_stage(stage: str, message: str) -> None:
                nonlocal failed_stage
                failed_stage = stage
                api_module._registry.update_progress(job_id, stage, message)
                library_id = payload.get('library_job_id')
                if library_id:
                    session = api_module._session_store.find_by_job(
                        library_id, tenant_id
                    )
                    if session is not None:
                        api_module._session_store.emit(
                            session["session_id"],
                            "job.stage",
                            {
                                "stage": stage,
                                "message": message,
                                "job_id": library_id,
                                "workbench": True,
                            },
                        )
            jd_text = (payload.get('jd_text') or '').strip()
            if payload.get('jd_url') and (not jd_text):
                jd_text = api_module.crawl_jd(payload['jd_url'])
            t0 = time.monotonic()
            report = api_module.run(
                config,
                payload['resume_text'],
                jd_text,
                run_eval=bool(payload.get('run_eval', False)),
                granularity=payload.get('granularity', 'medium'),
                prompt_focus=payload.get('prompt_focus', 'balanced'),
                custom_prompt=payload.get('custom_prompt', ''),
                diagnosis=payload.get('precomputed_diagnosis'),
                on_stage=on_stage,
                cache=api_module._cache,
                tenant=tenant_id,
            )
            report.elapsed_seconds = round(time.monotonic() - t0, 1)
            result = api_module._report_to_dict(report)
            if payload.get('diagnosis'):
                result['diagnosis'] = api_module._build_diagnosis_section(result)
                result['diagnosis_source_hash'] = api_module._content_sha256(payload.get('resume_text') or '')
                master_resume_id = payload.get('master_resume_id')
                if master_resume_id:
                    try:
                        api_module._resumes.set_latest_diagnosis_snapshot(
                            tenant_id,
                            master_resume_id,
                            result['diagnosis'],
                            result['diagnosis_source_hash'],
                        )
                    except Exception:
                        logger.exception(
                            'Failed to persist diagnosis snapshot for '
                            'master resume %s',
                            master_resume_id,
                        )
            # Persist the library alignment product BEFORE marking the
            # registry job succeeded. If save_alignment crashes, the registry
            # job stays non-terminal and startup recovery can requeue or flag
            # it instead of leaving a succeeded job with no durable product.
            library_job_id = payload.get('library_job_id')
            if library_job_id:
                tailored = result.get('tailored_resume') or {}
                sections = tailored.get('sections') or {}
                draft = (
                    "\n\n".join(str(value) for value in sections.values())
                    if sections
                    else None
                )
                eval_score = result.get('eval_score')
                match_score = (
                    eval_score.get('jd_match_score')
                    if eval_score
                    else None
                )
                if match_score is None:
                    match_score = api_module._gap_match_score(result)
                session = api_module._session_store.find_by_job(
                    library_job_id, tenant_id
                )
                if session is not None:
                    for index, diff in enumerate(result.get("diffs") or []):
                        api_module._session_store.emit(
                            session["session_id"],
                            "tailor.diff",
                            {
                                "job_id": library_job_id,
                                "diff_id": diff.get("diff_id"),
                                "index": index,
                                "tentative": True,
                            },
                        )
                try:
                    api_module._jobs.save_alignment(
                        tenant_id,
                        library_job_id,
                        jd_profile=result.get('jd_profile'),
                        gap_report=result.get('gap_report'),
                        match_score=match_score,
                        diffs=result.get('diffs') or [],
                        invalid_diffs=tailored.get('invalid_diffs') or [],
                        draft=draft,
                        eval_score=eval_score,
                        model=result.get('model') or '',
                        prompt_version='engine.v1',
                        alignment_status='succeeded',
                    )
                except Exception:
                    logger.exception(
                        'Failed to persist alignment for library job %s; '
                        'keeping analysis job %s non-terminal for recovery',
                        library_job_id,
                        job_id,
                    )
                    raise
                if session is not None:
                    api_module._session_store.update(
                        session["session_id"],
                        {
                            "job": api_module._jobs.get_job(
                                tenant_id, library_job_id
                            ),
                            "alignment": {
                                "status": "succeeded",
                                "stage": "done",
                                "diffs": result.get("diffs") or [],
                                "invalid_diffs": (
                                    tailored.get("invalid_diffs") or []
                                ),
                                "draft": draft,
                                "eval_score": eval_score,
                            },
                        },
                    )
                    api_module._session_store.emit(
                        session["session_id"],
                        "job.result",
                        {
                            "job_id": library_job_id,
                            "result": result,
                        },
                    )
            api_module._registry.succeed(job_id, result)
            if application_id:
                try:
                    api_module._applications.set_application_job(
                        tenant_id, application_id, job_id, 'succeeded'
                    )
                except Exception:
                    # The analysis itself succeeded; an application link
                    # update failure must not flip the job to failed.
                    logger.exception(
                        'Failed to link application %s to succeeded job %s',
                        application_id,
                        job_id,
                    )
        except api_module.CrawlError as exc:
            api_module._registry.fail(job_id, f'Failed to crawl JD from URL: {exc}')
            if application_id:
                try:
                    api_module._applications.set_application_job(tenant_id, application_id, job_id, 'failed')
                except Exception:
                    logger.exception(
                        'Failed to link application %s after crawl failure %s',
                        application_id,
                        job_id,
                    )
        except Exception as exc:
            logger.exception('Analysis job %s failed', job_id)
            if payload.get('diagnosis'):
                error = '诊断任务暂时失败：模型服务不可用或返回异常，请检查 API Key 与网络连接后重试'
            else:
                error = api_module._job_failure_detail(
                    failed_stage, exc
                )
            api_module._registry.fail(job_id, error, stage=failed_stage or None)
            if application_id:
                try:
                    api_module._applications.set_application_job(tenant_id, application_id, job_id, 'failed')
                except Exception:
                    logger.exception(
                        'Failed to link application %s after failure %s',
                        application_id,
                        job_id,
                    )
        finally:
            api_module._registry.delete_payload(job_id)
            api_module._payloads.pop(job_id, None)

