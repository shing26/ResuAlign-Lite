"""In-process reminder scheduler for the personal job workbench.

The scheduler only discovers and emits due reminders. Delivery is owned by
``ReminderDeliveryWorker`` so ``reminder_sent_at`` is persisted only after a
successful send and failures can retry.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

from .observability import log_event

logger = logging.getLogger(__name__)


def reminder_interval_seconds(default: int = 60) -> int:
    """Return the configured scheduler tick interval."""
    raw = os.getenv("RESUALIGN_REMINDER_INTERVAL_SECONDS")
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


class ReminderScheduler:
    """Daemon thread that claims due follow-ups and emits structured events.

    It does not claim rows: delivery claims through
    ``claim_pending_reminders`` and only marks ``reminder_sent_at`` after a
    successful send, keeping failure retries and restart idempotency intact.
    """

    def __init__(
        self,
        store: Any,
        interval_seconds: int | None = None,
    ) -> None:
        self._store = store
        self._interval = (
            interval_seconds
            if interval_seconds is not None
            else reminder_interval_seconds()
        )
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._loop,
            name="resualign-reminder-scheduler",
            daemon=True,
        )

    def start(self) -> None:
        if not self._thread.is_alive():
            self._stop.clear()
            self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def tick(self) -> list[dict[str, Any]]:
        now = time.time()
        due = self._store.list_due_reminders(now)
        log_event(
            logger,
            "reminder.scanned",
            extra={
                "due": len(due),
                "interval_seconds": self._interval,
            },
        )
        for job in due:
            log_event(
                logger,
                "reminder.due",
                extra={
                    "job_id": job["job_id"],
                    "tenant_id": job["tenant_id"],
                    "next_step_due_at": job["next_step_due_at"],
                },
            )
        return due

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self.tick()
            except Exception:
                logger.exception("Reminder scheduler tick failed")
