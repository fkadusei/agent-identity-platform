"""Workload identity: fetch SPIFFE SVIDs and build an mTLS context.

The SPIFFE library is imported lazily so the rest of the SDK can be used (and
unit-tested) without it installed. Install with ``pip install agentnhi[spiffe]``.

There is deliberately no way to configure a static credential here. If you find
yourself wanting one, the design is telling you to use identity instead.
"""
from __future__ import annotations

import ssl
import tempfile
from pathlib import Path

from .audit import audit
from .errors import IdentityError


def fetch_jwt_svid(spiffe_socket: str, audience: str) -> str:
    """Return a fresh JWT-SVID for this workload, audienced for ``audience``.

    Raises IdentityError if the Workload API is unreachable or issues nothing.
    """
    try:
        from spiffe.workloadapi.workload_api_client import WorkloadApiClient
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on extras
        raise IdentityError(
            "SPIFFE support is not installed (pip install agentnhi[spiffe])"
        ) from exc

    client = WorkloadApiClient(socket_path=spiffe_socket)
    try:
        svid = client.fetch_jwt_svid(audience={audience})
        audit("svid.issued", spiffe_id=str(svid.spiffe_id), aud=list(svid.audience))
        return svid.token
    except Exception as exc:  # noqa: BLE001 - normalized for callers
        raise IdentityError(f"could not fetch JWT-SVID: {exc}") from exc
    finally:
        client.close()


def fetch_x509_svid(spiffe_socket: str):
    """Return the workload's X.509 SVID (cert chain + private key)."""
    try:
        from spiffe.workloadapi.workload_api_client import WorkloadApiClient
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on extras
        raise IdentityError(
            "SPIFFE support is not installed (pip install agentnhi[spiffe])"
        ) from exc

    client = WorkloadApiClient(socket_path=spiffe_socket)
    try:
        return client.fetch_x509_svid()
    except Exception as exc:  # noqa: BLE001
        raise IdentityError(f"could not fetch X.509-SVID: {exc}") from exc
    finally:
        client.close()


def mtls_client_context(spiffe_socket: str, ca_cert_path: str | None = None) -> ssl.SSLContext:
    """Build an mTLS client context from the workload's X.509-SVID.

    The SVID is short-lived; callers that hold a long-lived context should
    rebuild it on rotation (or fetch per request).
    """
    svid = fetch_x509_svid(spiffe_socket)
    try:
        cert_pem = b"".join(_pem(c) for c in svid.cert_chain)
        key_pem = _private_key_pem(svid.private_key)
    except Exception as exc:  # noqa: BLE001
        raise IdentityError(f"could not serialise X.509-SVID: {exc}") from exc

    tmp = Path(tempfile.mkdtemp(prefix="agentnhi-svid-"))
    cert_file, key_file = tmp / "cert.pem", tmp / "key.pem"
    cert_file.write_bytes(cert_pem)
    key_file.write_bytes(key_pem)

    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    if ca_cert_path:
        ctx.load_verify_locations(ca_cert_path)
    ctx.load_cert_chain(certfile=str(cert_file), keyfile=str(key_file))
    return ctx


def _pem(cert) -> bytes:  # pragma: no cover - exercised against a live SPIRE
    from cryptography.hazmat.primitives import serialization

    return cert.public_bytes(serialization.Encoding.PEM)


def _private_key_pem(key) -> bytes:  # pragma: no cover - exercised against a live SPIRE
    from cryptography.hazmat.primitives import serialization

    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
