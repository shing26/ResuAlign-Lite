"""Scheduled refresh service for URL-sourced library jobs."""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any, Optional

import resualign.api as api_module

from .progress_sink import CrawlProgressSink

logger = logging.getLogger(__name__)

_CLOSED_CATEGORIES = {"empty", "http", "no_content", "selector"}


def _jd_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


class JobRefreshService:
    """Re-crawl an existing URL job and persist the structured diff."""

    def __init__(
        self,
        job_store: Any | None = None,
        crawl_store: Any | None = None,
        crawler_fn: Any | None = None,
    ) -> None:
        self._bound_job_store = job_store
        self._bound_crawl_store = crawl_store
        self._crawler_fn = crawler_fn

    @property
    def store(self) -> Any:
        return self._bound_job_store or api_module._jobs

    @property
    def crawl_store(self) -> Any:
        return self._bound_crawl_store or api_module._crawl_tasks

    def _crawler(self) -> Any:
        return self._crawler_fn or api_module.crawl_jd

    def queue_refresh(
        self,
        tenant_id: str,
        job_id: str,
    ) -> Optional[dict[str, Any]]:
        """Create one refresh crawl task, or return the existing pending one."""
        job = self.store.get_job(tenant_id, job_id)
        if job is None:
            return None
        if job.get("source_type") != "url" or not job.get("source_url"):
            raise api_module.UserStoreError(
                "Only URL-sourced jobs can be refreshed"
            )
        pending = self.crawl_store.pending_by_job(tenant_id, job_id)
        if pending is not None:
            return {
                "queued": False,
                "job_id": job_id,
                "crawl_id": pending["crawl_id"],
                "reason": "already_pending",
            }
        task = self.crawl_store.create(
            tenant_id,
            job["source_url"],
            job_id=job_id,
        )
        return {
            "queued": True,
            "job_id": job_id,
            "crawl_id": task["crawl_id"],
            "reason": "queued",
        }

    def queue_refresh_all(
        self,
        tenant_id: str,
    ) -> list[dict[str, Any]]:
        """Queue refresh tasks for every eligible URL job."""
        results: list[dict[str, Any]] = []
        for job in self.store.list_refresh_candidates(tenant_id):
            try:
                payload = self.queue_refresh(tenant_id, job["job_id"])
            except api_module.UserStoreError as exc:
                payload = {
                    "queued": False,
                    "job_id": job["job_id"],
                    "error": str(exc),
                }
            payload = dict(payload or {})
            payload["title"] = job["title"]
            results.append(payload)
        return results

    def run_refresh(
        self,
        tenant_id: str,
        job_id: str,
        crawl_id: str | None = None,
    ) -> dict[str, Any]:
        """Fetch the job URL, update changed fields, and record the event."""
        job = self.store.get_job(tenant_id, job_id)
        if job is None:
            return {"job_id": job_id, "status": "not_found", "error": "Job not found"}
        url = job.get("source_url")
        if not url:
            return {"job_id": job_id, "status": "failed", "error": "No source URL"}
        if crawl_id is None:
            queued = self.queue_refresh(tenant_id, job_id)
            if queued is None:
                return {
                    "job_id": job_id,
                    "status": "failed",
                    "error": "Job not found",
                }
            crawl_id = queued["crawl_id"]

        progress = CrawlProgressSink(
            self.crawl_store,
            crawl_id,
            tenant_id=tenant_id,
        )

        try:
            meta: dict[str, Any] = {}
            jd_text = self._crawler()(
                url,
                meta=meta,
                on_stage=progress.on_stage,
            )
            now = time.time()
            changed_fields, updates = self._build_updates(job, jd_text, meta)
            if changed_fields:
                updates.update(
                    {
                        "last_refresh_at": now,
                        "refresh_status": "succeeded",
                        "match_stale": 1,
                    }
                )
            else:
                updates.update(
                    {
                        "last_refresh_at": now,
                        "refresh_status": "succeeded",
                    }
                )
            updated = self.store.update_job(
                tenant_id,
                job_id,
                **updates,
            )
            self.store.record_refresh_event(
                tenant_id,
                job_id,
                changed_fields=changed_fields,
                old_summary=self._summary(job),
                new_summary=self._summary(updated or job),
                jd_text_hash=_jd_hash(jd_text),
                status="succeeded",
            )
            progress.complete()
            return {
                "job_id": job_id,
                "crawl_id": crawl_id,
                "status": "succeeded",
                "changed": bool(changed_fields),
                "changed_fields": changed_fields,
                "job": updated,
            }
        except api_module.CrawlError as exc:
            status = "closed" if exc.category in _CLOSED_CATEGORIES else "failed"
            now = time.time()
            self.store.update_job(
                tenant_id,
                job_id,
                last_refresh_at=now,
                refresh_status=status,
            )
            self.store.record_refresh_event(
                tenant_id,
                job_id,
                status=status,
                error=str(exc),
            )
            progress.fail(str(exc))
            return {
                "job_id": job_id,
                "crawl_id": crawl_id,
                "status": status,
                "error": str(exc),
            }
        except Exception as exc:
            now = time.time()
            self.store.update_job(
                tenant_id,
                job_id,
                last_refresh_at=now,
                refresh_status="failed",
            )
            self.store.record_refresh_event(
                tenant_id,
                job_id,
                status="failed",
                error=str(exc)[:300],
            )
            try:
                self.crawl_store.update_state(
                    crawl_id,
                    "failed",
                    error=str(exc)[:300],
                    tenant_id=tenant_id,
                )
            except Exception:
                pass
            logger.exception("Refresh failed for job %s", job_id)
            return {
                "job_id": job_id,
                "crawl_id": crawl_id,
                "status": "failed",
                "error": str(exc)[:300],
            }

    @staticmethod
    def _build_updates(
        job: dict[str, Any],
        jd_text: str,
        meta: dict[str, Any],
    ) -> tuple[list[str], dict[str, Any]]:
        """Return changed field names plus the update_job kwargs to write."""
        derived_title = (
            api_module._derive_title(jd_text)
            if hasattr(api_module, "_derive_title")
            else None
        )
        title = (
            meta.get("title")
            or job.get("title")
            or derived_title
        )
        company = meta.get("company") or job.get("company")
        location = meta.get("city") or job.get("location")
        salary_min, salary_max = api_module.extract_salary_range(jd_text)
        candidates = {
            "jd_text": (job.get("jd_text") or "", jd_text),
            "title": (job.get("title"), title),
            "company": (job.get("company"), company),
            "location": (job.get("location"), location),
            "salary_min": (job.get("salary_min"), salary_min),
            "salary_max": (job.get("salary_max"), salary_max),
        }
        changed: list[str] = []
        updates: dict[str, Any] = {}
        for field, (old, new) in candidates.items():
            if field in {"salary_min", "salary_max"}:
                old_value = old if old is not None else None
                new_value = new if new is not None else None
                if old_value != new_value:
                    changed.append(field)
                    updates[field] = new_value
                continue
            if str(old or "") != str(new or ""):
                changed.append(field)
                updates[field] = new
        return changed, updates

    @staticmethod
    def _summary(job: dict[str, Any] | None) -> str:
        if job is None:
            return ""
        return (
            f"{job.get('title') or ''} | {job.get('company') or ''} | "
            f"{(job.get('jd_text') or '')[:120]}"
        )
