"""Token verification: signature, issuer, audience, and issued-to (azp)."""
from __future__ import annotations

import pytest

from agentnhi import Settings, TokenRejected, TokenVerifier
from agentnhi.tokens import Delegation
from tests.constants import AGENT, AUDIENCE, ISSUER, OTHER_AGENT


def verifier(resolver, **settings):
    base = dict(keycloak_issuer=ISSUER, audience=AUDIENCE, trusted_workload=AGENT)
    base.update(settings)
    return TokenVerifier(Settings(**base), signing_key_resolver=resolver)


def test_valid_token_yields_delegation(resolver, make_token):
    token = make_token()
    d = verifier(resolver).verify(token)
    assert isinstance(d, Delegation)
    assert d.user == "alice"
    assert d.workload == AGENT
    assert d.audience == AUDIENCE


def test_user_falls_back_to_subject_when_no_username(resolver, make_token):
    token = make_token(preferred_username=None)
    assert verifier(resolver).verify(token).user == "user-123"


def test_roles_are_extracted_from_realm_access(resolver, make_token):
    token = make_token(realm_access={"roles": ["support_rep", "privacy"]})
    assert verifier(resolver).verify(token).roles == ("support_rep", "privacy")


def test_roles_default_to_empty(resolver, make_token):
    assert verifier(resolver).verify(make_token()).roles == ()


def test_wrong_audience_is_rejected(resolver, make_token):
    token = make_token(aud="some-other-service")
    with pytest.raises(TokenRejected, match="audience"):
        verifier(resolver).verify(token)


def test_forwarded_token_is_rejected_by_azp(resolver, make_token):
    token = make_token(azp=OTHER_AGENT)
    with pytest.raises(TokenRejected, match="issued to"):
        verifier(resolver).verify(token)


def test_azp_check_is_skipped_when_not_configured(resolver, make_token):
    token = make_token(azp=OTHER_AGENT)
    d = verifier(resolver, trusted_workload=None).verify(token)
    assert d.workload == OTHER_AGENT


def test_expired_token_is_rejected(resolver, make_token):
    token = make_token(exp=1, iat=1)
    with pytest.raises(TokenRejected):
        verifier(resolver).verify(token)


def test_wrong_issuer_is_rejected(resolver, make_token):
    token = make_token(iss="http://evil.example/realms/x")
    with pytest.raises(TokenRejected):
        verifier(resolver).verify(token)


def test_bad_signature_is_rejected(make_token):
    token = make_token()
    from cryptography.hazmat.primitives.asymmetric import rsa

    other = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key()
    with pytest.raises(TokenRejected, match="invalid token"):
        TokenVerifier(
            Settings(keycloak_issuer=ISSUER, audience=AUDIENCE, trusted_workload=AGENT),
            signing_key_resolver=lambda _t: other,
        ).verify(token)


def test_missing_audience_config_is_an_error(resolver, make_token):
    with pytest.raises(TokenRejected, match="no expected audience"):
        TokenVerifier(
            Settings(keycloak_issuer=ISSUER, audience="", trusted_workload=AGENT),
            signing_key_resolver=resolver,
        ).verify(make_token())
