"""Reliable judge result consumer.

Uses BRPOPLPUSH so a message is only removed from the processing list after
it has been persisted. Transient failures requeue with backoff; permanently
invalid messages (bad signature, schema violations, state conflicts) go to a
dead-letter list for operator inspection instead of being dropped silently.
"""

import json
import logging
import time
from typing import Any, cast

import redis

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.signing import verify_result_signature
from app.tasks.results import process_judge_result, process_judge_started

logger = logging.getLogger(__name__)

QUEUE = "judge:results"
PROCESSING_QUEUE = "judge:results:processing"
DEAD_LETTER_QUEUE = "judge:results:dead"
MAX_REQUEUE_ATTEMPTS = 8


def _client() -> redis.Redis:
    settings = get_settings()
    return redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=30)


def _recover_stale_processing(client: redis.Redis) -> int:
    """On startup, return unfinished processing items to the main queue."""
    recovered = 0
    while True:
        item = client.rpoplpush(PROCESSING_QUEUE, QUEUE)
        if item is None:
            return recovered
        recovered += 1


def _dead_letter(client: redis.Redis, raw: bytes, reason: str) -> None:
    logger.warning("Dead-lettering judge message: %s", reason)
    client.rpush(DEAD_LETTER_QUEUE, json.dumps({"reason": reason, "raw": raw.decode("utf-8", "replace")}))


def _ack(client: redis.Redis, raw: bytes) -> None:
    # redis-py accepts bytes at runtime; the typed stub declares str.
    client.lrem(PROCESSING_QUEUE, 1, cast(str, raw))


def _handle_message(client: redis.Redis, raw: bytes) -> None:
    try:
        message = json.loads(raw)
    except json.JSONDecodeError:
        _dead_letter(client, raw, "invalid JSON")
        _ack(client, raw)
        return
    payload = message.get("payload")
    signature = message.get("signature", "")
    if not isinstance(payload, dict) or not verify_result_signature(payload, signature):
        _dead_letter(client, raw, "invalid signature")
        _ack(client, raw)
        return
    try:
        if payload.get("event") == "started":
            process_judge_started(payload)
        else:
            process_judge_result(payload)
    except AppError as exc:
        # Permanent validation/state problem: never retry, keep for inspection.
        _dead_letter(client, raw, f"{exc.code}: {exc.message}")
        _ack(client, raw)
    except Exception:
        # Transient failure (database hiccup, etc.): requeue with a bounded
        # number of attempts. The message stays in the processing list until
        # the requeue succeeds, so a crash mid-requeue is recoverable.
        attempts = int(message.get("attempts", 0)) if isinstance(message, dict) else 0
        if attempts + 1 >= MAX_REQUEUE_ATTEMPTS:
            _dead_letter(client, raw, "too many transient failures")
            _ack(client, raw)
            return
        logger.exception("Temporary failure handling judge message; requeueing")
        message["attempts"] = attempts + 1
        # Push the retried envelope before acknowledging the original: a crash
        # in between leaves a duplicate, which idempotent result handling
        # tolerates, rather than a lost result.
        client.rpush(QUEUE, json.dumps(message, ensure_ascii=False))
        _ack(client, raw)
        time.sleep(min(2, 0.25 * 2 ** attempts))
    else:
        _ack(client, raw)


def consume_results(block_ms: int = 5000) -> None:
    client = _client()
    recovered = _recover_stale_processing(client)
    if recovered:
        logger.info("Recovered %s unacknowledged judge messages", recovered)
    logger.info("Judge result consumer started")
    while True:
        try:
            item = cast(Any, client.brpoplpush(QUEUE, PROCESSING_QUEUE, timeout=max(1, block_ms // 1000)))
            if item is None:
                continue
            _handle_message(client, item[1])
        except redis.RedisError:
            logger.exception("Result consumer transport error; reconnecting")
            time.sleep(2)
        except Exception:
            # Bug outside the message handler: the in-flight message is still
            # in the processing list. This loop is single-threaded, so pushing
            # processing items back to the queue cannot disturb other work.
            logger.exception("Unexpected consumer error; returning message to queue")
            try:
                _recover_stale_processing(client)
            except redis.RedisError:
                logger.exception("Failed to recover processing queue")
            time.sleep(1)


if __name__ == "__main__":
    consume_results()
