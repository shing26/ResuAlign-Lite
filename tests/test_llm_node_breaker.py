"""LLM node auto-breaker tests (ticket #103 / plan §4).

Semantics under test (grilling table):
- counted call codes: timeout/http/auth/quota/other; NOT counted:
  rate_limit/parse/schema/empty (transient or output-quality);
- counted probe statuses: timeout/network_error/missing_key/http_401/402/403
  /http_5xx; NOT counted: http_429 and other 4xx;
- threshold 3 -> persistent auto_disable; selection paths filter it while
  ADMIN paths (get_active_node / list / activate / delete-promotion) stay
  unfiltered; success (call or manual test) or explicit activation recovers.
"""

from __future__ import annotations

import logging
import sqlite3

import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.engine.llm import LLMResponseError, StreamConnectionError
from resualign.engine.llm_nodes import LLMNodeStore
from resualign.engine.role_router import call_with_role, call_with_role_streaming
from resualign.workspace import UserStore

from .conftest import fake_api_key, fake_password

client = TestClient(app)


def _store(tmp_path) -> LLMNodeStore:
    return LLMNodeStore(db_path=tmp_path / "nodes.db")


def _node(store, tenant="t", **kw):
    kw.setdefault("is_active", True)
    return store.create_node(
        tenant,
        name=kw.pop("name", "坏节点"),
        provider="deepseek",
        model="deepseek-chat",
        api_key=fake_api_key("brk"),
        base_url="https://api.deepseek.com",
        **kw,
    )


def _trip(store, tenant, node_id, *, via="call", times=3):
    for _ in range(times):
        if via == "call":
            store.record_call_failure(tenant, node_id, "timeout")
        else:
            store.record_node_health(tenant, node_id, "network_error", None)


class TestCodeClassification:
    @pytest.mark.parametrize("code", ["timeout", "http", "auth", "quota", "other"])
    def test_counted_call_codes(self, tmp_path, code):
        store = _store(tmp_path)
        n = _node(store)
        store.record_call_failure("t", n["node_id"], code)
        assert store.get_node("t", n["node_id"])["consecutive_failures"] == 1

    @pytest.mark.parametrize(
        "code", ["rate_limit", "parse", "schema", "empty", "unknown_code"]
    )
    def test_uncounted_call_codes(self, tmp_path, code):
        store = _store(tmp_path)
        n = _node(store)
        _trip(store, "t", n["node_id"])
        before = store.get_node("t", n["node_id"])["consecutive_failures"]
        store.record_call_failure("t", n["node_id"], code)
        assert (
            store.get_node("t", n["node_id"])["consecutive_failures"] == before
        ), f"{code} must not feed the breaker"

    @pytest.mark.parametrize(
        "status",
        ["timeout", "network_error", "missing_key", "http_401", "http_402",
         "http_403", "http_500", "http_503"],
    )
    def test_counted_probe_statuses(self, tmp_path, status):
        store = _store(tmp_path)
        n = _node(store)
        store.record_node_health("t", n["node_id"], status, None)
        assert store.get_node("t", n["node_id"])["consecutive_failures"] == 1

    @pytest.mark.parametrize("status", ["http_429", "http_404", "http_422"])
    def test_uncounted_probe_statuses(self, tmp_path, status):
        store = _store(tmp_path)
        n = _node(store)
        store.record_node_health("t", n["node_id"], status, None)
        assert store.get_node("t", n["node_id"])["consecutive_failures"] == 0

    def test_success_call_counts_nothing_but_clears(self, tmp_path):
        store = _store(tmp_path)
        n = _node(store)
        _trip(store, "t", n["node_id"], times=2)
        store.record_call_success("t", n["node_id"])
        row = store.get_node("t", n["node_id"])
        assert row["consecutive_failures"] == 0 and not row["auto_disabled"]


