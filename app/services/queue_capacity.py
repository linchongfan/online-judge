"""Atomic judge-queue capacity reservation.

A submission reserves one global and one per-user slot in Redis once every
other validation has passed; the slot is released when the submission reaches
a terminal state. Reservations are keyed by submission id, so releasing is
idempotent — duplicate terminal events can never free another submission's
slot — and a bounded TTL bounds the damage of a crashed process.

When Redis is unavailable in non-production, this falls back to the legacy
database count check; in production a reservation failure is fail-closed.
"""

from __future__ import annotations

from typing import Any

import redis

from app.core.config import get_settings

# Bound the reservation lifetime well above the longest realistic queue wait.
RESERVATION_TTL_SECONDS = 3_600

_RESERVE_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current > tonumber(ARGV[1]) then
  redis.call('DECR', KEYS[1])
  return 0
end
redis.call('EXPIRE', KEYS[1], ARGV[2])
return 1
"""

# KEYS[1] = per-submission reservation key (value: owning user id)
# KEYS[2] = global counter. The per-user counter is derived from the owner.
# Returns 1 when a reservation was consumed, 0 when there was none (the
# release is idempotent).
_DECR_SCRIPT = """
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
if current > 0 then
  redis.call('DECR', KEYS[1])
end
return 1
"""

_RELEASE_SCRIPT = """
local owner = redis.call('GET', KEYS[1])
if not owner then
  return 0
end
redis.call('DEL', KEYS[1])
local global_count = tonumber(redis.call('GET', KEYS[2]) or '0')
if global_count > 0 then
  redis.call('DECR', KEYS[2])
end
local user_key = 'judge:slots:user:' .. owner
local user_count = tonumber(redis.call('GET', user_key) or '0')
if user_count > 0 then
  redis.call('DECR', user_key)
end
return 1
"""


class QueueCapacityError(RuntimeError):
    """Base class for capacity failures."""


class GlobalQueueFull(QueueCapacityError):
    pass


class UserQueueFull(QueueCapacityError):
    pass


class QueueCapacity:
    def __init__(self) -> None:
        self._redis: Any = None

    def _client(self) -> Any:
        if self._redis is None:
            self._redis = redis.Redis.from_url(
                get_settings().redis_url, socket_connect_timeout=0.3, socket_timeout=0.5
            )
        return self._redis

    @staticmethod
    def _global_key() -> str:
        return "judge:slots:global"

    @staticmethod
    def _user_key(user_id: int) -> str:
        return f"judge:slots:user:{user_id}"

    @staticmethod
    def _submission_key(submission_id: str) -> str:
        return f"judge:slot:sub:{submission_id}"

    def reserve(self, submission_id: str, user_id: int, global_limit: int, user_limit: int) -> None:
        """Reserve one queue slot for this submission, or raise."""
        try:
            client = self._client()
            global_ok = bool(
                client.eval(_RESERVE_SCRIPT, 1, self._global_key(), global_limit, RESERVATION_TTL_SECONDS)
            )
            if not global_ok:
                raise GlobalQueueFull("global queue full")
            user_ok = bool(
                client.eval(_RESERVE_SCRIPT, 1, self._user_key(user_id), user_limit, RESERVATION_TTL_SECONDS)
            )
            if not user_ok:
                # The user counter already rolled itself back inside the Lua
                # script; only undo the global slot we actually took. The
                # submission has no reservation key yet, so this must be a
                # plain decrement, not the submission-linked release.
                client.eval(_DECR_SCRIPT, 1, self._global_key())
                raise UserQueueFull("user queue full")
            # Link the reservation to the submission so terminal release is
            # idempotent and can find the owning user.
            client.set(self._submission_key(submission_id), user_id, ex=RESERVATION_TTL_SECONDS)
            return
        except redis.RedisError:
            if get_settings().is_production:
                # Fail closed: without a reservation we cannot bound the queue.
                raise GlobalQueueFull("queue reservation unavailable") from None
            raise _FallbackToCountCheck from None

    def release(self, submission_id: str) -> None:
        """Idempotently return this submission's slots."""
        try:
            self._client().eval(_RELEASE_SCRIPT, 2, self._submission_key(submission_id), self._global_key())
        except redis.RedisError:
            # The reservation TTL bounds the damage of a lost release.
            return


class _FallbackToCountCheck(Exception):
    """Internal signal: Redis unavailable in a non-production environment."""


queue_capacity = QueueCapacity()


def reserve_or_raise(db, submission_id: str, user_id: int, global_limit: int, user_limit: int) -> None:
    """Reserve a slot; on Redis failure outside production, count in the DB."""
    from sqlalchemy import func, select

    from app.core.exceptions import AppError
    from app.models import JudgeStatus, Submission

    try:
        queue_capacity.reserve(submission_id, user_id, global_limit, user_limit)
        return
    except GlobalQueueFull as exc:
        if str(exc) == "global queue full":
            raise AppError(503, "GLOBAL_QUEUE_FULL", "判题队列已满，请稍后再试") from None
        raise AppError(503, "QUEUE_UNAVAILABLE", "判题队列暂不可用，请稍后再试") from None
    except UserQueueFull:
        raise AppError(429, "USER_QUEUE_FULL", "等待判题的提交过多，请稍后提交") from None
    except _FallbackToCountCheck:
        active = [JudgeStatus.PENDING, JudgeStatus.JUDGING]
        total_queued = db.scalar(select(func.count(Submission.id)).where(Submission.status.in_(active))) or 0
        if total_queued >= global_limit:
            raise AppError(503, "GLOBAL_QUEUE_FULL", "判题队列已满，请稍后再试") from None
        queued = (
            db.scalar(
                select(func.count(Submission.id)).where(
                    Submission.user_id == user_id, Submission.status.in_(active)
                )
            )
            or 0
        )
        if queued >= user_limit:
            raise AppError(429, "USER_QUEUE_FULL", "等待判题的提交过多，请稍后提交") from None
