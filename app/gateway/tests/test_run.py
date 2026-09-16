"""The gateway must never serve an SVID the Workload API handed it half-spent.

The bug this guards (2026-09-16): the gateway restarted on a fixed 3300s timer
that assumed a fresh 1h SVID at startup, but SPIRE returns its *cached* copy,
which can be up to half-spent. The gateway then served an expired certificate
until the timer fired, and every agent->gateway handshake failed with
CERTIFICATE_VERIFY_FAILED — which looked like the model failing to pick a tool.
"""
from __future__ import annotations

import datetime
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from app.gateway.run import _restart_delay, _svid_expiry


def _cert(tmp_path: Path, not_after: datetime.datetime) -> Path:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "acme.com")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_after - datetime.timedelta(minutes=60))
        .not_valid_after(not_after)
        .sign(key, hashes.SHA256())
    )
    path = tmp_path / "cert.pem"
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return path


def test_svid_expiry_is_read_from_the_certificate(tmp_path):
    not_after = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=36)).replace(
        microsecond=0
    )
    assert abs(_svid_expiry(str(_cert(tmp_path, not_after))) - not_after.timestamp()) < 1


def test_restart_delay_never_outlives_the_certificate():
    # Half-spent SVID: 2160s of life, 120s margin. The old fixed 3300s timer
    # would have slept past expiry; the file is re-checked every minute instead.
    assert _restart_delay(2160, 120) == 60.0
    assert _restart_delay(170, 120) == 50.0
    assert _restart_delay(120, 120) == 0.0
