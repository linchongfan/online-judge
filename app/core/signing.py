import hashlib
import hmac
import json
from typing import Any

from app.core.config import get_settings


def canonical_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_result(payload: dict[str, Any]) -> str:
    return hmac.new(
        get_settings().judge_result_secret.encode("utf-8"), canonical_payload(payload), hashlib.sha256
    ).hexdigest()


def verify_result_signature(payload: dict[str, Any], signature: str) -> bool:
    return hmac.compare_digest(sign_result(payload), signature)
