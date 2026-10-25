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


# ── --demo-company (TinyFish demo row) ─────────────────────────────────────


class _FakeSession:
    """Captures add()/execute() so _run can be exercised without a database."""

    def __init__(self, site_exists: bool = True):
        self.added: list = []
        self.deleted_ids: list[set[str]] = []
        self._site_exists = site_exists

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def begin(self):
        return self

    def add(self, obj):
        self.added.append(obj)

    async def scalar(self, _stmt):
        return object() if self._site_exists else None

    async def execute(self, stmt):
        params = stmt.compile().params
        for v in params.values():
            if isinstance(v, (list, tuple)):
                self.deleted_ids.append(set(v))


def _run_fake(**kw):
    import asyncio

    import apps.api.models.database as database

    session = _FakeSession()
    with patch.object(database, "async_session", lambda: session):
        assert asyncio.run(seed._run(None, False, **kw)) == 0
    return session


def _visitors(session):
    from apps.api.models.visitor import Visitor

    return [o for o in session.added if isinstance(o, Visitor)]


def test_default_run_seeds_exactly_five():
    s = _run_fake(unseed=False)
    assert len(_visitors(s)) == 5
    assert seed.visitor_id_for("demo-visitor") not in {v.visitor_id for v in _visitors(s)}


def test_demo_company_seeds_sixth_stripe_row_without_web_key():
    from apps.api.models.enrichment import EnrichmentProfile
    from apps.api.models.visitor import IdentifiedVisitor

    s = _run_fake(unseed=False, demo_company=True)
    demo_id = seed.visitor_id_for("demo-visitor")
    assert len(_visitors(s)) == 6
    prof = next(o for o in s.added if isinstance(o, EnrichmentProfile) and o.visitor_id == demo_id)
    assert prof.company_name == "Stripe" and prof.job_title == "Head of Partnerships"
    assert "web" not in (prof.social_context or {})
    ident = next(o for o in s.added if isinstance(o, IdentifiedVisitor) and o.visitor_id == demo_id)
    assert ident.full_name == "Demo Visitor" and ident.city == "San Francisco"
    assert ident.email.endswith("@example.com")


def test_demo_company_idempotent_delete_then_insert():
    a = _run_fake(unseed=False, demo_company=True)
    b = _run_fake(unseed=False, demo_company=True)
    ids_a = sorted(v.visitor_id for v in _visitors(a))
    assert ids_a == sorted(v.visitor_id for v in _visitors(b))
    # every inserted id is deleted first in the same transaction
    assert all(set(ids_a) <= d for d in a.deleted_ids) and a.deleted_ids


def test_unseed_removes_demo_row_even_without_flag():
    s = _run_fake(unseed=True)
    assert _visitors(s) == []
    assert any(seed.visitor_id_for("demo-visitor") in d for d in s.deleted_ids)


def test_demo_person_passes_domain_allow_list():
    assert seed.DEMO_PERSON["email"].rsplit("@", 1)[1] in seed.ALLOWED_EMAIL_DOMAINS
    seed._validate_roster()
    assert len(seed.roster_for()) == 5 and len(seed.roster_for(demo_company=True)) == 6
