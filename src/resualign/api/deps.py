
from typing import Any, Optional

from fastapi import Depends, Header, HTTPException, Request

from ..app.context import context
from .rate_limit import _RateLimiter


def _bearer_token(authorization: str=Header(default='')) -> Optional[str]:
    if not authorization.lower().startswith('bearer '):
        return None
    token = authorization[7:].strip()
    return token or None

def _enforce_rate_limit(request: Request, limiter: _RateLimiter) -> None:
    """Reject requests that exceed the limiter's per-client budget."""
    key = request.client.host if request.client else 'unknown'
    if not limiter.allow(key):
        raise HTTPException(status_code=429, detail='Too many requests, please try again later')

def get_current_user(token: Optional[str]=Depends(_bearer_token)) -> dict[str, Any]:
    """Resolve the bearer token to a user, raising 401 when invalid."""
    if token is not None:
        user = context._users.user_for_token(token)
        if user is not None:
            return user
    elif context._PERSONAL_MODE:
        return context._users.get_or_create_personal_user()
    else:
        raise HTTPException(status_code=401, detail='Not authenticated', headers={'WWW-Authenticate': 'Bearer'})
    raise HTTPException(status_code=401, detail='Invalid or expired token', headers={'WWW-Authenticate': 'Bearer'})


def get_local_ingest_user(
    x_resualign_token: str = Header(default=''),
) -> dict[str, Any]:
    """Resolve the X-ResuAlign-Token header to a tenant for local ingestion."""
    token = x_resualign_token.strip()
    if not token:
        raise HTTPException(
            status_code=401,
            detail={
                'code': 'missing_token',
                'reason': '缺少 X-ResuAlign-Token 请求头',
                'action': (
                    '请在系统设置页复制本地摄入 Token，'
                    '并粘贴到油猴脚本配置中'
                ),
            },
        )
    store = getattr(context, '_settings_store', None)
    tenant_id = (
        store.find_tenant_by_local_ingest_token(token)
        if store is not None
        else None
    )
    if tenant_id is None:
        raise HTTPException(
            status_code=401,
            detail={
                'code': 'invalid_token',
                'reason': 'X-ResuAlign-Token 无效或已重置',
                'action': (
                    '请在系统设置页重新复制 Token，'
                    '并同步更新油猴脚本配置'
                ),
            },
        )
    return {'user_id': tenant_id}

