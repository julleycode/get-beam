"""Unit tests for the social-resolution pipeline orchestrator (no DB/network).

Covers stage ordering, the paid-fallback threshold + budget guard, the
social_context read-modify-write (preserving deep_research), and the Gemini seed.
"""

import pytest

from apps.api.services import social_resolver as res
from apps.api.services.osint_scanner import OsintAccount


class _FakeDB:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _FakeEnricher:
    """Records the osint_seed deep_research was called with."""
    last_seed = None

    def __init__(self, db):
        self.db = db

    async def enrich_tier1(self, visitor, identified):
        return None

    async def deep_research(self, visitor, identified, profile, osint_seed=None):
        _FakeEnricher.last_seed = osint_seed
        return {"status": "enriched"}


def _profile_acc(site, engine="maigret", username="jdoe", name="John Doe", cand_source="name"):
    """A maigret-style profile. By default its extracted `name` matches the test
    full_name ("John Doe") → identity-verified → confirmed."""
    extra = {"username": username, "cand_source": cand_source}
    if name:
        extra["name"] = name
    return OsintAccount(site, "social", f"https://{site.lower()}.com/{username}",
                        "profile", "likely", engine, extra)


class _Knobs:
    def __init__(self):
        self.osint_accounts = []
        self.maigret = []
        self.rules = []
        self.paid = []
        self.paid_configured = False
        self.paid_budget_left = True
        self.paid_called = False
        self.paid_incr = 0


@pytest.fixture
def wired(monkeypatch):
    """Wire the pipeline with controllable stubs. Returns a _Knobs state object."""
    k = _Knobs()

    async def fake_osint(email):
        return {"status": "complete", "accounts": [a.to_dict() for a in k.osint_accounts],
                "engines": ["user-scanner"]}

    async def fake_maigret(cands, **kw):
        return list(k.maigret)

    async def fake_rules(cands, **kw):
        return list(k.rules)

    async def fake_paid(email):
        k.paid_called = True
        return {"used": True, "provider": "osint-industries",
                "accounts": [a.to_dict() for a in k.paid], "found": len(k.paid),
                "cached": False, "error": None}

    async def fake_budget_left(site_id):
        return k.paid_budget_left

    async def fake_incr(site_id):
        k.paid_incr += 1

    monkeypatch.setattr(res, "run_osint_scan", fake_osint)
    monkeypatch.setattr(res.maigret_engine, "search_usernames", fake_maigret)
    monkeypatch.setattr(res.maigret_engine, "is_available", lambda: True)
    monkeypatch.setattr(res, "resolve_via_rules", fake_rules)
    monkeypatch.setattr(res.paid_osint, "lookup", fake_paid)
    monkeypatch.setattr(res.paid_osint, "is_configured", lambda: k.paid_configured)
    monkeypatch.setattr(res, "osint_paid_budget_left", fake_budget_left)
    monkeypatch.setattr(res, "increment_osint_paid_usage", fake_incr)
    monkeypatch.setattr(res, "Enricher", _FakeEnricher)
    monkeypatch.setattr(res.settings, "osint_engines", "user-scanner,holehe,maigret")
    monkeypatch.setattr(res.settings, "osint_paid_min_profiles", 1)
    monkeypatch.setattr(res.settings, "gemini_api_key", "")  # skip gemini unless a test enables
    return k


def _run(profile_social=None, linkedin_url=None, twitter_handle=None, github_url=None):
    db = _FakeDB()
    visitor = _Obj(site_id="s1", visitor_id="v1")
    identified = _Obj(email="jdoe@example.com", full_name="John Doe")
    profile = _Obj(social_context=profile_social, linkedin_url=linkedin_url,
                   twitter_handle=twitter_handle, github_url=github_url)
    return db, visitor, identified, profile


@pytest.mark.asyncio
async def test_free_profiles_skip_paid(wired):
    wired.maigret = [_profile_acc("GitHub"), _profile_acc("Instagram")]
    wired.paid_configured = True
    db, v, i, p = _run()
    out = await res.resolve_social(db, visitor=v, identified=i, profile=p)
    assert out["status"] == "complete"
    assert out["profiles"] == 2
    assert out["paid_used"] is False
    assert wired.paid_called is False  # >= min profiles → no paid
    # persisted social_resolution + osint_scan
    sc = p.social_context
    assert sc["social_resolution"]["summary"]["profile_count"] == 2
    assert "osint_scan" in sc


@pytest.mark.asyncio
async def test_empty_free_triggers_paid(wired):
    wired.maigret = []
    wired.rules = []
    wired.paid_configured = True
    wired.paid = [_profile_acc("Telegram", engine="osint-industries", username="jd")]
    db, v, i, p = _run()
    out = await res.resolve_social(db, visitor=v, identified=i, profile=p)
    assert wired.paid_called is True
    assert wired.paid_incr == 1
    assert out["paid_used"] is True
    assert out["profiles"] == 1
    assert "paid" in p.social_context["social_resolution"]["stages_run"]


@pytest.mark.asyncio
async def test_paid_budget_exhausted_skips_paid(wired):
    wired.paid_configured = True
    wired.paid_budget_left = False  # over budget
    db, v, i, p = _run()
    out = await res.resolve_social(db, visitor=v, identified=i, profile=p)
    assert wired.paid_called is False
    assert out["paid_used"] is False
    paid = p.social_context["social_resolution"]["paid"]
    assert paid["error"] == "daily paid budget reached"


@pytest.mark.asyncio
async def test_paid_not_configured_skips_paid(wired):
    wired.paid_configured = False
    db, v, i, p = _run()
    out = await res.resolve_social(db, visitor=v, identified=i, profile=p)
    assert wired.paid_called is False
    assert out["paid_used"] is False


