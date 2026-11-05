import json
from hashlib import sha256
from secrets import compare_digest, randbelow
from threading import Lock
from time import monotonic
from typing import Any

import redis

from app.core.config import get_settings
from app.core.exceptions import AppError


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
            client = self._client()
            raw = client.get(key)
            if raw is None:
                return False
            data = json.loads(raw)
            expected = data["hash"]
            if int(data["attempts"]) >= 5:
                client.delete(key)
                return False
            valid = compare_digest(expected, self._hash(email, code))
            if valid and consume:
                client.delete(key)
            elif not valid:
                data["attempts"] = int(data["attempts"]) + 1
                client.set(key, json.dumps(data), keepttl=True)
            return valid
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
