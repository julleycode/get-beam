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


# ── Phase 3: remote (prod demo) opt-in ─────────────────────────────────────

_REMOTE = "postgresql+asyncpg://admin:s3cretpw@aws-1-ap-southeast-1.pooler.supabase.com:6543/postgres"
_OWNER = __import__("uuid").UUID("11111111-2222-3333-4444-555555555555")
_OTHER = __import__("uuid").UUID("99999999-2222-3333-4444-555555555555")


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _RemoteSession(_FakeSession):
    """Answers user/site/count SELECTs; records every write statement."""

    def __init__(self, users=(_OWNER,), site_owner=None, child_count=3):
        super().__init__()
        self.users = list(users)
        self.site_owner = site_owner
        self.child_count = child_count
        self.statements: list = []
        self.began = 0

    def begin(self):
        self.began += 1
        return self

    async def scalar(self, stmt):
        sql = str(stmt)
        if "count(" in sql:
            return self.child_count
        if "FROM sites" in sql:
            if self.site_owner is None:
                return None
            from types import SimpleNamespace
            return SimpleNamespace(user_id=self.site_owner)
        return None

    async def execute(self, stmt):
        sql = str(stmt)
        if sql.startswith("SELECT") and "FROM users" in sql:
            return _Result(self.users)
        self.statements.append(stmt)
        await super().execute(stmt)

    @property
    def deletes(self):
        return [s for s in self.statements if str(s).startswith("DELETE")]


_FERNET_KEY = "A" * 43 + "="  # 32 zero-ish bytes, urlsafe-b64: a valid Fernet key


def _remote_main(monkeypatch, argv, session, pii=True, enc=None, fallback=""):
    import apps.api.models.database as database
    from apps.api.config import settings

    monkeypatch.setenv("DATABASE_URL", _REMOTE)
    monkeypatch.setattr(settings, "database_url", _REMOTE)
    monkeypatch.setattr(settings, "pii_hmac_key", "k" * 32 if pii else "")
    enc = pii if enc is None else enc
    if enc is True:
        enc = _FERNET_KEY
    monkeypatch.setattr(settings, "pii_encryption_key", enc or "")
    monkeypatch.setattr(settings, "encryption_key", fallback)
    with patch.object(database, "async_session", lambda: session):
        return seed.main(["--allow-remote", "--owner-email", "Owner@Example.com", *argv])


def _no_session():
    raise AssertionError("async_session must not be called")


# P3-G1
def test_p3_g1_nonlocal_without_allow_remote_refused(monkeypatch):
    import apps.api.models.database as database

    monkeypatch.setenv("DATABASE_URL", _REMOTE)
    with patch.object(database, "async_session", _no_session):
        assert seed.main(["--demo-company", "--yes"]) == 2


# P3-G2
@pytest.mark.parametrize("argv", [
    ["--allow-remote"],
    ["--allow-remote", "--owner-email", "a@b.com", "--user-id", str(_OWNER)],
    ["--owner-email", "a@b.com"],
])
def test_p3_g2_flag_combinations_refused(monkeypatch, argv):
    import apps.api.models.database as database

    monkeypatch.setenv("DATABASE_URL", _REMOTE)
    with patch.object(database, "async_session", _no_session):
        assert seed.main(argv) == 2


def test_p3_check_target_modes():
    assert seed.check_target(_REMOTE, True, "a@b.com", None) == "remote"
    assert seed.check_target("postgresql://u:p@localhost:5433/d", True, "a@b.com", None) == "remote"
    assert seed.check_target("postgresql://u:p@localhost:5433/d", False, None, None) == "local"
    with pytest.raises(seed.NonLocalDatabaseError):
        seed.check_target("not a url", True, "a@b.com", None)


