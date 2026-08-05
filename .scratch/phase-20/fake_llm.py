"""FastAPI fake LLM server used by the phase-20 key-path smoke."""

from __future__ import annotations

import asyncio
import json
import re

from fastapi import FastAPI, Request


app = FastAPI(title="phase20-fake-llm")


def _resume_from_user(user: str) -> str:
    match = re.search(r"Resume:\n(.*?)\n\nGap Report:", user, re.S)
    return match.group(1).strip() if match else ""


def fake_llm_response(system: str, user: str) -> dict:
    """Return a deterministic OpenAI-compatible response per prompt."""
    if "job classifier" in system:
        return {
            "job_function": "后端",
            "seniority": "高级",
            "tech_tags": ["Python", "FastAPI"],
        }
    if "resume auditor" in system:
        return {
            "score": 82,
            "skills": ["Python", "FastAPI"],
            "issues": ["Add quantified results."],
        }
    if "job description analyst" in system and "gap analyst" in system:
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
        return {
            "must_have_skills": ["Python", "FastAPI"],
            "nice_to_have_skills": ["Redis", "Docker"],
            "soft_skills": [],
            "business_scenarios": ["high concurrency"],
            "min_years_experience": 5,
            "education_requirements": [],
        }
    if "resume gap analyst" in system:
        return {
            "missing_keywords": [
                "FastAPI async endpoints",
                "Redis caching for high concurrency",
            ],
            "misaligned_emphasis": [],
            "strength_matches": ["Python"],
        }
    if "precise resume editor" in system:
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
        return {
            "jd_match_score": 88,
            "improvement": 12,
            "hallucination_detected": False,
            "hallucination_details": [],
            "gap_coverage": 0.9,
        }
    return {"score": 80, "skills": [], "issues": []}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


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