@pytest.mark.asyncio
async def test_preserves_deep_research_and_seeds_gemini(wired):
    wired.maigret = [_profile_acc("GitHub")]
    monkeypatch_seed = {"deep_research": "OLD NARRATIVE", "researched_at": "2026-01-01"}
    res.settings.gemini_api_key = "fake-key"  # enable gemini stage
    db, v, i, p = _run(profile_social=dict(monkeypatch_seed))
    await res.resolve_social(db, visitor=v, identified=i, profile=p)
    # deep_research preserved through the social_resolution write
    assert p.social_context.get("deep_research") == "OLD NARRATIVE"
    # gemini was seeded with both osint_scan and social_resolution
    seed = _FakeEnricher.last_seed
    assert seed is not None
    assert "osint_scan" in seed and "social_resolution" in seed


@pytest.mark.asyncio
async def test_alias_merge_and_name_confirms(wired):
    # Maigret "Twitter" (parsed name matches) + rule-base "X" → same platform after
    # aliasing → merge into ONE profile, confirmed via NAME match (not engine count).
    wired.maigret = [_profile_acc("Twitter", engine="maigret", username="jdoe")]
    wired.rules = [OsintAccount("X", "social", "https://x.com/jdoe", "profile",
                                "likely", "rule-base", {"username": "jdoe"})]
    db, v, i, p = _run()
    await res.resolve_social(db, visitor=v, identified=i, profile=p)
    profiles = p.social_context["social_resolution"]["profiles"]
    assert len(profiles) == 1
    assert profiles[0]["confidence"] == "confirmed"
    assert "maigret" in profiles[0]["source_engine"]
    assert "rule-base" in profiles[0]["source_engine"]


@pytest.mark.asyncio
async def test_unverified_guess_is_filtered(wired):
    # A profile whose extracted name does NOT match the person, on a site the email
    # is NOT registered on → guess → kept out of `profiles`, parked in `guesses`.
    wired.maigret = [_profile_acc("GitHub", username="someoneelse", name="Someone Else")]
    db, v, i, p = _run()
    out = await res.resolve_social(db, visitor=v, identified=i, profile=p)
    sr_blob = p.social_context["social_resolution"]
    assert sr_blob["profiles"] == []          # not shown as a real profile
    assert len(sr_blob["guesses"]) == 1       # collapsed under guesses
    assert sr_blob["guesses"][0]["confidence"] == "guess"
    assert out["confirmed"] == 0


@pytest.mark.asyncio
async def test_pdl_handle_is_confirmed(wired):
    # PDL wrote a LinkedIn URL to the profile (email-keyed) → confirmed profile,
    # no guessing needed.
    db, v, i, p = _run(linkedin_url="https://www.linkedin.com/in/nathan-nguyennhat/")
    await res.resolve_social(db, visitor=v, identified=i, profile=p)
    profiles = p.social_context["social_resolution"]["profiles"]
    li = [a for a in profiles if a["site_name"] == "LinkedIn"]
    assert len(li) == 1
    assert li[0]["confidence"] == "confirmed"
    assert li[0]["source_engine"] == "pdl"


@pytest.mark.asyncio
async def test_name_match_confirms(wired):
    # Maigret parsed a real name that matches the target → confirmed even though it
    # came from a guessed (name-derived) username.
    wired.maigret = [_profile_acc("GitHub", username="johndoe", name="John Doe")]
    db, v, i, p = _run()
    await res.resolve_social(db, visitor=v, identified=i, profile=p)
    prof = p.social_context["social_resolution"]["profiles"][0]
    assert prof["confidence"] == "confirmed"


@pytest.mark.asyncio
async def test_site_overlap_is_likely(wired):
    # Profile on a site the email IS registered on, but no name match → "likely"
    # (they use the site; the handle isn't identity-verified).
    wired.osint_accounts = [
        OsintAccount("GitHub", "dev", "https://github.com", "registered",
                     "confirmed", "holehe", {}),
    ]
    wired.maigret = [_profile_acc("GitHub", username="ghuser", name=None)]
    db, v, i, p = _run()
    await res.resolve_social(db, visitor=v, identified=i, profile=p)
    profs = p.social_context["social_resolution"]["profiles"]
    gh = [a for a in profs if a["site_name"] == "GitHub"]
    assert gh and gh[0]["confidence"] == "likely"


def test_default_engines_include_maigret():
    """The shipped code default must enable maigret so the username stage runs
    without an operator manually setting OSINT_ENGINES (prod was patched via env;
    the code default should match). Reads the class default — immune to env."""
    from apps.api.config import Settings

    assert "maigret" in Settings.model_fields["osint_engines"].default


@pytest.mark.asyncio
async def test_maigret_stage_runs_with_default(wired, monkeypatch):
    """With the genuine config default (now includes maigret), the Maigret
    username stage runs — no env-only enablement needed."""
    from apps.api.config import Settings

    monkeypatch.setattr(
        res.settings, "osint_engines",
        Settings.model_fields["osint_engines"].default,
    )
    wired.maigret = [_profile_acc("GitHub")]
    db, v, i, p = _run()
    out = await res.resolve_social(db, visitor=v, identified=i, profile=p)
    assert "maigret" in p.social_context["social_resolution"]["stages_run"]
    assert out["profiles"] == 1


@pytest.mark.asyncio
async def test_no_email_returns_not_identified(wired):
    db = _FakeDB()
    v = _Obj(site_id="s1", visitor_id="v1")
    i = _Obj(email="", full_name=None)
    p = _Obj(social_context=None, twitter_handle=None, github_url=None)
    out = await res.resolve_social(db, visitor=v, identified=i, profile=p)
    assert out["status"] == "not_identified"
