import json
from hashlib import sha256
from hmac import compare_digest
from secrets import randbelow
from threading import Lock
from time import monotonic
from typing import Any

import redis

from app.core.config import get_settings
from app.core.exceptions import AppError

# Atomic compare/count/consume: concurrent requests can never share one
# attempt budget or consume a valid code twice. The comparison runs inside
# Redis (not constant-time), which is acceptable because the codes live in
# the server-side store and latency is not attacker-observable across the
# trust boundary.
_VERIFY_SCRIPT = """
local raw = redis.call('GET', KEYS[1])
if not raw then
  return 0
end
local data = cjson.decode(raw)
if tonumber(data.attempts) >= 5 then
  redis.call('DEL', KEYS[1])
  return 0
end
if data.hash == ARGV[1] then
  if ARGV[2] == '1' then
    redis.call('DEL', KEYS[1])
  end
  return 1
end
data.attempts = tonumber(data.attempts) + 1
local encoded = cjson.encode(data)
-- Preserve the remaining TTL without KEPTTL (Redis < 6 has no KEPTTL).
local ttl = redis.call('PTTL', KEYS[1])
if ttl > 0 then
  redis.call('SET', KEYS[1], encoded, 'PX', ttl)
else
  redis.call('SET', KEYS[1], encoded)
end
return 0
"""


class VerificationCodeService:
    def __init__(self) -> None:
        self._local: dict[str, tuple[str, int, float]] = {}
        self._lock = Lock()
        self._redis: Any = None

    def _client(self) -> Any:
        if self._redis is None:
            self._redis = redis.Redis.from_url(get_settings().redis_url, socket_connect_timeout=0.3, socket_timeout=0.5)
        return self._redis

    @staticmethod
    def _key(email: str) -> str:
        return f"password-reset:{email.lower()}"

    @staticmethod
    def _hash(email: str, code: str) -> str:
        secret = get_settings().secret_key.encode()
        return sha256(secret + b":" + email.lower().encode() + b":" + code.encode()).hexdigest()

    def issue(self, email: str) -> str:
        code = f"{randbelow(1_000_000):06d}"
        payload = json.dumps({"hash": self._hash(email, code), "attempts": 0})
        try:
            self._client().set(self._key(email), payload, ex=600)
        except redis.RedisError as exc:
            if get_settings().is_production:
                raise AppError(503, "VERIFICATION_UNAVAILABLE", "验证码服务暂时不可用") from exc
            with self._lock:
                self._local[self._key(email)] = (self._hash(email, code), 0, monotonic() + 600)
        return code

    def verify(self, email: str, code: str, *, consume: bool = True) -> bool:
        key = self._key(email)
        try:
            result = self._client().eval(_VERIFY_SCRIPT, 1, key, self._hash(email, code), "1" if consume else "0")
            return bool(result)
        except redis.RedisError as exc:
            if get_settings().is_production:
                raise AppError(503, "VERIFICATION_UNAVAILABLE", "验证码服务暂时不可用") from exc
            return self._verify_local(key, email, code, consume)

    def _verify_local(self, key: str, email: str, code: str, consume: bool) -> bool:
        with self._lock:
            expected, attempts, expires = self._local.get(key, ("", 5, 0))
            if expires <= monotonic() or attempts >= 5:
                self._local.pop(key, None)
                return False
            valid = compare_digest(expected, self._hash(email, code))
            if valid and consume:
                self._local.pop(key, None)
            elif not valid:
                self._local[key] = (expected, attempts + 1, expires)
            return valid


verification_codes = VerificationCodeService()
