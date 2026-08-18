"""Tests for the MVP-05 reminder delivery worker and settings contract."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from resualign.job_library import JobLibraryStore
from resualign.reminders import (
    ReminderDeliveryWorker,
    _send_webhook,
    _webhook_payload,
    build_reminder_message,
    reminder_configuration,
)
from resualign.settings_store import SettingsStore

_NOW = datetime(2026, 8, 17, 12, 0, tzinfo=timezone(timedelta(hours=8)))
_NOW_TS = _NOW.timestamp()


def _due() -> str:
    return _NOW.isoformat()


def _make_active_job(store: JobLibraryStore, title: str = "Backend") -> dict:
    job = store.create_job(
        tenant_id="tenant-a",
        title=title,
        jd_text="Python backend engineer.",
    )
    return store.update_job(
        "tenant-a",
        job["job_id"],
        status="已投递",
        next_step_due_at=_due(),
    )


def _enabled_settings(tmp_path) -> SettingsStore:
    store = SettingsStore(db_path=tmp_path / "settings.db")
    store.update_settings(
        "local",
        {
            "reminder": {
                "enabled": True,
                "provider": "generic",
            }
        },
    )
    return store


class _OkResponse:
    def raise_for_status(self) -> None:
        return None


class _FakeSMTP:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.message = None
        self.login_args = None

    def starttls(self, context=None):
        return None

    def login(self, user, password):
        self.login_args = (user, password)

    def send_message(self, message):
        self.message = message

    def quit(self):
        return None


def test_worker_delivers_generic_webhook_and_marks_sent_once(
    tmp_path, monkeypatch
):
    store = JobLibraryStore(db_path=tmp_path / "jobs.db")
    _make_active_job(store)
    settings = _enabled_settings(tmp_path)
    monkeypatch.setenv("RESUALIGN_REMINDER_WEBHOOK_URL", "https://hook.test/remind")
    monkeypatch.setenv(
        "RESUALIGN_REMINDER_WEBHOOK_SECRET", "supersecret-token"
    )
    calls: list[dict] = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append({"url": url, "json": json, "headers": headers})
        return _OkResponse()

    monkeypatch.setattr("resualign.reminders.httpx.post", fake_post)
    worker = ReminderDeliveryWorker(store, settings, interval_seconds=60)
    claimed = worker.tick()
    assert len(claimed) == 1
    assert len(calls) == 1
    body = calls[0]["json"]
    assert body["event"] == "reminder.due"
    assert body["payload"]["title"] == "Backend"
    assert body["payload"]["next_step_due_at"] == _due()
    assert "supersecret-token" not in build_reminder_message(
        claimed[0]
    )
    fetched = store.get_job("tenant-a", claimed[0]["job_id"])
    assert fetched["reminder_sent_at"] is not None
    assert worker.tick() == []
    assert len(calls) == 1


def test_provider_payload_shapes():
    job = {
        "title": "Backend",
        "company": "Acme",
        "status_canonical": "applied",
        "next_step": "准备面试",
        "next_step_due_at": _due(),
        "interview_stage": "一面",
    }
    assert _webhook_payload("feishu", job)["msg_type"] == "text"
    assert _webhook_payload("wecom", job)["msgtype"] == "text"
    assert "text" in _webhook_payload("telegram", job)
    generic = _webhook_payload("generic", job)
    assert generic["event"] == "reminder.due"
    assert generic["payload"]["interview_stage"] == "一面"


def test_worker_sends_smtp(tmp_path, monkeypatch):
    store = JobLibraryStore(db_path=tmp_path / "jobs.db")
    _make_active_job(store)
    settings = _enabled_settings(tmp_path)
    settings.update_settings(
        "local",
        {
            "reminder": {
                "smtp_host": "smtp.example.com",
                "smtp_port": 587,
                "smtp_user": "user",
                "smtp_from": "from@example.com",
                "smtp_to": "to@example.com",
            }
        },
    )
    monkeypatch.setenv("RESUALIGN_SMTP_PASSWORD", "smtp-password")
    fake = _FakeSMTP()
    monkeypatch.setattr("resualign.reminders.smtplib.SMTP", lambda *a, **k: fake)
    worker = ReminderDeliveryWorker(store, settings, interval_seconds=60)
    claimed = worker.tick()
    assert len(claimed) == 1
    assert fake.message is not None
    assert fake.message["To"] == "to@example.com"
    assert "Backend" in fake.message["Subject"]
    assert fake.login_args == ("user", "smtp-password")
    assert store.get_job("tenant-a", claimed[0]["job_id"])["reminder_sent_at"]


def test_worker_retries_then_succeeds(tmp_path, monkeypatch):
    store = JobLibraryStore(db_path=tmp_path / "jobs.db")
    job = _make_active_job(store)
    settings = _enabled_settings(tmp_path)
    monkeypatch.setenv("RESUALIGN_REMINDER_WEBHOOK_URL", "https://hook.test/remind")
    calls = {"count": 0}

    def flaky_post(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] < 3:
            raise RuntimeError("temporary network failure")
        return _OkResponse()

    monkeypatch.setattr("resualign.reminders.httpx.post", flaky_post)
    monkeypatch.setattr("resualign.reminders.time.sleep", lambda _: None)
    worker = ReminderDeliveryWorker(store, settings, interval_seconds=60)
    worker.tick()
    assert calls["count"] == 3
    fetched = store.get_job("tenant-a", job["job_id"])
    assert fetched["reminder_sent_at"] is not None
    assert fetched["reminder_attempts"] == 1


def test_worker_final_failure_schedules_retry(tmp_path, monkeypatch):
    store = JobLibraryStore(db_path=tmp_path / "jobs.db")
    job = _make_active_job(store)
    settings = _enabled_settings(tmp_path)
    monkeypatch.setenv("RESUALIGN_REMINDER_WEBHOOK_URL", "https://hook.test/remind")

    def failing_post(*args, **kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr("resualign.reminders.httpx.post", failing_post)
    monkeypatch.setattr("resualign.reminders.time.sleep", lambda _: None)
    worker = ReminderDeliveryWorker(store, settings, interval_seconds=60)
    worker.tick()
    fetched = store.get_job("tenant-a", job["job_id"])
    assert fetched["reminder_sent_at"] is None
    assert fetched["reminder_attempts"] == 1
    assert fetched["reminder_next_retry_at"] > _NOW_TS

    retry_at = fetched["reminder_next_retry_at"] + 1
    again = store.claim_pending_reminders(retry_at)
    assert len(again) == 1
    assert again[0]["reminder_attempts"] == 2


def test_worker_without_channel_is_noop(tmp_path, monkeypatch):
    store = JobLibraryStore(db_path=tmp_path / "jobs.db")
    _make_active_job(store)
    settings = SettingsStore(db_path=tmp_path / "settings.db")
    calls = {"count": 0}
    monkeypatch.setattr(
        "resualign.reminders.httpx.post",
        lambda *a, **k: calls.__setitem__("count", calls["count"] + 1),
    )
    worker = ReminderDeliveryWorker(store, settings, interval_seconds=60)
    assert worker.tick() == []
    assert calls["count"] == 0


def test_config_never_exposes_secrets(tmp_path, monkeypatch):
    settings = _enabled_settings(tmp_path)
    monkeypatch.setenv(
        "RESUALIGN_REMINDER_WEBHOOK_URL",
        "https://hook.test/remind?token=secret-token",
    )
    monkeypatch.setenv("RESUALIGN_REMINDER_WEBHOOK_SECRET", "webhook-secret")
    monkeypatch.setenv("RESUALIGN_SMTP_PASSWORD", "smtp-secret")
    config = reminder_configuration(settings)
    assert config["webhook_secret"] == "webhook-secret"
    assert config["smtp_password"] == "smtp-secret"
    job = {
        "title": "Backend",
        "company": None,
        "status_canonical": "applied",
        "next_step": None,
        "next_step_due_at": None,
        "interview_stage": None,
    }
    assert "secret-token" not in str(_webhook_payload("generic", job))
    assert "webhook-secret" not in build_reminder_message(job)
    assert "smtp-secret" not in build_reminder_message(job)


def test_send_webhook_timeout_and_secret_header(tmp_path, monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return _OkResponse()

    monkeypatch.setattr("resualign.reminders.httpx.post", fake_post)
    _send_webhook(
        "feishu",
        "https://hook.test/feishu",
        "secret-token",
        {
            "title": "Backend",
            "company": None,
            "status_canonical": "applied",
            "next_step": None,
            "next_step_due_at": None,
            "interview_stage": None,
        },
        timeout=3.0,
    )
    assert captured["url"] == "https://hook.test/feishu"
    assert captured["headers"]["Authorization"] == "Bearer secret-token"
    assert captured["json"]["msg_type"] == "text"