class TestTripFilterAndRecovery:
    def test_threshold_trips_and_filters_call_chain(self, tmp_path):
        store = _store(tmp_path)
        n = _node(store)
        assert store.get_usable_node("t") is not None
        _trip(store, "t", n["node_id"])
        row = store.get_node("t", n["node_id"])
        assert row["auto_disabled"] is True
        assert row["consecutive_failures"] == 3
        # Call-chain selection filters...
        assert store.get_usable_node("t") is None
        assert store.resolve_node_for_role("t", "editor") is None
        # ...admin selection does NOT (the badge & truth must stay visible).
        assert store.get_active_node("t") is not None
        assert store.get_active_node("t")["node_id"] == n["node_id"]

    def test_extra_failures_do_not_restack(self, tmp_path):
        store = _store(tmp_path)
        n = _node(store)
        _trip(store, "t", n["node_id"], times=5)
        row = store.get_node("t", n["node_id"])
        assert row["auto_disabled"] is True
        assert row["consecutive_failures"] == 5

    def test_probe_ok_recovers(self, tmp_path):
        store = _store(tmp_path)
        n = _node(store)
        _trip(store, "t", n["node_id"])
        store.record_node_health("t", n["node_id"], "ok", 12.0)
        row = store.get_node("t", n["node_id"])
        assert not row["auto_disabled"] and row["consecutive_failures"] == 0
        assert store.get_usable_node("t") is not None

    def test_activation_recovers(self, tmp_path):
        store = _store(tmp_path)
        n = _node(store)
        _trip(store, "t", n["node_id"])
        store.activate_node("t", n["node_id"])
        assert store.get_usable_node("t") is not None

    def test_state_persists_across_process_restart(self, tmp_path):
        store = _store(tmp_path)
        n = _node(store)
        _trip(store, "t", n["node_id"])
        reopened = LLMNodeStore(db_path=tmp_path / "nodes.db")
        assert reopened.get_usable_node("t") is None
        assert reopened.get_active_node("t") is not None

    def test_transitions_logged_once(self, tmp_path, caplog):
        store = _store(tmp_path)
        n = _node(store)
        with caplog.at_level(logging.INFO, logger="resualign.engine.llm_nodes"):
            _trip(store, "t", n["node_id"])
            _trip(store, "t", n["node_id"], times=2)  # already disabled
            store.record_call_success("t", n["node_id"])
        msgs = [r.getMessage() for r in caplog.records]
        disabled = [m for m in msgs if '"llm_node.auto_disabled"' in m]
        recovered = [m for m in msgs if '"llm_node.recovered"' in m]
        assert len(disabled) == 1, "auto_disabled must log exactly per transition"
        assert len(recovered) == 1
        assert '"threshold": 3' in disabled[0]


class TestRoleBindingBoundary:
    def test_disabled_bound_role_falls_back_binding_survives(self, tmp_path):
        store = _store(tmp_path)
        a = _node(store, name="主节点")
        b = _node(store, name="编辑节点", is_active=False)
        assert store.set_role_binding("t", "editor", b["node_id"])
        _trip(store, "t", b["node_id"])
        # Bound editor node is skipped; resolution falls back to usable active.
        assert store.resolve_node_for_role("t", "editor")["node_id"] == a["node_id"]
        # The binding itself is admin state — kept, not silently deleted.
        assert store.get_role_binding("t", "editor") == b["node_id"]
        store.record_call_success("t", b["node_id"])
        assert store.resolve_node_for_role("t", "editor")["node_id"] == b["node_id"]


