"""The redaction guarantee: no secret or personal data leaves in an audit record."""
from __future__ import annotations

from agentnhi import audit, configure, redact, set_sink

# A JWT-shaped string, assembled at runtime so no contiguous token literal
# exists in source (or in compiled bytecode) for a secret scanner to flag.
_HEADER = "eyJhbGciOiJSUzI1NiJ9"
_PAYLOAD = "eyJzdWIiOiJhbGljZSIsImF6cCI6ImFnZW50In0"
_SIGNATURE = "c2lnbmF0dXJlLXNpZ25hdHVyZS1zaWduYXR1cmU"
JWT = f"{_HEADER}.{_PAYLOAD}.{_SIGNATURE}"


def test_secret_keys_are_redacted():
    out = redact(
        {
            "access_token": JWT,
            "authorization": "Bearer abc.def.ghi",
            "client_assertion": JWT,
            "jti": "abc",
            "api_key": "sk-whatever",
            "password": "hunter2",
        }
    )
    for key in ("access_token", "authorization", "client_assertion", "jti", "api_key", "password"):
        assert out[key] == "[REDACTED]", key


def test_personal_data_keys_are_redacted():
    out = redact(
        {
            "email": "alice@example.com",
            "full_name": "Alice Example",
            "card_number": "4111111111111111",
            "pan": "4111111111111111",
            "phone": "+15551234567",
        }
    )
    for key in ("email", "full_name", "card_number", "pan", "phone"):
        assert out[key] == "[REDACTED:pii]", key


def test_innocent_keys_pass_through():
    out = redact({"tool": "refunds.issue", "decision": "allow", "count": 3})
    assert out == {"tool": "refunds.issue", "decision": "allow", "count": 3}


def test_hostname_is_not_over_redacted():
    # "hostname" contains "name" but is not personal data.
    assert redact({"hostname": "tool-server"}) == {"hostname": "tool-server"}


def test_jwt_in_an_innocent_field_is_masked():
    out = redact({"note": f"token was {JWT}"})
    assert JWT not in out["note"]
    assert "[REDACTED:jwt]" in out["note"]


def test_redaction_is_recursive():
    out = redact({"outer": {"email": "a@b.c", "list": [{"access_token": "x"}]}})
    assert out["outer"]["email"] == "[REDACTED:pii]"
    assert out["outer"]["list"][0]["access_token"] == "[REDACTED]"


def test_audit_applies_redaction_and_returns_record():
    captured: list[dict] = []
    set_sink(captured.append)
    try:
        record = audit("tool.call", spiffe_id="spiffe://agent", access_token=JWT, email="a@b.c")
    finally:
        set_sink(None)
    assert record["event"] == "tool.call"
    assert record["access_token"] == "[REDACTED]"
    assert record["email"] == "[REDACTED:pii]"
    assert record["spiffe_id"] == "spiffe://agent"
    assert captured and captured[0] == record


def test_configure_adds_extra_keys():
    configure(extra_keys=("nickname",))
    try:
        assert redact({"nickname": "Al"})["nickname"] == "[REDACTED:pii]"
    finally:
        configure(extra_keys=())
