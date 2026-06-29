"""Phase 7: secret/config hardening.

- validate_production runs for production AND any unrecognized app_env (a typo
  can't silently disable the secret checks).
- the PII / known-contacts blind-index keys never fall back to a hardcoded
  constant — a missing key raises instead (a known key = public membership oracle).
"""

import pytest

import apps.api.services.known_hash as known_hash
import apps.api.services.pii_crypto as pii_crypto
from apps.api.config import Settings


def _settings(**overrides) -> Settings:
    s = Settings()
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


class TestValidateProduction:
    def test_unknown_env_is_strict(self):
        s = _settings(app_env="staging", app_secret_key="strong",
                      token_encryption_key="tok", encryption_key="")
        with pytest.raises(RuntimeError):
            s.validate_production()

    def test_typo_env_is_strict(self):
        s = _settings(app_env="produciton", app_secret_key="change-me-in-production",
                      token_encryption_key="", encryption_key="")
        with pytest.raises(RuntimeError):
            s.validate_production()

    def test_development_is_exempt(self):
        s = _settings(app_env="development", app_secret_key="change-me-in-production",
                      encryption_key="")
        s.validate_production()  # must NOT raise

    def test_production_ok_when_keys_set(self):
        s = _settings(app_env="production", app_secret_key="strong",
                      token_encryption_key="tok", encryption_key="enc")
        s.validate_production()  # must NOT raise


class TestBlindIndexKey:
    def test_pii_hash_raises_without_any_key(self, monkeypatch):
        monkeypatch.setattr(pii_crypto.settings, "pii_hmac_key", "")
        monkeypatch.setattr(pii_crypto.settings, "encryption_key", "")
        with pytest.raises(RuntimeError):
            pii_crypto.email_hash("a@b.com")

    def test_pii_hash_uses_encryption_key(self, monkeypatch):
        monkeypatch.setattr(pii_crypto.settings, "pii_hmac_key", "")
        monkeypatch.setattr(pii_crypto.settings, "encryption_key", "some-real-key")
        digest = pii_crypto.email_hash("a@b.com")
        assert isinstance(digest, str) and len(digest) == 64

    def test_known_hash_raises_without_any_key(self, monkeypatch):
        monkeypatch.setattr(known_hash.settings, "pii_hmac_key", "")
        monkeypatch.setattr(known_hash.settings, "encryption_key", "")
        with pytest.raises(RuntimeError):
            known_hash.email_hash("a@b.com")
