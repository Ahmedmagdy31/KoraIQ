"""Redis sliding-window-log rate limiter (atomic Lua). Fails OPEN if Redis is down: availability of a
free game beats strictness; server-side game timing is the real anti-cheat control."""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import HTTPException, Request, status

from app.config import get_settings
from app.redis_client import get_redis

log = logging.getLogger(__name__)

_LUA = """
local key, now, window, limit, member = KEYS[1], tonumber(ARGV[1]), tonumber(ARGV[2]), tonumber(ARGV[3]), ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local count = redis.call('ZCARD', key)
if count >= limit then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
  return {0, math.ceil((tonumber(oldest[2]) + window - now) / 1000)}
end
redis.call('ZADD', key, now, member)
redis.call('PEXPIRE', key, window)
return {1, 0}
"""


def client_ip(request: Request) -> str:
    """Right-most untrusted hop of X-Forwarded-For, given N trusted proxies (Cloud Run / LB)."""
    hops = get_settings().trusted_proxy_hops
    xff = request.headers.get("x-forwarded-for")
    if xff and hops > 0:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if len(parts) >= hops:
            return parts[-hops]
    return request.client.host if request.client else "unknown"


async def hit(bucket: str, limit: int, window_s: int = 60) -> None:
    try:
        allowed, retry = await get_redis().eval(_LUA, 1, f"rl:{bucket}", int(time.time() * 1000), window_s * 1000, limit, uuid.uuid4().hex)
    except Exception:  # noqa: BLE001
        log.warning("rate limiter unavailable; failing open", exc_info=True)
        return
    if not int(allowed):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "rate_limited", headers={"Retry-After": str(max(1, int(retry)))})
