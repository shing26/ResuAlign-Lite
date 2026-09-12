import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

import resualign.api as api_module

from ...observability import log_event
from ..deps import _bearer_token, get_current_user
from ..schemas import LoginRequest, SignupRequest

router = APIRouter()

# Ticket #100: auth failures must never pass UserStoreError text through to
# the client (that was str(exc) leak point #20/#30). Known, user-safe store
# messages are mirrored as fixed 话术; anything unexpected is replaced by the
# generic line and logged server-side so diagnosis is not lost.
_LOGIN_DETAIL = "Invalid email or password"
_SIGNUP_DETAILS = {
    "Email already registered": "Email already registered",
    "Password must be at least 8 characters": "Password must be at least 8 characters",
}
_SIGNUP_FALLBACK_DETAIL = "注册失败，请检查输入后重试"

_auth_logger = logging.getLogger("resualign.api.auth")


def _safe_signup_detail(exc: Exception) -> str:
    text = str(exc)
    if text not in _SIGNUP_DETAILS:
        log_event(
            _auth_logger,
            "auth.unexpected_store_error",
            level="warning",
            extra={"stage": "signup", "error": text},
        )
        return _SIGNUP_FALLBACK_DETAIL
    return _SIGNUP_DETAILS[text]


@router.post("/api/auth/signup", status_code=201)
def signup(req: SignupRequest, request: Request):
    """Create a user account."""
    api_module._enforce_rate_limit(request, api_module._auth_rate_limiter)
    try:
        user = api_module._users.create_user(req.email, req.password)
    except api_module.UserStoreError as exc:
        raise HTTPException(status_code=409, detail=_safe_signup_detail(exc)) from exc
    return user


@router.post("/api/auth/login")
def login(req: LoginRequest, request: Request):
    """Verify credentials and return an opaque bearer token."""
    api_module._enforce_rate_limit(request, api_module._auth_rate_limiter)
    try:
        token = api_module._users.login(req.email, req.password)
    except api_module.UserStoreError as exc:
        if str(exc) != _LOGIN_DETAIL:
            log_event(
                _auth_logger,
                "auth.unexpected_store_error",
                level="warning",
                extra={"stage": "login", "error": str(exc)},
            )
        raise HTTPException(status_code=401, detail=_LOGIN_DETAIL) from exc
    user = api_module._users.user_for_token(token)
    return {"token": token, "user": user}


@router.post("/api/auth/logout")
def logout(token: Optional[str] = Depends(_bearer_token)):
    """Revoke the current bearer token."""
    if token is not None:
        api_module._users.revoke_token(token)
    return {"status": "ok"}


@router.get("/api/auth/me")
def me(user: dict[str, Any] = Depends(get_current_user)):
    """Return the currently authenticated user."""
    return user
