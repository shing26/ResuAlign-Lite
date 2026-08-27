"""Reminder delivery worker: webhook and SMTP fan-out for due follow-ups.

The worker consumes the scheduler's due queue through atomic store claims.
Delivery success is the only event that persists ``reminder_sent_at``;
failures schedule an exponential retry and are logged without ever
blocking the API request path or the scheduler loop.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
import threading
import time
from datetime import date, timedelta
from email.message import EmailMessage
from typing import Any

import httpx

from .config import EnvSettings
from .observability import log_event

logger = logging.getLogger(__name__)

_DELIVERY_TIMEOUT = 10.0
_WEBHOOK_RETRIES = 2
_MAX_CLAIM_ATTEMPTS = 3
_LEASE_SECONDS = 300.0

WEBHOOK_PROVIDERS = ("generic", "feishu", "wecom", "telegram")
AUTO_FOLLOWUP_MESSAGE = "投递后跟进"


def auto_followup_due_at(
    applied_at: str | None = None,
    *,
    days: int = 3,
    delivery_hour: int = 9,
) -> str:
    """Return the due timestamp for an automatic post-application follow-up."""
    base = (applied_at or "").strip()[:10]
    if not base:
        base = time.strftime("%Y-%m-%d")
    try:
        applied_date = date.fromisoformat(base)
    except ValueError:
        applied_date = date.today()
    due = applied_date + timedelta(days=days)
    return f"{due.isoformat()}T{delivery_hour:02d}:00:00"


def reminder_delivery_interval_seconds(default: int = 30) -> int:
    """Return the configured delivery worker tick interval."""
    raw = EnvSettings().resualign_reminder_interval_seconds
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return default


def reminder_configuration(settings_store: Any = None) -> dict[str, Any]:
    """Resolve effective reminder delivery config without exposing secrets.

    Non-secret SMTP fields and the enabled/provider flags come from the
    persisted settings store; webhook URL/secret and SMTP password only ever
    come from environment variables (via ``EnvSettings``).
    """
    env = EnvSettings()
    stored: dict[str, Any] = {}
    if settings_store is not None:
        try:
            stored = (
                settings_store.get_settings("local").get("reminder") or {}
            )
        except Exception:  # noqa: BLE001 - a broken settings store disables
            stored = {}
    provider = (
        (stored.get("provider") or "").strip()
        or env.resualign_reminder_webhook_provider
        or "generic"
    )
    if provider not in WEBHOOK_PROVIDERS:
        provider = "generic"
    smtp_port = stored.get("smtp_port") or env.resualign_smtp_port or 587
    try:
        smtp_port = int(smtp_port)
    except (TypeError, ValueError):
        smtp_port = 587
    return {
        "enabled": bool(
            stored.get("enabled", False)
        ),
        "provider": provider,
        "webhook_url": (env.resualign_reminder_webhook_url or "").strip(),
        "webhook_secret": (env.resualign_reminder_webhook_secret or "").strip(),
        "smtp_host": (
            (stored.get("smtp_host") or "").strip()
            or (env.resualign_smtp_host or "").strip()
            or None
        ),
        "smtp_port": smtp_port,
        "smtp_user": (
            (stored.get("smtp_user") or "").strip()
            or (env.resualign_smtp_user or "").strip()
            or None
        ),
        "smtp_password": (env.resualign_smtp_password or "").strip() or None,
        "smtp_from": (
            (stored.get("smtp_from") or "").strip()
            or (env.resualign_smtp_from or "").strip()
            or None
        ),
        "smtp_to": (
            (stored.get("smtp_to") or "").strip()
            or (env.resualign_reminder_email_to or "").strip()
            or None
        ),
    }


def build_reminder_message(job: dict[str, Any]) -> str:
    """Build the user-facing reminder text (never includes secrets)."""
    lines = [
        f"【跟进提醒】{job.get('title') or '未命名岗位'}",
        f"公司：{job.get('company') or '-'}",
        f"状态：{job.get('status_canonical') or '-'}",
        f"下一步：{job.get('next_step') or '-'}",
        f"截止时间：{job.get('next_step_due_at') or '-'}",
        f"面试阶段：{job.get('interview_stage') or '-'}",
    ]
    return "\n".join(lines)


def _job_payload(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": job.get("job_id"),
        "title": job.get("title"),
        "company": job.get("company"),
        "status": job.get("status_canonical"),
        "next_step": job.get("next_step"),
        "next_step_due_at": job.get("next_step_due_at"),
        "interview_stage": job.get("interview_stage"),
    }


def _webhook_payload(
    provider: str,
    job: dict[str, Any],
) -> dict[str, Any]:
    text = build_reminder_message(job)
    if provider == "feishu":
        return {"msg_type": "text", "content": {"text": text}}
    if provider == "wecom":
        return {"msgtype": "text", "text": {"content": text}}
    if provider == "telegram":
        return {"text": text}
    return {"event": "reminder.due", "payload": _job_payload(job)}


def _send_webhook(
    provider: str,
    url: str,
    secret: str,
    job: dict[str, Any],
    *,
    timeout: float = _DELIVERY_TIMEOUT,
) -> None:
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["Authorization"] = f"Bearer {secret}"
    response = httpx.post(
        url,
        json=_webhook_payload(provider, job),
        headers=headers,
        timeout=timeout,
    )
    response.raise_for_status()


def _send_smtp(
    config: dict[str, Any],
    job: dict[str, Any],
    *,
    timeout: float = _DELIVERY_TIMEOUT,
) -> None:
    host = config["smtp_host"]
    to_addr = config["smtp_to"]
    from_addr = config["smtp_from"]
    if not host or not to_addr or not from_addr:
        raise ValueError("SMTP host, from, and to addresses are required")
    message = EmailMessage()
    message["Subject"] = f"【ResuAlign 跟进提醒】{job.get('title') or '未命名岗位'}"
    message["From"] = from_addr
    message["To"] = to_addr
    message.set_content(build_reminder_message(job))
    port = int(config["smtp_port"] or 587)
    if port == 465:
        smtp = smtplib.SMTP_SSL(
            host,
            port,
            timeout=timeout,
            context=ssl.create_default_context(),
        )
    else:
        smtp = smtplib.SMTP(host, port, timeout=timeout)
        smtp.starttls(context=ssl.create_default_context())
    try:
        if config.get("smtp_user") and config.get("smtp_password"):
            smtp.login(config["smtp_user"], config["smtp_password"])
        smtp.send_message(message)
    finally:
        try:
            smtp.quit()
        except Exception:  # noqa: BLE001 - closing must not mask send result
            pass


def _deliver_once(
    config: dict[str, Any],
    job: dict[str, Any],
    *,
    timeout: float = _DELIVERY_TIMEOUT,
) -> None:
    """Send via webhook or SMTP with retries; raise on final failure."""
    if config.get("webhook_url"):
        last_error: Exception | None = None
        for attempt in range(_WEBHOOK_RETRIES + 1):
            try:
                _send_webhook(
                    config["provider"],
                    config["webhook_url"],
                    config.get("webhook_secret") or "",
                    job,
                    timeout=timeout,
                )
                return
            except Exception as exc:  # noqa: BLE001 - retryable delivery
                last_error = exc
                if attempt < _WEBHOOK_RETRIES:
                    time.sleep(0.2 * (2**attempt))
        raise last_error  # type: ignore[misc]
    if config.get("smtp_host"):
        last_error = None
        for attempt in range(_WEBHOOK_RETRIES + 1):
            try:
                _send_smtp(config, job, timeout=timeout)
                return
            except Exception as exc:  # noqa: BLE001 - retryable delivery
                last_error = exc
                if attempt < _WEBHOOK_RETRIES:
                    time.sleep(0.2 * (2**attempt))
        raise last_error  # type: ignore[misc]
    raise ValueError("No reminder delivery channel is configured")


class ReminderDeliveryWorker:
    """Daemon thread that claims and delivers due reminders."""

    def __init__(
        self,
        store: Any,
        settings_store: Any | None = None,
        interval_seconds: int | None = None,
    ) -> None:
        self._store = store
        self._settings_store = settings_store
        self._interval = (
            interval_seconds
            if interval_seconds is not None
            else reminder_delivery_interval_seconds()
        )
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._loop,
            name="resualign-reminder-delivery",
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
        """Claim due reminders, deliver them, and persist outcome."""
        config = reminder_configuration(self._settings_store)
        if not config["enabled"]:
            log_event(
                logger,
                "reminder.delivery_disabled",
                extra={"reason": "not_enabled"},
            )
            return []
        if not config.get("webhook_url") and not config.get("smtp_host"):
            log_event(
                logger,
                "reminder.delivery_disabled",
                extra={"reason": "no_channel_configured"},
            )
            return []
        claimed = self._store.claim_pending_reminders(
            time.time(),
            lease_seconds=_LEASE_SECONDS,
            max_attempts=_MAX_CLAIM_ATTEMPTS,
        )
        now = time.time()
        for job in claimed:
            try:
                _deliver_once(config, job)
            except Exception as exc:  # noqa: BLE001 - one failure never stops
                attempts = int(job.get("reminder_attempts") or 1)
                retry_at = now + min(3600.0, 60.0 * (2 ** max(0, attempts - 1)))
                self._store.mark_reminder_failed(
                    job["tenant_id"],
                    job["job_id"],
                    retry_at,
                )
                log_event(
                    logger,
                    "reminder.delivery_failed",
                    extra={
                        "job_id": job["job_id"],
                        "tenant_id": job["tenant_id"],
                        "attempts": attempts,
                        "next_retry_at": retry_at,
                        "error": str(exc)[:300],
                    },
                )
                continue
            self._store.mark_reminder_sent(
                job["tenant_id"],
                job["job_id"],
                time.time(),
            )
            log_event(
                logger,
                "reminder.delivered",
                extra={
                    "job_id": job["job_id"],
                    "tenant_id": job["tenant_id"],
                    "provider": config["provider"],
                },
            )
        return claimed

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self.tick()
            except Exception:
                logger.exception("Reminder delivery tick failed")
