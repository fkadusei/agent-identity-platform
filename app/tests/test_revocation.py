"""Revocation (S23): the store, the client, and admission refusal."""
from __future__ import annotations

import pytest

from app.api.revocations import RevocationStore
from app.common import revocation, workload

AGENT = workload.AGENT


@pytest.fixture(autouse=True)
def _clean():
    revocation.reset()
    yield
    revocation.reset()


def test_the_store_revokes_restores_and_lists():
    store = RevocationStore()
    store.revoke(AGENT, reason="rogue", by="admin")
    assert store.ids() == {AGENT}
    assert store.all()[0]["reason"] == "rogue"
    assert store.restore(AGENT) is True
    assert store.ids() == set()


def test_the_client_uses_an_in_process_source():
    revocation.set_source(lambda: {AGENT})
    assert revocation.is_revoked(AGENT)
    assert not revocation.is_revoked("spiffe://acme.com/ns/agent-platform/sa/other")


def test_disabled_without_a_source_or_url():
    # No source and no REVOCATION_URL: nothing is revoked, no network is touched.
    assert revocation.revoked_ids() == set()


def test_a_revoked_caller_is_refused_at_admission(monkeypatch):
    """The point of S23: refusal at admission, not at SVID expiry."""
    monkeypatch.setenv("WORKLOAD_AUDIENCE", workload.TOOLS)

    class Keys:
        def get_signing_key_from_jwt(self, token):
            return type("K", (), {"key": "k"})()

    monkeypatch.setattr(workload, "_keys", lambda: Keys())
    monkeypatch.setattr(workload.jwt, "decode", lambda *a, **k: {"sub": AGENT})
    revocation.set_source(lambda: {AGENT})

    with pytest.raises(workload.WorkloadRejected, match="revoked"):
        workload.verify("Bearer x")


def test_an_unrevoked_caller_passes_admission(monkeypatch):
    monkeypatch.setenv("WORKLOAD_AUDIENCE", workload.TOOLS)

    class Keys:
        def get_signing_key_from_jwt(self, token):
            return type("K", (), {"key": "k"})()

    monkeypatch.setattr(workload, "_keys", lambda: Keys())
    monkeypatch.setattr(workload.jwt, "decode", lambda *a, **k: {"sub": AGENT})
    revocation.set_source(lambda: set())

    assert workload.verify("Bearer x") == AGENT