class TestRoleRouterWiring:
    def _boom(self, code):
        def fn(client, **kw):
            raise LLMResponseError("node down", code=code)

        return fn

    def test_counted_primary_and_fallback_failures_tally(self, tmp_path):
        store = _store(tmp_path)
        n = _node(store)
        with pytest.raises(LLMResponseError):
            call_with_role("editor", self._boom("timeout"), store, "t")
        # primary fail + fallback fail (same sole node) both counted
        assert store.get_node("t", n["node_id"])["consecutive_failures"] == 2

    def test_uncounted_code_tallies_zero(self, tmp_path):
        store = _store(tmp_path)
        n = _node(store)
        with pytest.raises(LLMResponseError):
            call_with_role("editor", self._boom("parse"), store, "t")
        assert store.get_node("t", n["node_id"])["consecutive_failures"] == 0

    def test_success_clears_counter(self, tmp_path):
        store = _store(tmp_path)
        n = _node(store)
        _trip(store, "t", n["node_id"], times=2)

        def ok(client, **kw):
            return "result"

        result, meta = call_with_role("editor", ok, store, "t")
        assert result == "result"
        assert store.get_node("t", n["node_id"])["consecutive_failures"] == 0

    def test_tripped_node_is_not_reaimed_at(self, tmp_path):
        store = _store(tmp_path)
        n = _node(store)
        _trip(store, "t", n["node_id"])

        def never(client, **kw):
            raise AssertionError("must not call a tripped node")

        with pytest.raises(LLMResponseError) as ei:
            call_with_role("editor", never, store, "t")
        assert "No default node" in str(ei.value)

    def test_stream_stall_counts_as_other(self, tmp_path):
        store = _store(tmp_path)
        n = _node(store)

        def stall(client, **kw):
            raise StreamConnectionError("idle")

        with pytest.raises(Exception):
            call_with_role_streaming("editor", stall, store, "t")
        assert store.get_node("t", n["node_id"])["consecutive_failures"] == 2

    def test_fake_store_without_breaker_still_works(self):
        """role_router must stay duck-typed for legacy node-store doubles."""

        class LegacyFake:
            def resolve_node_for_role(self, tenant_id, role):
                return {
                    "node_id": "f",
                    "provider": "deepseek",
                    "model": "m",
                    "api_key": fake_api_key("legacy"),
                    "base_url": "https://x",
                }

            def get_active_node(self, tenant_id):
                return self.resolve_node_for_role(tenant_id, "editor")

        def ok(client, **kw):
            return "done"

        result, meta = call_with_role("editor", ok, LegacyFake(), "t")
        assert result == "done"


class TestMigrationFive:
    """A pre-#103 llm_nodes table upgrades with the two breaker columns."""

    _OLD = """
    CREATE TABLE llm_nodes (
        node_id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        name TEXT NOT NULL,
        provider TEXT NOT NULL,
        base_url TEXT,
        api_key TEXT,
        model TEXT,
        is_active INTEGER NOT NULL DEFAULT 0,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        last_test_status TEXT,
        last_test_latency_ms REAL,
        last_test_at REAL,
        disable_thinking INTEGER NOT NULL DEFAULT 0
    );
    """

    def test_legacy_database_gains_breaker_columns(self, tmp_path):
        db = tmp_path / "legacy.db"
        conn = sqlite3.connect(db)
        conn.executescript(
            self._OLD
            + "INSERT INTO llm_nodes (node_id, tenant_id, name, provider, "
            "model, is_active, created_at, updated_at) VALUES "
            "('n1','t','旧节点','deepseek','m',1,1.0,1.0);"
        )
        conn.commit()
        conn.close()
        store = LLMNodeStore(db_path=db)
        row = store.get_active_node("t")
        assert row["auto_disabled"] is False
        assert row["consecutive_failures"] == 0
        _trip(store, "t", "n1")
        assert store.get_usable_node("t") is None


@pytest.fixture()
def api_node_store(tmp_path):
    saved = {
        name: getattr(api_module, name)
        for name in ("_llm_nodes", "_users", "_PERSONAL_MODE")
    }
    db = tmp_path / "api.db"
    api_module._llm_nodes = LLMNodeStore(db_path=db)
    api_module._users = UserStore(db_path=db)
    api_module._PERSONAL_MODE = False
    try:
        yield api_module._llm_nodes
    finally:
        for name, value in saved.items():
            setattr(api_module, name, value)


class TestNodeListApi:
    def test_breaker_fields_flow_to_settings_ui(self, api_node_store):
        assert client.post(
            "/api/auth/signup",
            json={"email": "brk@example.com", "password": fake_password("123")},
        ).status_code == 201
        tok = client.post(
            "/api/auth/login",
            json={"email": "brk@example.com", "password": fake_password("123")},
        ).json()["token"]
        headers = {"Authorization": f"Bearer {tok}"}
        created = client.post(
            "/api/llm/nodes",
            json={
                "name": "云端",
                "provider": "deepseek",
                "model": "deepseek-chat",
                "api_key": fake_api_key("api"),
                "base_url": "https://api.deepseek.com",
            },
            headers=headers,
        ).json()
        listed = client.get("/api/llm/nodes", headers=headers).json()[0]
        assert listed["auto_disabled"] is False
        assert listed["consecutive_failures"] == 0
        _trip(
            api_node_store,
            created["tenant_id"],
            created["node_id"],
            via="probe",
        )
        after = client.get("/api/llm/nodes", headers=headers).json()[0]
        assert after["auto_disabled"] is True
        assert after["consecutive_failures"] == 3
