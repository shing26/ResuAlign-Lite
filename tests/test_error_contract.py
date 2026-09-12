"""Error-shape contract tests (ticket #100 / plan §1).

These tests are the runtime shape-lock chosen over OpenAPI declarations:
- unhandled exceptions become JSON 500 ``{code, message, request_id}`` with
  ``X-Request-Id`` header == body ``request_id``;
- every existing error response keeps its ``detail`` byte-for-byte and gains
  only an additive top-level ``request_id``;
- auth failures never pass ``UserStoreError`` text through;
- ``http.unhandled`` structured logs carry method/path/error/traceback.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api.errors import register_error_handlers
from resualign.workspace import UserStoreError

client = TestClient(api_module.app)


def _mini_client() -> TestClient:
    """A bare app with only the error plumbing installed.

    Routes are added here (never on the real app) so the frozen OpenAPI
    snapshot of ``resualign.api.app`` stays untouched.
    """
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/boom")
    def boom():
        raise ValueError("SENTINEL internal boom")

    @app.get("/raise-http")
    def raise_http():
        raise HTTPException(status_code=404, detail="missing thing")

    @app.get("/raise-http-dict")
    def raise_http_dict():
        raise HTTPException(
            status_code=401,
            detail={"code": "x", "reason": "y", "action": "z"},
        )

    return TestClient(app, raise_server_exceptions=False)


class TestMiniAppErrorShapes:
    def test_unhandled_exception_becomes_json_500(self):
        r = _mini_client().get("/boom")
        assert r.status_code == 500
        assert r.headers["content-type"].startswith("application/json")
        body = r.json()
        assert body["code"] == "internal_error"
        assert isinstance(body["message"], str) and body["message"]
        assert body["request_id"] == r.headers["X-Request-Id"]
        # The exception text must stay server-side only.
        assert "SENTINEL" not in r.text

    def test_http_exception_keeps_detail_and_adds_request_id(self):
        r = _mini_client().get("/raise-http")
        assert r.status_code == 404
        body = r.json()
        assert body["detail"] == "missing thing"
        assert body["request_id"] == r.headers["X-Request-Id"]

    def test_http_exception_dict_detail_survives(self):
        r = _mini_client().get("/raise-http-dict")
        assert r.status_code == 401
        body = r.json()
        assert body["detail"] == {"code": "x", "reason": "y", "action": "z"}
        assert body["request_id"] == r.headers["X-Request-Id"]

    def test_unhandled_exception_logs_structured_event(self, caplog):
        with caplog.at_level(logging.ERROR, logger="resualign.api"):
            _mini_client().get("/boom")
        records = [
            rec.getMessage()
            for rec in caplog.records
            if '"http.unhandled"' in rec.getMessage()
        ]
        assert records, "expected one http.unhandled record"
        msg = records[0]
        assert '"method": "GET"' in msg
        assert '"path": "/boom"' in msg
        assert "SENTINEL internal boom" in msg  # kept server-side
        assert "ValueError" in msg
        assert '"request_id"' in msg


class TestRealAppAdditiveShapes:
    def test_validation_error_422_shape_preserved_plus_request_id(self):
        r = client.post("/api/analyze", json={})
        assert r.status_code == 422
        body = r.json()
        assert "request_id" in body
        assert body["request_id"] == r.headers["X-Request-Id"]
        detail = body["detail"]
        assert isinstance(detail, list) and detail
        for item in detail:
            assert set(item.keys()) >= {"loc", "msg", "type"}

    def test_business_error_detail_shape_unchanged(self):
        # 404 from the jobs router: detail string untouched, request_id added.
        r = client.get("/api/jobs/does-not-exist")
        assert r.status_code == 404
        body = r.json()
        assert isinstance(body["detail"], str) and body["detail"]
        assert body["request_id"] == r.headers["X-Request-Id"]

    def test_body_limit_413_carries_request_id(self):
        big = b"x" * (api_module._MAX_BODY_BYTES + 1)
        r = client.post(
            "/api/analyze",
            content=big,
            headers={"Content-Type": "text/plain"},
        )
        assert r.status_code == 413
        body = r.json()
        assert isinstance(body["detail"], str)
        assert body["request_id"] == r.headers["X-Request-Id"]


class TestAuthLeakClosed:
    def test_login_never_passes_through_store_text(self, monkeypatch):
        def boom(email, password):
            raise UserStoreError("SENTINEL sqlite3 diag: no such table users")

        monkeypatch.setattr(api_module._users, "login", boom)
        r = client.post(
            "/api/auth/login", json={"email": "a@b.co", "password": "whatever1"}
        )
        assert r.status_code == 401
        body = r.json()
        assert body["detail"] == "Invalid email or password"
        assert "SENTINEL" not in r.text
        assert body["request_id"] == r.headers["X-Request-Id"]

    def test_signup_keeps_known_user_safe_messages(self, monkeypatch):
        for known in (
            "Email already registered",
            "Password must be at least 8 characters",
        ):

            def boom(email, password, _known=known):
                raise UserStoreError(_known)

            monkeypatch.setattr(api_module._users, "create_user", boom)
            r = client.post(
                "/api/auth/signup", json={"email": "a@b.co", "password": "whatever1"}
            )
            assert r.status_code == 409
            assert r.json()["detail"] == known

    def test_signup_generic_for_unknown_store_error(self, monkeypatch):
        def boom(email, password):
            raise UserStoreError("SENTINEL unique constraint on users")

        monkeypatch.setattr(api_module._users, "create_user", boom)
        r = client.post(
            "/api/auth/signup", json={"email": "a@b.co", "password": "whatever1"}
        )
        assert r.status_code == 409
        body = r.json()
        assert body["detail"] == "注册失败，请检查输入后重试"
        assert "SENTINEL" not in r.text
        assert body["request_id"] == r.headers["X-Request-Id"]
