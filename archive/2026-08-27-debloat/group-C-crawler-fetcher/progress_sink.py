"""Shared crawl progress sink for URL ingestion and refresh services."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

CRAWL_ORDER = {
    "queued": "fetching",
    "fetching": "parsing",
    "parsing": "classifying",
    "classifying": "succeeded",
}


class CrawlProgressSink:
    """Persist crawl state transitions without swallowing caller errors.

    Both the workbench URL-ingestion path and the scheduled refresh service
    used duplicated ``on_stage`` closures. This class centralises the
    swallow-and-log policy so store failures cannot break a crawl.
    """

    def __init__(
        self,
        crawl_store: Any,
        crawl_id: str,
        tenant_id: str | None = None,
    ) -> None:
        self.crawl_store = crawl_store
        self.crawl_id = crawl_id
        self.tenant_id = tenant_id

    def _update(self, status: str, **kwargs: Any) -> bool:
        try:
            self.crawl_store.update_state(
                self.crawl_id,
                status,
                **kwargs,
            )
        except Exception:  # noqa: BLE001 - a store hiccup must not kill a crawl
            logger.warning(
                "Crawl state update failed for %s", self.crawl_id, exc_info=True
            )
            return False
        return True

    def on_stage(self, stage: str, message: str = "") -> None:
        """Write one crawler progress callback into the crawl row."""
        self._update(
            stage,
            stage=message or stage,
            tenant_id=self.tenant_id,
        )

    def complete(self) -> None:
        """Fast-forward a row to ``succeeded`` through the canonical order."""
        current = self.crawl_store.get(self.crawl_id, self.tenant_id)
        while current and current["status"] != "succeeded":
            next_status = CRAWL_ORDER.get(current["status"])
            if next_status is None:
                break
            advanced = self._update(
                next_status,
                stage=next_status,
                tenant_id=self.tenant_id,
            )
            if not advanced:
                break
            current = self.crawl_store.get(self.crawl_id, self.tenant_id)

    def fail(self, error: str) -> None:
        """Record a terminal failure on the crawl row."""
        self._update("failed", error=error, tenant_id=self.tenant_id)
