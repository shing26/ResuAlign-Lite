"""Sprint 3 fetch pipeline: URL submit -> rule precheck -> crawl -> build.

``JobFetcherService.submit_url`` runs the synchronous pipeline for one JD
URL and returns a small state machine result::

    {'status': 'created'}             job created in the library
    {'status': 'duplicate'}           URL already in the tenant's library
    {'status': 'blocked'}             crawl failed -> blocker_queue entry
    {'status': 'rule_rejected'}       automation rule rejected it

The pipeline is deliberately synchronous: the personal workbench tool
fetches + builds the job before responding, and the frontend awaits the
request (toast on completion). Failures still return fast with a durable
blocker_queue record the user can act on later.
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import urlparse

import resualign.api as api_module

from ...agent.hitl import emit_hitl_event
from ...job_library import _normalize_source_url
from ...rules import RuleFilterEngine

logger = logging.getLogger(__name__)

# ``_jd_parse_error_detail`` already classifies crawl failures into stable
# user-actionable codes; map those codes onto blocker_queue categories.
_DETAIL_CODE_TO_CATEGORY = {
    "blocked_by_policy": "invalid_url",
    "invalid_url": "invalid_url",
    "network_error": "network_error",
    "no_content": "no_content",
    "timeout": "timeout",
    "login_required": "login_required",
    "site_error": "site_error",
}

# Fallback used when the detail mapper is not consulted / returns an unknown
# code: derive the category directly from the crawler's internal category.
_CRAWL_CATEGORY_FALLBACK = {
    "url": "invalid_url",
    "dns": "network_error",
    "empty": "no_content",
    "selector": "no_content",
    "fetch": "fetch_error",
    "http": "site_error",
}


def _validate_url_input(url: str) -> str | None:
    """Return a fast validation error, or None when the URL is plausible."""
    value = (url or "").strip()
    if not value:
        return "链接不能为空"
    parsed = urlparse(value)
    if parsed.scheme.lower() not in ("http", "https"):
        return "链接格式无效，请输入有效的 https:// 招聘链接"
    if not parsed.hostname:
        return "链接格式无效，请输入有效的 https:// 招聘链接"
    if parsed.username or parsed.password:
        return "链接不得包含用户名或密码"
    return None


def _blocker_category_from_error(exc: BaseException) -> str:
    """Map a crawl failure to a blocker_queue category."""
    try:
        detail = api_module._jd_parse_error_detail(exc)
    except Exception:
        detail = None
    code = (detail or {}).get("code")
    if code in _DETAIL_CODE_TO_CATEGORY:
        return _DETAIL_CODE_TO_CATEGORY[code]
    category = getattr(exc, "category", None)
    return _CRAWL_CATEGORY_FALLBACK.get(category, "site_error")


class JobFetcherService:
    """Synchronous URL submit pipeline for the job library."""

    def __init__(
        self,
        store: Any | None = None,
        engine: RuleFilterEngine | None = None,
    ) -> None:
        # Optional bindings for tests. When unset the service resolves
        # ``api_module._jobs`` at call time, so test fixtures that swap the
        # package attribute are picked up automatically.
        self._bound_store = store
        self._bound_engine = engine

    @property
    def store(self) -> Any:
        if self._bound_store is not None:
            return self._bound_store
        return api_module._jobs

    def _engine(self) -> RuleFilterEngine:
        if self._bound_engine is not None:
            return self._bound_engine
        # The engine is stateless; build one per call so a swapped store is
        # always honored.
        return RuleFilterEngine(self.store)

    @staticmethod
    def _emit_blocker_created(blocker: dict[str, Any]) -> None:
        """Fan out the HITL ``blocker.created`` event (webhook or app log).

        Added in Sprint 6 so humans/agents watching ``RESUALIGN_WEBHOOK_URL``
        learn about pipeline blockers without polling. Never raises.
        """
        emit_hitl_event(
            "blocker.created",
            {
                "blocker_id": blocker["blocker_id"],
                "url": blocker.get("url"),
                "reason": blocker.get("reason"),
                "category": blocker.get("category"),
            },
        )

    # -- Automation rules ----------------------------------------------------

    def list_rules(
        self, tenant_id: str, enabled_only: bool = False
    ) -> list[dict[str, Any]]:
        return self.store.list_rules(tenant_id, enabled_only=enabled_only)

    def create_rule(
        self,
        tenant_id: str,
        rule_type: str,
        value: str,
        label: str | None = None,
        enabled: int | bool = 1,
    ) -> dict[str, Any]:
        return self.store.create_rule(
            tenant_id,
            rule_type,
            value,
            label=label,
            enabled=enabled,
        )

    def update_rule(
        self,
        tenant_id: str,
        rule_id: str,
        value: str | None = None,
        label: str | None = None,
        enabled: int | bool | None = None,
    ) -> Optional[dict[str, Any]]:
        return self.store.update_rule(
            tenant_id,
            rule_id,
            value=value,
            label=label,
            enabled=enabled,
        )

    def delete_rule(self, tenant_id: str, rule_id: str) -> bool:
        return self.store.delete_rule(tenant_id, rule_id)

    # -- Blocker queue -------------------------------------------------------

    def get_blocker(
        self, tenant_id: str, blocker_id: str
    ) -> Optional[dict[str, Any]]:
        return self.store.get_blocker(tenant_id, blocker_id)

    def list_blockers(
        self, tenant_id: str, status: str | None = None
    ) -> list[dict[str, Any]]:
        return self.store.list_blockers(tenant_id, status=status)

    def ignore_blocker(
        self, tenant_id: str, blocker_id: str
    ) -> Optional[dict[str, Any]]:
        return self.store.ignore_blocker(tenant_id, blocker_id)

    def resolve_blocker_with_text(
        self,
        tenant_id: str,
        blocker_id: str,
        manual_text: str,
    ) -> Optional[dict[str, Any]]:
        """Create a library job from pasted text and resolve the blocker.

        Returns ``None`` when the blocker does not exist. Raises
        ``UserStoreError`` when the blocker is not pending or the text is
        empty; the blocker stays pending on any failure.
        """
        blocker = self.store.get_blocker(tenant_id, blocker_id)
        if blocker is None:
            return None
        if blocker.get("status") != "pending":
            raise api_module.UserStoreError(
                "Only pending blockers can be resolved"
            )
        text = (manual_text or "").strip()
        if not text:
            raise api_module.UserStoreError("Manual JD text is required")
        user = {"user_id": tenant_id}
        # The pasted text is the source of truth: title/salary are derived
        # from it, never copied from the (possibly URL-only) blocker row.
        job = api_module._create_job_from_source(
            user,
            {
                "jd_text": text,
                "source_type": "paste",
            },
        )
        resolved = self.store.resolve_blocker(
            tenant_id,
            blocker_id,
            job_id=job["job_id"],
            manual_text=text,
        )
        return {"blocker": resolved, "job": job}

    # -- Fetch pipeline ------------------------------------------------------

    def submit_url(self, tenant_id: str, url: str) -> dict[str, Any]:
        """Run the full URL pipeline and return a status-machine dict."""
        url = (url or "").strip()
        error = _validate_url_input(url)
        if error:
            blocker = self.store.create_blocker(
                tenant_id,
                url=url,
                reason=error,
                category="invalid_url",
            )
            self._emit_blocker_created(blocker)
            return self._blocked_payload(blocker)

        # Hash dedupe before spending a crawl on a known URL.
        normalized = _normalize_source_url(url)
        dedupe_key = "url:" + normalized
        existing = self.store.find_by_dedupe_key(tenant_id, dedupe_key)
        if existing is not None:
            return {
                "status": "duplicate",
                "job_id": existing["job_id"],
                "reason": "该链接已在岗位库中",
            }

        # Rule precheck on URL-only metadata (fast reject before crawling).
        pre_verdict = self._engine().check(
            tenant_id, {"url": url}, preflight=True
        )
        if not pre_verdict.accepted:
            blocker = self.store.create_blocker(
                tenant_id,
                url=url,
                title=url,
                reason=pre_verdict.reason or "被自动化规则拦截",
                category="rule_rejected",
            )
            self._emit_blocker_created(blocker)
            return self._rule_rejected_payload(blocker, pre_verdict)

        meta: dict[str, Any] = {}
        try:
            jd_text = api_module.crawl_jd(url, meta=meta)
        except api_module.CrawlError as exc:
            logger.warning(
                "Fetch pipeline crawl failed for %s: %s", url, exc
            )
            detail = api_module._jd_parse_error_detail(exc)
            blocker = self.store.create_blocker(
                tenant_id,
                url=url,
                reason=(detail or {}).get("reason") or str(exc),
                category=_blocker_category_from_error(exc),
            )
            self._emit_blocker_created(blocker)
            return self._blocked_payload(blocker)
        except Exception as exc:
            logger.exception(
                "Fetch pipeline unexpected crawl error for %s", url
            )
            blocker = self.store.create_blocker(
                tenant_id,
                url=url,
                reason=str(exc)[:300],
                category="fetch_error",
            )
            self._emit_blocker_created(blocker)
            return self._blocked_payload(blocker)

        title = self._derive_or_fallback_title(jd_text, meta)
        salary_min, salary_max = api_module.extract_salary_range(jd_text)
        location = meta.get("city")
        company = meta.get("company")

        # Full rule check on the extracted metadata.
        verdict = self._engine().check(
            tenant_id,
            {
                "title": title,
                "jd_text": jd_text,
                "location": location,
                "salary_min": salary_min,
                "salary_max": salary_max,
                "url": url,
            },
        )
        if not verdict.accepted:
            blocker = self.store.create_blocker(
                tenant_id,
                url=url,
                title=title,
                reason=verdict.reason or "被自动化规则拦截",
                category="rule_rejected",
            )
            self._emit_blocker_created(blocker)
            return self._rule_rejected_payload(blocker, verdict)

        user = {"user_id": tenant_id}
        payload: dict[str, Any] = {
            "title": title,
            "jd_text": jd_text,
            "jd_url": url,
            "company": company,
            "location": location,
            "salary_min": salary_min,
            "salary_max": salary_max,
            "source_type": "url",
            "source_url": url,
        }
        try:
            job = api_module._create_job_from_source(user, payload)
        except api_module.UserStoreError as exc:
            if "Duplicate job" in str(exc):
                # Lost a concurrent create race; report the existing row.
                current = self.store.find_by_dedupe_key(
                    tenant_id, dedupe_key
                )
                return {
                    "status": "duplicate",
                    "job_id": current["job_id"] if current else None,
                    "reason": str(exc),
                }
            raise
        return {"status": "created", "job_id": job["job_id"]}

    @staticmethod
    def _derive_or_fallback_title(
        jd_text: str, meta: dict[str, Any]
    ) -> str:
        """Prefer the title derived from rendered JD text, then meta hints."""
        derived = api_module._derive_title(jd_text)
        if derived and derived != "未命名岗位":
            return derived
        return meta.get("title") or derived or "未命名岗位"

    @staticmethod
    def _blocked_payload(blocker: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "blocked",
            "blocker_id": blocker["blocker_id"],
            "category": blocker["category"],
            "reason": blocker["reason"],
            "url": blocker["url"],
        }

    @staticmethod
    def _rule_rejected_payload(
        blocker: dict[str, Any], verdict: Any
    ) -> dict[str, Any]:
        return {
            "status": "rule_rejected",
            "blocker_id": blocker["blocker_id"],
            "category": "rule_rejected",
            "reason": blocker["reason"],
            "rule_type": verdict.rule_type,
            "url": blocker["url"],
        }
