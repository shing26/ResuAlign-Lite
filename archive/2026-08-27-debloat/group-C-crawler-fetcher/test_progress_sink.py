"""Tests for the shared crawl progress sink."""

from __future__ import annotations

from resualign.api.services.progress_sink import (
    CRAWL_ORDER,
    CrawlProgressSink,
)


class _FakeCrawlStore:
    def __init__(self) -> None:
        self.state = {"status": "queued", "stage": "queued"}
        self.calls: list[tuple] = []

    def get(self, crawl_id, tenant_id=None):
        self.calls.append(("get", crawl_id, tenant_id))
        return dict(self.state)

    def update_state(self, crawl_id, status, **kwargs):
        self.calls.append(("update", crawl_id, status, kwargs))
        self.state.update({"status": status})
        if "stage" in kwargs:
            self.state["stage"] = kwargs["stage"]
        if "error" in kwargs:
            self.state["error"] = kwargs["error"]


def test_crawl_order_has_terminal_chain():
    assert CRAWL_ORDER["queued"] == "fetching"
    assert CRAWL_ORDER["classifying"] == "succeeded"


def test_on_stage_writes_stage_and_status():
    store = _FakeCrawlStore()
    sink = CrawlProgressSink(store, "crawl-1", tenant_id="local")
    sink.on_stage("fetching", "fetching_jd")
    assert store.state["status"] == "fetching"
    assert store.state["stage"] == "fetching_jd"


def test_complete_fast_forwards_through_ordered_stages():
    store = _FakeCrawlStore()
    sink = CrawlProgressSink(store, "crawl-1", tenant_id="local")
    sink.complete()
    statuses = [
        call[2] for call in store.calls if call[0] == "update"
    ]
    assert statuses == ["fetching", "parsing", "classifying", "succeeded"]


def test_complete_stops_at_unknown_status():
    store = _FakeCrawlStore()
    store.state["status"] = "weird"
    sink = CrawlProgressSink(store, "crawl-1", tenant_id="local")
    sink.complete()
    assert store.state["status"] == "weird"


def test_fail_records_error():
    store = _FakeCrawlStore()
    sink = CrawlProgressSink(store, "crawl-1", tenant_id="local")
    sink.fail("HTTP 403")
    assert store.state["status"] == "failed"
    assert store.state["error"] == "HTTP 403"


def test_store_error_does_not_raise():
    class BrokenStore:
        def update_state(self, *args, **kwargs):
            raise RuntimeError("db locked")

        def get(self, *args, **kwargs):
            return {"status": "queued"}

    sink = CrawlProgressSink(BrokenStore(), "crawl-1", tenant_id="local")
    sink.on_stage("fetching", "fetching_jd")
    sink.complete()
    sink.fail("boom")
