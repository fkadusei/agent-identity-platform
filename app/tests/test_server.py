"""Serving with SPIFFE mTLS (A): the certificate's lifetime, and who may connect.

The bug this guards (S15): a TLS server that keeps an expired certificate fails
every handshake, which looks like an outage rather than a rotated credential. The
deadline therefore comes from the certificate, not from a constant.

The second half is the control itself: a peer must present an SVID **issued by our
SPIRE**, not merely any certificate.
"""
from __future__ import annotations

import datetime
import socket
import ssl
import threading
import time
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from app.common.server import restart_delay, server_ssl_context, svid_expiry

SPIFFE_PREFIX = "spiffe://acme.com/ns/agent-platform/sa"


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _write(path: Path, certificate: x509.Certificate, key: ec.EllipticCurvePrivateKey) -> tuple[str, str]:
    path.mkdir(parents=True, exist_ok=True)
    cert_file, key_file = path / "cert.pem", path / "key.pem"
    cert_file.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return str(cert_file), str(key_file)


def _ca(name: str = "test-ca") -> tuple[ec.EllipticCurvePrivateKey, x509.Certificate]:
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(_now() - datetime.timedelta(minutes=1))
        .not_valid_after(_now() + datetime.timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        # Strict X.509 (the default verify flags in modern Python) wants a CA that
        # says it may sign certificates; SPIRE's CA carries the same extensions.
        .add_extension(
            x509.KeyUsage(
                digital_signature=False, content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False, key_cert_sign=True,
                crl_sign=True, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    return key, certificate


def _leaf(
    ca_key: ec.EllipticCurvePrivateKey,
    ca_cert: x509.Certificate,
    *,
    name: str,
    spiffe_id: str,
    expires_in: datetime.timedelta = datetime.timedelta(hours=1),
) -> tuple[ec.EllipticCurvePrivateKey, x509.Certificate]:
    key = ec.generate_private_key(ec.SECP256R1())
    certificate = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(_now() - datetime.timedelta(minutes=1))
        .not_valid_after(_now() + expires_in)
        # A SPIFFE identity is a URI SAN, which is why hostname checks are off.
        .add_extension(
            x509.SubjectAlternativeName([x509.UniformResourceIdentifier(spiffe_id)]),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False, key_cert_sign=False,
                crl_sign=False, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage(
                [x509.oid.ExtendedKeyUsageOID.SERVER_AUTH, x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH]
            ),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_cert.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    return key, certificate


# --- the deadline comes from the certificate ---------------------------------


def test_svid_expiry_is_read_from_the_certificate(tmp_path):
    ca_key, ca_cert = _ca()
    expires_in = datetime.timedelta(minutes=36)
    key, cert = _leaf(ca_key, ca_cert, name="agent", spiffe_id=f"{SPIFFE_PREFIX}/agent", expires_in=expires_in)
    cert_file, _ = _write(tmp_path / "svid", cert, key)

    expected = (cert.not_valid_after_utc).timestamp()
    assert abs(svid_expiry(cert_file) - expected) < 1
    # ...and it is the *certificate's* answer, not the TTL we passed in.
    assert svid_expiry(cert_file) - time.time() < expires_in.total_seconds()


def test_restart_delay_never_outlives_the_certificate():
    # Half-spent SVID: 2160s of life left, 120s margin -> re-check every minute.
    assert restart_delay(2160, 120) == 60.0
    assert restart_delay(170, 120) == 50.0
    assert restart_delay(120, 120) == 0.0


def test_health_listener_answers_liveness_and_nothing_else():
    """The kubelet's listener must not be a second way into the service.

    It exists because a probe cannot present an SVID, so a mTLS-only service would
    otherwise be checked by "is the socket open?" — which a hung process answers.
    The price of a plaintext listener is that it must expose *only* liveness: on the
    gateway, serving the app's routes there would hand the model endpoint to
    anything that can reach the pod (S16).
    """
    from fastapi.testclient import TestClient

    from app.common.server import health_app

    client = TestClient(health_app())
    assert client.get("/healthz").json() == {"ok": True}
    # Not the gateway's route, not the api's, not a catch-all.
    assert client.post("/v1/chat/completions", json={}).status_code == 404
    assert client.get("/tasks").status_code == 404
    assert client.get("/metrics").status_code == 404


# --- who may connect ---------------------------------------------------------


def _serve_until(context: ssl.SSLContext, expected: int, port: list, accepted: list) -> None:
    """Accept connections, wrapping each in TLS; count the ones that complete."""
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(8)
    port.append(server.getsockname()[1])
    done = 0
    for _ in range(expected):
        try:
            connection, _address = server.accept()
        except OSError:
            break
        try:
            with context.wrap_socket(connection, server_side=True) as tls:
                tls.settimeout(5)
                tls.recv(1)
            done += 1
        except Exception:  # noqa: BLE001 - a rejected handshake is the point
            pass
    accepted.append(done)
    server.close()


def _client_context(ca_cert: Path, cert_file: str, key_file: str) -> ssl.SSLContext:
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(ca_cert))
    context.check_hostname = False
    context.load_cert_chain(certfile=cert_file, keyfile=key_file)
    return context


def _dial(port: int, context: ssl.SSLContext) -> None:
    raw = socket.create_connection(("127.0.0.1", port), timeout=5)
    with context.wrap_socket(raw, server_hostname="ignored") as tls:
        tls.settimeout(5)
        tls.sendall(b"x")
        # Read so a fatal alert the server sends is seen here rather than left
        # unread; the server closes the connection the other way.
        try:
            tls.recv(1)
        except (ssl.SSLError, ConnectionResetError, OSError):
            raise


def test_a_peer_issued_by_our_spire_is_accepted_and_a_foreign_one_is_not(tmp_path):
    """The control, tested with a real handshake rather than a stub.

    Two clients dial the same listener: one holds an SVID from our CA, the other
    holds a perfectly valid certificate from a *different* CA. Only the first
    completes — which is what "only a workload SPIRE has issued can connect" means.
    """
    ours_key, ours_cert = _ca("our-spire")
    theirs_key, theirs_cert = _ca("someone-else")
    bundle = tmp_path / "bundle.crt"
    bundle.write_bytes(ours_cert.public_bytes(serialization.Encoding.PEM))

    server_key, server_cert = _leaf(
        ours_key, ours_cert, name="tools", spiffe_id=f"{SPIFFE_PREFIX}/tools"
    )
    cert_file, key_file = _write(tmp_path / "tools", server_cert, server_key)
    context = server_ssl_context(cert_file, key_file, str(bundle))
    assert context.verify_mode == ssl.CERT_REQUIRED

    good_key, good_cert = _leaf(ours_key, ours_cert, name="agent", spiffe_id=f"{SPIFFE_PREFIX}/agent")
    good = _client_context(bundle, *_write(tmp_path / "agent", good_cert, good_key))

    bad_key, bad_cert = _leaf(theirs_key, theirs_cert, name="rogue", spiffe_id=f"{SPIFFE_PREFIX}/rogue")
    bad = _client_context(bundle, *_write(tmp_path / "rogue", bad_cert, bad_key))

    port: list[int] = []
    accepted: list[int] = []
    thread = threading.Thread(target=_serve_until, args=(context, 2, port, accepted), daemon=True)
    thread.start()
    while not port:
        time.sleep(0.01)

    _dial(port[0], good)
    # A refused client may see the alert on either side of the handshake, so the
    # assertion is the one signal that cannot be ambiguous: how many connections
    # the *server* was willing to complete.
    try:
        _dial(port[0], bad)
    except (ssl.SSLError, ConnectionResetError, OSError):
        pass

    thread.join(timeout=10)
    assert accepted == [1], "only the workload SPIRE issued should have connected"
