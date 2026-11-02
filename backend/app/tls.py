"""Local certificate authority and server certificate for HTTPS."""

from __future__ import annotations

import ipaddress
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from app.config import cert_dir, tls_hosts


def _ipv4_addresses() -> set[str]:
    found = {"127.0.0.1"}
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            found.add(info[4][0])
    except OSError:
        pass
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))
        found.add(probe.getsockname()[0])
        probe.close()
    except OSError:
        pass
    return found


def certificate_names() -> tuple[list[str], list[str]]:
    names = {"localhost"}
    ips = _ipv4_addresses()
    ips.add("::1")
    for item in tls_hosts():
        try:
            ips.add(str(ipaddress.ip_address(item)))
        except ValueError:
            names.add(item)
    return sorted(names), sorted(ips, key=str)


def cert_files() -> tuple[Path, Path]:
    folder = cert_dir()
    return folder / "server.pem", folder / "server-key.pem"


def ca_file() -> Path:
    return cert_dir() / "ca.pem"


def _hosts_stamp(names: list[str], ips: list[str]) -> str:
    return "\n".join([*(f"dns:{name}" for name in names), *(f"ip:{addr}" for addr in ips)])


def _write_key(path: Path, key: rsa.RSAPrivateKey) -> None:
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _load_or_create_ca(folder: Path) -> tuple[x509.Certificate, rsa.RSAPrivateKey]:
    ca_path = folder / "ca.pem"
    key_path = folder / "ca-key.pem"
    if ca_path.is_file() and key_path.is_file():
        cert = x509.load_pem_x509_certificate(ca_path.read_bytes())
        key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
        try:
            cert.extensions.get_extension_for_class(x509.SubjectKeyIdentifier)
            cert.extensions.get_extension_for_class(x509.AuthorityKeyIdentifier)
        except x509.ExtensionNotFound:
            cert = None
        if cert is not None and isinstance(key, rsa.RSAPrivateKey):
            return cert, key
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "EspressoLab Attendance Local CA")]))
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "EspressoLab Attendance Local CA")]))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), critical=False)
        .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True, content_commitment=False, key_encipherment=False, data_encipherment=False, key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
        .sign(key, hashes.SHA256())
    )
    ca_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    _write_key(key_path, key)
    return cert, key


def ensure_certs() -> tuple[Path, Path]:
    """Create or refresh the server certificate. Reuses the local CA so a trusted install stays valid."""
    folder = cert_dir()
    folder.mkdir(parents=True, exist_ok=True)
    names, ips = certificate_names()
    stamp_path = folder / "hosts.txt"
    wanted = _hosts_stamp(names, ips)
    cert_path, key_path = cert_files()
    if cert_path.is_file() and key_path.is_file() and ca_file().is_file() and stamp_path.is_file() and stamp_path.read_text(encoding="utf-8") == wanted:
        try:
            server = x509.load_pem_x509_certificate(cert_path.read_bytes())
            server.extensions.get_extension_for_class(x509.AuthorityKeyIdentifier)
            ca = x509.load_pem_x509_certificate(ca_file().read_bytes())
            ca.extensions.get_extension_for_class(x509.SubjectKeyIdentifier)
            return cert_path, key_path
        except (ValueError, x509.ExtensionNotFound):
            pass

    ca_cert, ca_key = _load_or_create_ca(folder)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    san = [x509.DNSName(name) for name in names]
    for addr in ips:
        san.append(x509.IPAddress(ipaddress.ip_address(addr)))
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, names[0])]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    _write_key(key_path, key)
    stamp_path.write_text(wanted, encoding="utf-8")
    return cert_path, key_path


if __name__ == "__main__":
    cert, key = ensure_certs()
    print(f"certificate {cert}")
    print(f"key {key}")
    print(f"certificate authority {ca_file()}")
