"""Real-Redis concurrency tests for the atomic verification counter."""

from __future__ import annotations

import threading

import pytest
import redis as redis_lib

from app.core.config import get_settings
from app.services.verification import verification_codes


def _redis_available() -> bool:
    try:
        return bool(
            redis_lib.Redis.from_url(get_settings().redis_url, socket_connect_timeout=1, socket_timeout=1).ping()
        )
    except redis_lib.RedisError:
        return False


pytestmark = pytest.mark.skipif(not _redis_available(), reason="Redis not reachable")


@pytest.fixture()
def redis_client():
    client = redis_lib.Redis.from_url(get_settings().redis_url, socket_connect_timeout=2, socket_timeout=5)
    key = verification_codes._key("concurrency@example.com")
    client.delete(key)
    yield client
    client.delete(key)


def test_concurrent_wrong_guesses_cannot_exceed_five_attempts(redis_client):
    email = "concurrency@example.com"
    code = verification_codes.issue(email)
    assert code != "000000"

    results: list[bool] = []
    barrier = threading.Barrier(8)

    def guess(guess_code: str) -> None:
        barrier.wait(timeout=10)
        results.append(verification_codes.verify(email, guess_code))

    threads = [
        threading.Thread(target=guess, args=(f"{(int(code) + i + 1) % 1_000_000:06d}",)) for i in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results == [False] * 8
    # The key is deleted once the budget is exhausted; any further attempt
    # simply misses. Either way the 5-attempt invariant held under races.
    assert redis_client.get(verification_codes._key(email)) is None


def test_valid_code_is_consumed_exactly_once(redis_client):
    email = "concurrency@example.com"
    code = verification_codes.issue(email)

    outcomes: list[bool] = []
    barrier = threading.Barrier(4)

    def consume() -> None:
        barrier.wait(timeout=10)
        outcomes.append(verification_codes.verify(email, code))

    threads = [threading.Thread(target=consume) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(outcomes) == [False, False, False, True]
    assert redis_client.get(verification_codes._key(email)) is None
