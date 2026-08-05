
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from ..deps import get_current_user, _bearer_token
from ..schemas import LoginRequest, SignupRequest

import resualign.api as api_module

router = APIRouter()

@router.post('/api/auth/signup', status_code=201)
def signup(req: SignupRequest, request: Request):
    """Create a user account."""
    api_module._enforce_rate_limit(request, api_module._auth_rate_limiter)
    try:
        user = api_module._users.create_user(req.email, req.password)
    except api_module.UserStoreError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return user

@router.post('/api/auth/login')
def login(req: LoginRequest, request: Request):
    """Verify credentials and return an opaque bearer token."""
    api_module._enforce_rate_limit(request, api_module._auth_rate_limiter)
    try:
        token = api_module._users.login(req.email, req.password)
    except api_module.UserStoreError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    user = api_module._users.user_for_token(token)
    return {'token': token, 'user': user}

@router.post('/api/auth/logout')
def logout(token: Optional[str]=Depends(_bearer_token)):
    """Revoke the current bearer token."""
    if token is not None:
        api_module._users.revoke_token(token)
    return {'status': 'ok'}

@router.get('/api/auth/me')
def me(user: dict[str, Any]=Depends(get_current_user)):
    """Return the currently authenticated user."""
    return user

