"""Compatibility import for the relocated rate limiter."""

from ..app.rate_limit import _RateLimiter

__all__ = ["_RateLimiter"]
