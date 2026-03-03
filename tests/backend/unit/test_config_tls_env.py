import os

from config import _sanitize_tls_env


def test_sanitize_tls_env_unsets_invalid_paths(monkeypatch):
    bad = "/tmp/definitely-missing-ca.pem"
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", bad)
    monkeypatch.setenv("SSL_CERT_FILE", bad)
    monkeypatch.setenv("CURL_CA_BUNDLE", bad)

    _sanitize_tls_env()

    assert "REQUESTS_CA_BUNDLE" not in os.environ
    assert "SSL_CERT_FILE" not in os.environ
    assert "CURL_CA_BUNDLE" not in os.environ
