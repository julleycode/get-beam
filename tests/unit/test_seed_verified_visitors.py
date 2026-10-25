"""seed_verified_visitors: fail-closed local-DSN guard + emailable roster."""
import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest

from apps.api.services.identity_classification import is_emailable_identity

pytestmark = pytest.mark.unit

_PATH = Path(__file__).resolve().parents[2] / "scripts" / "seed_verified_visitors.py"
_spec = importlib.util.spec_from_file_location("seed_verified_visitors", _PATH)
seed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed)


@pytest.mark.parametrize("url", [
    "postgresql+asyncpg://u:p@localhost:5433/db",
    "postgresql+asyncpg://u:p@127.0.0.1:5433/db",
    "postgresql://u:p@[::1]:5433/db",
    "postgresql://u:p@host.docker.internal:5433/db",
])
def test_local_dsn_accepted(url):
    assert seed.is_local_db_url(url)
    seed._assert_local_dsn(url)


@pytest.mark.parametrize("url", [
    "postgresql+asyncpg://u:p@aws-1-ap-southeast-1.pooler.supabase.com:6543/postgres",
    "postgresql+asyncpg://u:p@db.hylcleqxlkdblibpdhhm.supabase.co:5432/postgres",
    "postgresql://u:p@localhost.evil.com/db",
    "not a url",
    "",
    None,
])
def test_remote_or_unparseable_dsn_rejected(url):
    assert not seed.is_local_db_url(url)
    with pytest.raises(seed.NonLocalDatabaseError):
        seed._assert_local_dsn(url)


def test_main_refuses_remote_with_zero_writes(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db.example.supabase.co/x")
    with patch.object(seed, "_run") as run, patch.object(seed.asyncio, "run") as arun:
        assert seed.main([]) == 2
    run.assert_not_called()
    arun.assert_not_called()


def test_main_refuses_when_env_unset(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with patch.object(seed.asyncio, "run") as arun:
        assert seed.main([]) == 2
    arun.assert_not_called()


def test_roster_is_five_emailable_fake_people():
    assert len(seed.ROSTER) == 5
    assert is_emailable_identity(seed.SEED_PROVIDER) is True
    assert seed.SEED_CONFIDENCE >= 0.9
    for p in seed.ROSTER:
        assert p["email"].rsplit("@", 1)[1] in {"example.com", "example.org", "example.net"}
        assert p["full_name"] and p["company_name"]
    seed._validate_roster()


def test_ids_deterministic_and_unique():
    ids = [seed.visitor_id_for(p["slug"]) for p in seed.ROSTER]
    assert ids == [seed.visitor_id_for(p["slug"]) for p in seed.ROSTER]
    assert len(set(ids)) == 5


def test_people_data_labs_provider_would_not_be_emailable():
    # Guards against copying scripts/seed.py's non-emailable provider.
    assert is_emailable_identity("people_data_labs") is False
