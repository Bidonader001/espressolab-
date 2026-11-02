"""HTTPS redirect, HSTS, and local certificates."""

from __future__ import annotations

from datetime import datetime, timezone

from cryptography import x509


def test_http_redirects_to_https_except_iclock(client, monkeypatch):
    monkeypatch.setenv("FORCE_HTTPS", "1")
    monkeypatch.setenv("HTTPS_PORT", "8443")
    moved = client.get("/api/v1/health", follow_redirects=False)
    assert moved.status_code == 308
    assert moved.headers["location"] == "https://testserver:8443/api/v1/health"
    iclock = client.get("/iclock/cdata", follow_redirects=False)
    assert iclock.status_code == 404


def test_https_responses_send_hsts(client):
    secure = client.get("/api/v1/health", headers={"X-Forwarded-Proto": "https"})
    assert secure.status_code == 200
    assert secure.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"
    assert "upgrade-insecure-requests" in secure.headers["content-security-policy"]
    plain = client.get("/api/v1/health")
    assert plain.status_code == 200
    assert "strict-transport-security" not in plain.headers


def test_local_certificate_covers_localhost(tmp_path, monkeypatch):
    monkeypatch.setenv("TLS_CERT_DIR", str(tmp_path))
    monkeypatch.setenv("TLS_HOSTS", "attendance.local,10.0.0.8")
    from app.tls import ca_file, certificate_names, ensure_certs

    cert_path, key_path = ensure_certs()
    assert cert_path.is_file() and key_path.is_file() and ca_file().is_file()
    names, ips = certificate_names()
    assert "localhost" in names and "attendance.local" in names
    assert "127.0.0.1" in ips and "10.0.0.8" in ips
    parsed = x509.load_pem_x509_certificate(cert_path.read_bytes())
    san = parsed.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    dns = set(san.get_values_for_type(x509.DNSName))
    assert {"localhost", "attendance.local"} <= dns
    assert parsed.not_valid_after_utc > datetime.now(timezone.utc)
    parsed.extensions.get_extension_for_class(x509.AuthorityKeyIdentifier)
    ca = x509.load_pem_x509_certificate(ca_file().read_bytes())
    ca.extensions.get_extension_for_class(x509.SubjectKeyIdentifier)


def test_production_cors_must_be_https(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_KEY", "x" * 48)
    monkeypatch.setenv("FERNET_KEY", "k" * 10)
    monkeypatch.setenv("ADMIN_PASSWORD", "a-long-private-passphrase-2026")
    monkeypatch.setenv("ALLOW_SIMULATOR", "0")
    monkeypatch.setenv("CORS_ORIGINS", "http://attendance.example.com")
    from app.config import production_problems

    text = " | ".join(production_problems())
    assert "https://" in text
    monkeypatch.setenv("CORS_ORIGINS", "https://attendance.example.com")
    assert production_problems() == []
