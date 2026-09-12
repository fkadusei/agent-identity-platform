"""Structured audit records that are safe by default.

The invariant this module enforces: **no secret, token, or personal data leaves
this process in an audit record** unless a caller explicitly allows it.

Redaction is applied to both keys and values, recursively:

* keys that look like credentials (`authorization`, `*token*`, `*secret*`,
  `*assertion*`, `jti`, `*api_key*`, ...) are replaced wholesale;
* keys that are known personal-data fields (`email`, `name`, `pan`, ...) are
  replaced with a marker;
* string values that look like a JWT or a `Bearer ...` header are masked even
  when they appear inside an otherwise-innocent field.

One record per event, keyed by identity fields, so a single query can answer
"which workload did what, on whose behalf, and why was it allowed".
"""
from __future__ import annotations

import json
import re
import sys
import time
from typing import Any, Callable

# Substring match on the KEY: catches access_token, client_assertion, api_key, ...
_SECRET_KEY_RE = re.compile(
    r"(?i)(authorization|cookie|token|secret|password|passwd|"
    r"api[_-]?key|assertion|jti|credential|private[_-]?key|session)"
)

# Exact match on the lowercased KEY: avoids over-redacting e.g. "hostname".
_PII_KEYS = {
    "name", "full_name", "first_name", "last_name", "customer_name", "username",
    "email", "email_address", "phone", "phone_number", "ssn", "tax_id",
    "address", "street", "city", "postal_code", "zip", "dob", "date_of_birth",
    "card", "card_number", "pan", "cvv", "cvc", "iban", "account_number",
    "routing_number",
}

# Value patterns masked regardless of the field they appear in.
_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}")
_BEARER_RE = re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+")

REDACTED = "[REDACTED]"
REDACTED_PII = "[REDACTED:pii]"

_extra_keys: set[str] = set()
_sink: Callable[[dict], None] | None = None


def configure(*, extra_keys: tuple[str, ...] = ()) -> None:
    """Register additional field names to treat as personal data."""
    _extra_keys.clear()
    _extra_keys.update(k.lower() for k in extra_keys)


def set_sink(sink: Callable[[dict], None] | None) -> None:
    """Override where records go (tests use this; default is stdout)."""
    global _sink
    _sink = sink


def _is_secret_key(key: str) -> bool:
    return bool(_SECRET_KEY_RE.search(key))


def _is_pii_key(key: str) -> bool:
    k = key.strip().lower()
    return k in _PII_KEYS or k in _extra_keys


def _redact_string(value: str) -> str:
    value = _JWT_RE.sub("[REDACTED:jwt]", value)
    value = _BEARER_RE.sub("Bearer [REDACTED]", value)
    return value


def redact(value: Any, *, key: str | None = None) -> Any:
    """Return a copy of ``value`` with secrets and personal data removed."""
    if key is not None:
        if _is_secret_key(key):
            return REDACTED
        if _is_pii_key(key):
            return REDACTED_PII
    if isinstance(value, dict):
        return {k: redact(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return _redact_string(value)
    return value


def _emit(record: dict) -> None:
    if _sink is not None:
        _sink(record)
        return
    json.dump(record, sys.stdout, default=str)
    sys.stdout.write("\n")
    sys.stdout.flush()


def audit(event: str, **fields: Any) -> dict:
    """Emit one redaction-safe structured record and return it."""
    record: dict[str, Any] = {"ts": round(time.time(), 3), "event": event}
    record.update(redact(fields))
    _emit(record)
    return record
