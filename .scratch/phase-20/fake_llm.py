"""FastAPI fake LLM server used by the phase-20 key-path smoke.

QA gate (Q2): the server routes by system-prompt keyword, counts hits per
stage, and treats an unknown system prompt as a hard failure (HTTP 500)
instead of silently falling into a default branch. The smoke script calls
``GET /assert-stages`` before shutdown; the server returns 500 unless every
required stage was hit at least once.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections import Counter

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


app = FastAPI(title="phase20-fake-llm")

# Module-level QA state: per-stage hit counters and unknown-prompt log.
STAGE_HITS: Counter[str] = Counter()
UNKNOWN_PROMPTS: list[str] = []

# E2E control: while E2E_CLASSIFY_FAILS_LEFT > 0, every classifier call
# whose user message carries the marker below fails with HTTP 500, so the
# tests/e2e suite can construct a classification-pending job through the
# real API path (POST /api/jobs catches LLMResponseError and stores the job
# with classification_pending=1). The app retries failed LLM calls
# max_retries+1 = 3 times, so the test sets fails_left=3 before creating the
# job; later calls (reclassify) succeed. The phase-20 smoke never sends the
# marker, so its REQUIRED_STAGES gate is unaffected.
E2E_CLASSIFY_FAIL_MARKER = "__E2E_CLASSIFY_FAIL__"
E2E_CLASSIFY_FAILS_LEFT: int = 0

# Stages the phase-20 key-path smoke must exercise at least once:
#  - job classifier        : session pipeline classification
#  - resume auditor        : workbench diagnosis (no-JD run)
#  - job description analyst : standalone proactive JD profile (no pinned resume)
#  - jd_analysis           : combined JD profile + gap analysis (pinned resume)
#  - precise resume editor : tailoring
#  - resume quality judge  : evaluation (run_eval=False in smoke, so not required)
REQUIRED_STAGES = [
    "job classifier",
    "resume auditor",
    "job description analyst",
    "jd_analysis",
    "precise resume editor",
]


def _resume_from_user(user: str) -> str:
    match = re.search(r"Resume:\n(.*?)\n\nGap Report:", user, re.S)
    return match.group(1).strip() if match else ""


def fake_llm_response(system: str, user: str) -> dict | None:
    """Return a deterministic OpenAI-compatible response per prompt.

    ``None`` marks an unknown system prompt: the caller returns HTTP 500.
    """
    global E2E_CLASSIFY_FAILS_LEFT
    if "job classifier" in system and E2E_CLASSIFY_FAIL_MARKER in user:
        if E2E_CLASSIFY_FAILS_LEFT > 0:
            E2E_CLASSIFY_FAILS_LEFT -= 1
            STAGE_HITS["e2e classify fail"] += 1
            return None
    if "job classifier" in system:
        STAGE_HITS["job classifier"] += 1
        return {
            "job_function": "后端",
            "seniority": "高级",
            "tech_tags": ["Python", "FastAPI"],
        }
    if "resume auditor" in system:
        STAGE_HITS["resume auditor"] += 1
        return {
            "score": 82,
            "skills": ["Python", "FastAPI"],
            "issues": ["Add quantified results."],
        }
    if "job description analyst" in system and "gap analyst" in system:
        STAGE_HITS["jd_analysis"] += 1
        return {
            "jd_profile": {
                "must_have_skills": ["Python", "FastAPI"],
                "nice_to_have_skills": ["Redis", "Docker"],
                "soft_skills": [],
                "business_scenarios": ["high concurrency"],
                "min_years_experience": 5,
                "education_requirements": [],
            },
            "gap_report": {
                "missing_keywords": [
                    "FastAPI async endpoints",
                    "Redis caching for high concurrency",
                ],
                "misaligned_emphasis": [],
                "strength_matches": ["Python"],
            },
        }
    if "job description analyst" in system:
        STAGE_HITS["job description analyst"] += 1
        return {
            "must_have_skills": ["Python", "FastAPI"],
            "nice_to_have_skills": ["Redis", "Docker"],
            "soft_skills": [],
            "business_scenarios": ["high concurrency"],
            "min_years_experience": 5,
            "education_requirements": [],
        }
    if "resume gap analyst" in system:
        STAGE_HITS["resume gap analyst"] += 1
        return {
            "missing_keywords": [
                "FastAPI async endpoints",
                "Redis caching for high concurrency",
            ],
            "misaligned_emphasis": [],
            "strength_matches": ["Python"],
        }
    if "precise resume editor" in system:
        STAGE_HITS["precise resume editor"] += 1
        resume = _resume_from_user(user)
        original = (
            resume.splitlines()[0]
            if resume
            else "# Python Backend Engineer"
        )
        proposed = f"{original} (high concurrency)"
        updated = resume.replace(original, proposed, 1)
        return {
            "sections": {"experience": updated},
            "diffs": [{
                "type": "modify",
                "original": original,
                "proposed": proposed,
                "reason": "Matches JD high-concurrency scenario",
                "confidence": "high",
                "provenance": original,
            }],
        }
    if "resume quality judge" in system:
        STAGE_HITS["resume quality judge"] += 1
        return {
            "jd_match_score": 88,
            "improvement": 12,
            "hallucination_detected": False,
            "hallucination_details": [],
            "gap_coverage": 0.9,
        }
    STAGE_HITS["unknown"] += 1
    return None


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "stage_hits": dict(STAGE_HITS)}


@app.get("/assert-stages")
async def assert_stages() -> dict:
    """Fail unless every required stage was hit at least once."""
    missing = [
        stage for stage in REQUIRED_STAGES if STAGE_HITS.get(stage, 0) < 1
    ]
    if missing:
        return JSONResponse(
            status_code=500,
            content={
                "error": "missing_stage_hits",
                "missing": missing,
                "stage_hits": dict(STAGE_HITS),
            },
        )
    return {"ok": True, "stage_hits": dict(STAGE_HITS)}


@app.post("/control/classify-fail")
async def control_classify_fail(times: int = 1) -> dict:
    """Set how many classifier calls carrying the E2E marker must fail."""
    global E2E_CLASSIFY_FAILS_LEFT
    E2E_CLASSIFY_FAILS_LEFT = max(0, times)
    return {"ok": True, "fails_left": E2E_CLASSIFY_FAILS_LEFT}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> dict:
    body = await request.json()
    stage_delay = float(request.query_params.get("stage_delay", "0"))
    schema_retry = request.query_params.get("schema_retry", "0") == "1"
    invalid_provenance = (
        request.query_params.get("invalid_provenance", "0") == "1"
    )
    if stage_delay > 0:
        await asyncio.sleep(stage_delay)
    messages = body.get("messages", [])
    system = next(
        (m.get("content", "") for m in messages if m.get("role") == "system"),
        "",
    )
    user = next(
        (m.get("content", "") for m in messages if m.get("role") == "user"),
        "",
    )
    payload = fake_llm_response(system, user)
    if payload is None:
        # Unknown system prompt: fail loudly instead of guessing.
        UNKNOWN_PROMPTS.append(system[:200])
        return JSONResponse(
            status_code=500,
            content={
                "error": "unknown_system_prompt",
                "system": system[:200],
            },
        )
    if schema_retry and "precise resume editor" in system:
        payload = {"broken": "schema"}
    if invalid_provenance and "precise resume editor" in system:
        payload["diffs"] = [{
            "type": "add",
            "original": "",
            "proposed": "Led a zero-to-one data platform.",
            "reason": "No source",
            "confidence": "low",
            "provenance": "",
        }]
    return {
        "choices": [{
            "message": {"content": json.dumps(payload, ensure_ascii=False)},
        }],
    }