# P3-G3 + P3-G4
def test_p3_g3_g4_remote_without_yes_is_redacted_dry_run(monkeypatch, capsys):
    s = _RemoteSession()
    assert _remote_main(monkeypatch, ["--demo-company"], s) == 0
    assert s.added == [] and s.statements == []
    out = capsys.readouterr().out
    assert "aws-1-ap-southeast-1.pooler.supabase.com" in out
    assert str(_OWNER) in out and seed.remote_site_id(_OWNER) in out
    for secret in ("s3cretpw", "admin", "6543", "postgres", "@example", "kkkk", "eeee"):
        assert secret not in out
    assert "DRY RUN" in out
    for t in ("visitors: 6", "identified_visitors: 6", "visitor_emails: 6",
              "enrichment_profiles: 6", "sites: 1"):
        assert t in out


def test_p3_dry_run_flag_overrides_yes(monkeypatch):
    s = _RemoteSession()
    assert _remote_main(monkeypatch, ["--yes", "--dry-run"], s) == 0
    assert s.added == [] and s.statements == []


# P3-G5
@pytest.mark.parametrize("users", [[], [_OWNER, _OTHER]])
def test_p3_g5_owner_must_match_exactly_one(monkeypatch, users):
    s = _RemoteSession(users=users)
    assert _remote_main(monkeypatch, ["--yes"], s) == 3
    assert s.added == [] and s.statements == []


def test_p3_g5_owner_lookup_is_case_insensitive_and_never_creates_user():
    import asyncio

    from apps.api.models.user import User

    s = _RemoteSession()
    seen = []
    orig = s.execute

    async def spy(stmt):
        seen.append(str(stmt.compile(compile_kwargs={"literal_binds": True})))
        return await orig(stmt)

    s.execute = spy
    assert asyncio.run(seed._resolve_owner_by_email(s, " Owner@Example.COM ")) == _OWNER
    assert "lower(users.email) = 'owner@example.com'" in seen[0]
    assert not any(isinstance(o, User) for o in s.added)


# P3-G6
def test_p3_g6_remote_site_id_shape():
    a, b = seed.remote_site_id(_OWNER), seed.remote_site_id(_OTHER)
    assert a == seed.remote_site_id(str(_OWNER)) and a != b
    assert a.startswith("beam_seed_verified_") and len(a) <= 50
    assert a != seed.SEED_SITE_ID
    assert seed.visitor_id_for("ava-chen", a) != seed.visitor_id_for("ava-chen")
    assert seed.visitor_id_for("ava-chen", a) != seed.visitor_id_for("ava-chen", b)


@pytest.mark.parametrize("argv", [["--yes"], ["--unseed", "--yes"]])
def test_p3_g6_existing_site_other_owner_refused(monkeypatch, argv):
    s = _RemoteSession(site_owner=_OTHER)
    assert _remote_main(monkeypatch, argv, s) == 4
    assert s.added == [] and s.statements == []


# P3-G7 + P3-G9
def test_p3_g7_g9_remote_seed_never_emailable_and_site_scoped(monkeypatch):
    from apps.api.models.site import Site
    from apps.api.models.visitor import IdentifiedVisitor

    s = _RemoteSession()
    assert _remote_main(monkeypatch, ["--demo-company", "--yes"], s) == 0
    site_id = seed.remote_site_id(_OWNER)
    idents = [o for o in s.added if isinstance(o, IdentifiedVisitor)]
    assert len(idents) == 6 and all(i.do_not_email is True for i in idents)
    sites = [o for o in s.added if isinstance(o, Site)]
    assert len(sites) == 1 and sites[0].hot_alert_enabled is False
    assert sites[0].user_id == _OWNER and sites[0].site_id == site_id
    assert sites[0].name == seed.SEED_SITE_NAME
    assert len(_visitors(s)) == 6
    assert all(o.site_id == site_id for o in s.added)
    allowed = {"sites", "visitors", "identified_visitors", "visitor_emails", "enrichment_profiles"}
    assert {o.__tablename__ for o in s.added} <= allowed
    for st in s.statements:
        assert st.table.name in allowed
    for forbidden in ("beam_identity_graph", "suppression", "api_usage", "usage", "credit"):
        assert not any(forbidden in str(st) for st in s.statements)


