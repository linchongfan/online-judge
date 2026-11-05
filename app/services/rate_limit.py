from threading import Lock
from time import monotonic
from typing import Any

import redis

from app.core.config import get_settings


class RateLimiter:
    def __init__(self) -> None:
        self._local: dict[str, tuple[int, float]] = {}
        self._lock = Lock()
        self._redis: Any = None

    def _client(self) -> Any:
        if self._redis is None:
            self._redis = redis.Redis.from_url(get_settings().redis_url, socket_connect_timeout=0.3, socket_timeout=0.5)
        return self._redis

    def allow(self, key: str, limit: int, window_seconds: int) -> bool:
        try:
            client = self._client()
            current = client.incr(key)
            if current == 1:
                client.expire(key, window_seconds)
            return int(current) <= limit
        except redis.RedisError:
            if get_settings().is_production:
                return False
            return self._allow_local(key, limit, window_seconds)

    def _allow_local(self, key: str, limit: int, window_seconds: int) -> bool:
        now = monotonic()
        with self._lock:
            count, expires = self._local.get(key, (0, now + window_seconds))
            if expires <= now:
                count, expires = 0, now + window_seconds
            count += 1
            self._local[key] = (count, expires)
            if len(self._local) > 10_000:
                self._local = {k: v for k, v in self._local.items() if v[1] > now}
            return count <= limit


rate_limiter = RateLimiter()
