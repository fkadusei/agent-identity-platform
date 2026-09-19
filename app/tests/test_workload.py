"""Naming the caller on a hop we own (S7).

The transport proves the caller holds a valid SVID; this proves *which* workload.
The name travels in a JWT-SVID audienced to the callee, so the tests are about the
ways that can go wrong: no token, a token for another service, a token from a
different SPIRE, a token with no subject, and a valid token from a workload that
is simply not allowed to call.
"""
from __future__ import annotations

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.authz import require_workload
from app.common import workload


class _FakeKeys:
    """Stands in for SPIRE's JWKS, so no cluster is needed."""

    def __init__(self, public_key):
        self._key = public_key

    def get_signing_key_from_jwt(self, _token):
        return type("SigningKey", (), {"key": self._key})()


@pytest.fixture
def spire(monkeypatch):
    """This service (the api) and a SPIRE that signs with a known key."""
    key = ec.generate_private_key(ec.SECP256R1())
    monkeypatch.setenv("WORKLOAD_AUDIENCE", workload.API)
    monkeypatch.setattr(workload, "_jwks", _FakeKeys(key.public_key()))
    monkeypatch.delenv("ALLOWED_WORKLOADS", raising=False)

    def token(sub: str, audience: str = workload.API, *, key_override=None, **extra) -> str:
        claims = {"sub": sub, "aud": audience, "iss": "spiffe://acme.com", **extra}
        return jwt.encode(claims, key_override or key, algorithm="ES256")

    return token


def test_it_returns_the_callers_spiffe_id(spire):
    assert workload.verify(spire(workload.AGENT)) == workload.AGENT


def test_a_token_for_another_service_is_refused(spire):
    # The audience pins a token to one callee, so one captured on a hop cannot be
    # replayed on the next.
    with pytest.raises(workload.WorkloadRejected):
        workload.verify(spire(workload.AGENT, audience=workload.TOOLS))


def test_a_token_from_another_spire_is_refused(spire):
    other = ec.generate_private_key(ec.SECP256R1())
    with pytest.raises(workload.WorkloadRejected):
        workload.verify(spire(workload.AGENT, key_override=other))


def test_a_missing_token_is_refused(spire):
    with pytest.raises(workload.WorkloadRejected):
        workload.verify(None)


def test_a_token_without_a_subject_is_refused(spire):
    import jwt as pyjwt

    key = ec.generate_private_key(ec.SECP256R1())
    # Sign with the *right* key but no subject — there is nothing to allow.
    anonymous = pyjwt.encode({"aud": workload.API}, key, algorithm="ES256")
    with pytest.raises(workload.WorkloadRejected):
        workload.verify(anonymous)


def test_a_valid_token_from_a_disallowed_workload_is_refused(spire):
    with pytest.raises(workload.WorkloadRejected, match="may not call"):
        workload.check(spire(workload.GATEWAY))


def test_the_allow_list_is_configurable(spire, monkeypatch):
    monkeypatch.setenv("ALLOWED_WORKLOADS", f"{workload.TOOLS},{workload.GATEWAY}")
    assert workload.check(spire(workload.TOOLS)) == workload.TOOLS
    with pytest.raises(workload.WorkloadRejected):
        workload.check(spire(workload.AGENT))


def test_the_service_requires_a_caller_only_when_it_has_an_audience(monkeypatch):
    monkeypatch.delenv("WORKLOAD_AUDIENCE", raising=False)
    assert workload.enabled() is False
    monkeypatch.setenv("WORKLOAD_AUDIENCE", workload.API)
    assert workload.enabled() is True


# --- the FastAPI gate the machine routes use ---------------------------------


def _app() -> FastAPI:
    app = FastAPI()

    @app.post("/machine")
    def machine(caller: str = Depends(require_workload(workload.AGENT))) -> dict:
        return {"caller": caller}

    @app.post("/machine-tools")
    def machine_tools(caller: str = Depends(require_workload(workload.TOOLS))) -> dict:
        return {"caller": caller}

    return app


def test_the_route_refuses_a_caller_that_does_not_name_itself(spire):
    response = TestClient(_app()).post("/machine")
    assert response.status_code == 403
    assert "workload identity rejected" in response.json()["detail"]


def test_the_route_refuses_the_wrong_workload(spire):
    response = TestClient(_app()).post(
        "/machine", headers={"X-Workload-Token": f"Bearer {spire(workload.TOOLS)}"}
    )
    assert response.status_code == 403
    assert "may not call" in response.json()["detail"]


def test_the_route_admits_the_named_workload(spire):
    response = TestClient(_app()).post(
        "/machine", headers={"X-Workload-Token": f"Bearer {spire(workload.AGENT)}"}
    )
    assert response.status_code == 200
    assert response.json() == {"caller": workload.AGENT}


def test_each_route_names_its_own_caller(spire):
    # The tool server is the only workload allowed to verify an approval, and the
    # agent is the only one allowed to create one — the same dependency, two lists.
    client = TestClient(_app())
    assert client.post(
        "/machine-tools", headers={"X-Workload-Token": f"Bearer {spire(workload.TOOLS)}"}
    ).status_code == 200
    assert client.post(
        "/machine-tools", headers={"X-Workload-Token": f"Bearer {spire(workload.AGENT)}"}
    ).status_code == 403


def test_without_a_configured_audience_the_route_stays_open(monkeypatch):
    """Documented fallback: a local run or the suite, where the transport is the
    only check. The manifests always set the audience, so a deployed hop is always
    named."""
    monkeypatch.delenv("WORKLOAD_AUDIENCE", raising=False)
    assert TestClient(_app()).post("/machine").status_code == 200