def test_p3_g7_existing_owned_site_not_recreated(monkeypatch):
    from apps.api.models.site import Site

    s = _RemoteSession(site_owner=_OWNER)
    assert _remote_main(monkeypatch, ["--yes"], s) == 0
    assert not any(isinstance(o, Site) for o in s.added)
    assert len(_visitors(s)) == 5


def test_p3_g7_local_seed_also_never_emailable():
    from apps.api.models.visitor import IdentifiedVisitor

    s = _run_fake(unseed=False, demo_company=True)
    assert all(o.do_not_email is True for o in s.added if isinstance(o, IdentifiedVisitor))


# P3-G8
def test_p3_g8_remote_unseed_deletes_whole_demo_site_only(monkeypatch, capsys):
    s = _RemoteSession(site_owner=_OWNER)
    assert _remote_main(monkeypatch, ["--unseed", "--yes"], s) == 0
    site_id = seed.remote_site_id(_OWNER)
    tables = [d.table.name for d in s.deletes]
    assert tables == ["enrichment_profiles", "visitor_emails", "identified_visitors",
                      "visitors", "events", "sites"]
    for d in s.deletes:
        params = d.compile().params
        assert site_id in params.values()
        assert seed.SEED_SITE_ID not in params.values()
    assert _OWNER in s.deletes[-1].compile().params.values()
    assert s.added == []
    assert "events: 3" in capsys.readouterr().out


def test_p3_g8_remote_unseed_without_yes_counts_only(monkeypatch, capsys):
    s = _RemoteSession(site_owner=_OWNER, child_count=7)
    assert _remote_main(monkeypatch, ["--unseed"], s) == 0
    assert s.statements == []
    out = capsys.readouterr().out
    assert "visitors: 7" in out and "DRY RUN" in out


# P3-G9 (local path too)
def test_p3_g9_local_seed_touches_only_seed_tables():
    s = _run_fake(unseed=False, demo_company=True)
    allowed = {"sites", "visitors", "identified_visitors", "visitor_emails", "enrichment_profiles"}
    assert {o.__tablename__ for o in s.added} <= allowed


# P3-G10
def test_p3_g10_missing_hmac_key_refused(monkeypatch, capsys):
    assert _remote_main(monkeypatch, ["--yes"], _no_session, pii=False, enc=True) == 5
    assert "PII_HMAC_KEY missing" in capsys.readouterr().err


@pytest.mark.parametrize("enc,fallback", [
    (False, ""),                 # no key at all
    (False, "not-a-fernet-key"), # fallback present but malformed
    ("e" * 32, ""),              # dedicated key malformed
])
def test_p3_g10_no_valid_pii_key_refused(monkeypatch, capsys, enc, fallback):
    assert _remote_main(monkeypatch, ["--yes"], _no_session, enc=enc, fallback=fallback) == 5
    assert "no valid Fernet PII key" in capsys.readouterr().err


def test_p3_g10_prod_shape_empty_pii_key_valid_fallback_proceeds(monkeypatch, capsys):
    """Prod 14-11-26: PII_ENCRYPTION_KEY empty, ENCRYPTION_KEY valid Fernet -> allowed."""
    s = _RemoteSession()
    assert _remote_main(monkeypatch, ["--demo-company"], s, enc=False,
                        fallback=_FERNET_KEY) == 0
    assert s.added == [] and s.statements == []
    assert "Refusing" not in capsys.readouterr().err


def test_effective_pii_key_valid():
    assert seed.effective_pii_key_valid("", _FERNET_KEY)
    assert seed.effective_pii_key_valid(_FERNET_KEY, "")
    assert not seed.effective_pii_key_valid("", "")
    assert not seed.effective_pii_key_valid("bad", _FERNET_KEY)  # dedicated key wins
