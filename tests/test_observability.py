import json
import logging

from resualign.observability import (
    CacheHitCounter,
    current_request_id,
    log_event,
    log_slow_call,
    new_request_id,
    request_context,
)


class _CaptureHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


def _capture_logger():
    logger = logging.getLogger("test-observability")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    handler = _CaptureHandler()
    logger.addHandler(handler)
    return logger, handler


def test_request_ids_are_short_and_unique():
    first = new_request_id()
    second = new_request_id()

    assert first != second
    assert len(first) == 12
    assert first.isalnum()


def test_request_context_sets_current_id():
    request_id = new_request_id()
    assert current_request_id() is None

    with request_context(request_id):
        assert current_request_id() == request_id

    assert current_request_id() is None


def test_log_event_writes_structured_json_line():
    logger, handler = _capture_logger()
    request_id = new_request_id()

    log_event(
        logger,
        "crawl.done",
        request_id=request_id,
        duration_ms=12.5,
        extra={"url": "https://example.com/job"},
    )

    payload = json.loads(handler.records[0].getMessage())
    assert payload["level"] == "info"
    assert payload["event"] == "crawl.done"
    assert payload["request_id"] == request_id
    assert payload["duration_ms"] == 12.5
    assert payload["extra"] == {"url": "https://example.com/job"}


def test_log_slow_call_only_warns_above_threshold():
    logger, handler = _capture_logger()
    request_id = new_request_id()

    assert (
        log_slow_call(
            logger,
            "crawl.slow",
            duration_ms=20,
            threshold_ms=100,
            request_id=request_id,
        )
        is False
    )
    assert handler.records == []

    assert (
        log_slow_call(
            logger,
            "crawl.slow",
            duration_ms=120,
            threshold_ms=100,
            request_id=request_id,
        )
        is True
    )
    payload = json.loads(handler.records[0].getMessage())
    assert payload["level"] == "warning"
    assert payload["duration_ms"] == 120
    assert payload["extra"]["threshold_ms"] == 100


def test_cache_hit_counter_tracks_rates_and_snapshot():
    counter = CacheHitCounter()
    assert counter.hit_rate() is None

    counter.hit(3)
    counter.miss(2)

    snapshot = counter.snapshot()
    assert snapshot["hits"] == 3
    assert snapshot["misses"] == 2
    assert snapshot["total"] == 5
    assert snapshot["hit_rate"] == 0.6
    assert counter.hit_rate() == 0.6

    counter.reset()
    assert counter.snapshot()["total"] == 0
