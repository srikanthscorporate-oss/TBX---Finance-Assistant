"""Redis access.

Every method degrades to a no-op when Redis is unreachable. Keys carry the
dataset version, so a reload invalidates old entries without a flush.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

log = logging.getLogger("tbx.cache")

try:
    import redis  # type: ignore
except ImportError:  # pragma: no cover
    redis = None


class Cache:
    def __init__(self, url: str | None = None, prefix: str = "tbx"):
        self.prefix = prefix
        self._r = None
        url = url or os.getenv("REDIS_URL", "")
        if redis is not None and url:
            try:
                client = redis.Redis.from_url(url, socket_connect_timeout=1.5,
                                              socket_timeout=1.5, decode_responses=True)
                client.ping()
                self._r = client
                log.info("redis connected: %s", url.split("@")[-1])
            except Exception as e:  # noqa: BLE001
                log.warning("redis unavailable, caching disabled: %s", e)

    @property
    def enabled(self) -> bool:
        return self._r is not None

    def _k(self, *parts: str) -> str:
        return ":".join((self.prefix, *parts))

    def get_json(self, *parts: str) -> Any | None:
        if not self._r:
            return None
        try:
            raw = self._r.get(self._k(*parts))
            return json.loads(raw) if raw else None
        except Exception as e:  # noqa: BLE001
            log.debug("cache get failed: %s", e)
            return None

    def set_json(self, *parts: str, value: Any, ttl: int | None) -> None:
        """`ttl=None` stores the value without an expiry, for state that must survive
        a restart rather than age out (the active data source pointer)."""
        if not self._r:
            return
        try:
            self._r.set(self._k(*parts), json.dumps(value, default=str), ex=ttl)
        except Exception as e:  # noqa: BLE001
            log.debug("cache set failed: %s", e)

    def delete(self, *parts: str) -> None:
        if self._r:
            try:
                self._r.delete(self._k(*parts))
            except Exception:  # noqa: BLE001
                pass

    def delete_prefix(self, *parts: str) -> int:
        """Delete every key under a prefix with SCAN, so a large history never blocks Redis."""
        if not self._r:
            return 0
        removed = 0
        try:
            for key in self._r.scan_iter(match=self._k(*parts) + ":*", count=500):
                removed += int(self._r.delete(key))
        except Exception as e:  # noqa: BLE001
            log.debug("cache delete_prefix failed: %s", e)
        return removed

    def incr(self, *parts: str, ttl: int | None = None) -> int:
        if not self._r:
            return 0
        try:
            k = self._k(*parts)
            n = self._r.incr(k)
            if ttl and n == 1:
                self._r.expire(k, ttl)
            return int(n)
        except Exception:  # noqa: BLE001
            return 0

    def get_int(self, *parts: str) -> int:
        if not self._r:
            return 0
        try:
            return int(self._r.get(self._k(*parts)) or 0)
        except Exception:  # noqa: BLE001
            return 0

    def ttl(self, *parts: str) -> int:
        if not self._r:
            return -2
        try:
            return int(self._r.ttl(self._k(*parts)))
        except Exception:  # noqa: BLE001
            return -2

    def set_flag(self, *parts: str, ttl: int) -> None:
        if self._r:
            try:
                self._r.set(self._k(*parts), "1", ex=max(1, ttl))
            except Exception:  # noqa: BLE001
                pass

    def flag(self, *parts: str) -> bool:
        if not self._r:
            return False
        try:
            return self._r.exists(self._k(*parts)) == 1
        except Exception:  # noqa: BLE001
            return False

    def push(self, *parts: str, value: Any, keep: int = 500) -> None:
        if not self._r:
            return
        try:
            k = self._k(*parts)
            p = self._r.pipeline()
            p.lpush(k, json.dumps(value, default=str)); p.ltrim(k, 0, keep - 1); p.execute()
        except Exception:  # noqa: BLE001
            pass

    def recent(self, *parts: str, n: int = 100) -> list[Any]:
        if not self._r:
            return []
        try:
            return [json.loads(x) for x in self._r.lrange(self._k(*parts), 0, n - 1)]
        except Exception:  # noqa: BLE001
            return []


_cache: Cache | None = None


def cache() -> Cache:
    global _cache
    if _cache is None:
        _cache = Cache()
    return _cache
