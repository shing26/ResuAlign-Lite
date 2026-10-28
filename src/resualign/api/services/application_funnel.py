"""ADR-0067/C: application funnel and adoption-to-interview observation."""

from __future__ import annotations

from typing import Any


def _rate(numerator: int, denominator: int) -> float | None:
    if not denominator:
        return None
    return round(numerator / denominator, 4)


def build_application_funnel(tenant_id: str, jobs_store: Any) -> dict[str, Any]:
    """Funnel counters plus per-application adoption rows (self-use view)."""
    counts = jobs_store.application_funnel_counts(tenant_id)
    rows: list[dict[str, Any]] = []
    for application in jobs_store.list_job_applications(tenant_id):
        job = jobs_store.get_job(tenant_id, application["job_id"]) or {}
        version_number = int(application.get("final_draft_version") or 0)
        version = None
        if version_number:
            version = jobs_store.get_final_draft_version(
                tenant_id, application["job_id"], version_number
            )
        rows.append({
            "job_id": application["job_id"],
            "job_title": job.get("title") or "",
            "company": job.get("company") or "",
            "applied_at": application.get("applied_at") or "",
            "channel": application.get("channel") or "",
            "final_draft_version": version_number,
            "accepted_count": len((version or {}).get("accepted_diff_ids") or []),
            "status": application.get("status") or "applied",
            "outcome_at": application.get("outcome_at") or "",
        })
    applied = len(rows)
    interviews = sum(1 for row in rows if row["status"] in ("interview", "offer"))
    offers = sum(1 for row in rows if row["status"] == "offer")
    return {
        "counts": counts,
        "applications": rows,
        "rates": {
            "draft_rate": _rate(counts.get("drafts", 0), counts.get("jobs", 0)),
            "applied_rate": _rate(applied, counts.get("drafts", 0)),
            "interview_rate": _rate(interviews, applied),
            "offer_rate": _rate(offers, applied),
        },
        "note": (
            "自用观察口径：interview_rate 分母为已记录投递；样本很小，"
            "只用于自检，不做显著性结论。"
        ),
    }
