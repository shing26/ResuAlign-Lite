
import threading
import time
from typing import Any, Optional

from fastapi import Depends, Header, HTTPException, Request

import resualign.api as api_module


class _RateLimiter:
    """Minimal in-memory sliding-window rate limiter per client key."""

    def __init__(self, max_requests: int, window_seconds: float=60.0):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = [timestamp for timestamp in self._hits.get(key, []) if now - timestamp < self.window_seconds]
            if len(hits) >= self.max_requests:
                self._hits[key] = hits
                return False
            hits.append(now)
            self._hits[key] = hits
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

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
        user = api_module._users.user_for_token(token)
        if user is not None:
            return user
    elif api_module._PERSONAL_MODE:
        return api_module._users.get_or_create_personal_user()
    else:
        raise HTTPException(status_code=401, detail='Not authenticated', headers={'WWW-Authenticate': 'Bearer'})
    raise HTTPException(status_code=401, detail='Invalid or expired token', headers={'WWW-Authenticate': 'Bearer'})

