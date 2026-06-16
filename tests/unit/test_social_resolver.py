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
    # Two STRONG (confirmed) free profiles → paid fallback skipped. Each carries 2
    # signals: independent name match + known handle → confirmed under the ≥2-signal
    # rule (a single name match alone would only be "likely" and would trip paid).
    wired.maigret = [
        _profile_acc("GitHub", cand_source="known"),
        _profile_acc("Instagram", cand_source="known"),
    ]
    wired.paid_configured = True
    db, v, i, p = _run()
    out = await res.resolve_social(db, visitor=v, identified=i, profile=p)
    assert out["status"] == "complete"
    assert out["profiles"] == 2
    assert out["confirmed"] == 2  # ≥2 signals each → confirmed → enough → no paid
    assert out["paid_used"] is False
    assert wired.paid_called is False  # >= min CONFIRMED profiles → no paid
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
    # Maigret "Twitter" + rule-base "X" → same platform after aliasing → merge into
    # ONE profile. Confirmed via TWO signals (independent name match + known handle),
    # per the ≥2-signal rule — not via engine count.
    wired.maigret = [_profile_acc("Twitter", engine="maigret", username="jdoe",
                                  cand_source="known")]
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
async def test_name_match_plus_probe_confirms(wired):
    # TWO independent signals → confirmed: (a) maigret parsed a real name matching the
    # target, INDEPENDENT of the handle "jd_codes" (not echoed/circular), AND (b) the
    # free email-probe "user-scanner" surfaced this same handle. Either alone is only
    # "likely"; together they reach confirmed under the ≥2-signal rule.
    wired.maigret = [_profile_acc("GitHub", engine="user-scanner",
                                  username="jd_codes", name="John Doe",
                                  cand_source="name")]
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


# ── Regression: echoed-handle circular confirmation (the wrong-person bug) ──
# A maigret hit whose parsed "name" is just the handle we searched (and the handle
# was derived from the target's own name/email) is circular — NOT independent
# identity evidence. It must never reach "confirmed". Real case: visitor "Ahmad
# Syamil" / ahmads@starhub.com → guessed handles "ahmads" / "syamilahmad" found on
# random sites whose channel name echoes the handle.

def _maigret_echo(username: str):
    """A maigret profile whose parsed display name == the searched username."""
    return OsintAccount(
        "YouTube", "social", f"https://youtube.com/@{username}", "profile",
        "likely", "maigret",
        {"name": username, "username": username, "parsed": True},
    )


def test_echoed_handle_ahmads_not_confirmed():
    # Echoed name → no name signal; maigret-only, not registered, not known → 0
    # signals → "guess" (and definitely NOT confirmed).
    acc = _maigret_echo("ahmads")
    assert res._classify(acc, "Ahmad Syamil", set()) == "guess"


def test_echoed_handle_syamilahmad_not_confirmed():
    acc = _maigret_echo("syamilahmad")
    assert res._classify(acc, "Ahmad Syamil", set()) == "guess"


def test_is_echoed_handle_helper():
    # exact / containment both count as echoed (circular)
    assert res._is_echoed_handle("ahmads", "ahmads") is True
    assert res._is_echoed_handle("Ahmad S", "ahmads") is True   # strips to "ahmads" == "ahmads"
    assert res._is_echoed_handle("syamilahmad", "syamilahmad") is True
    # an INDEPENDENT real name is not an echo
    assert res._is_echoed_handle("Nathan Adams", "nadams123") is False
    # empty / missing → not an echo (can't decide → don't suppress)
    assert res._is_echoed_handle(None, "ahmads") is False
    assert res._is_echoed_handle("ahmads", None) is False


# ── Regression: adult/NSFW sites never surface (legal/defamation risk) ──

def test_is_adult_helper():
    assert res._is_adult("OnlyFans") is True
    assert res._is_adult("onlyfans") is True
    assert res._is_adult("Pornhub") is True
    assert res._is_adult("GitHub") is False
    assert res._is_adult(None) is False


@pytest.mark.asyncio
async def test_adult_site_dropped_from_output(wired):
    # An OnlyFans username collision (even if it would otherwise be surfaced) is
    # excluded from BOTH profiles and guesses, and counted in summary.hidden_adult.
    wired.maigret = [
        OsintAccount("OnlyFans", "social", "https://onlyfans.com/syamilahmad",
                     "profile", "likely", "maigret",
                     {"name": "Syamil Ahmad", "username": "syamilahmad"}),
        _profile_acc("GitHub", username="jd_codes", name="John Doe"),  # legit, kept
    ]
    db, v, i, p = _run()
    await res.resolve_social(db, visitor=v, identified=i, profile=p)
    sr = p.social_context["social_resolution"]
    sites_shown = {a["site_name"] for a in sr["profiles"]} | {
        a["site_name"] for a in sr["guesses"]
    }
    assert "OnlyFans" not in sites_shown          # dropped everywhere
    assert "GitHub" in sites_shown                # legit profile survives
    assert sr["summary"]["hidden_adult"] == 1


# ── Phase 2: signal-counting _classify (≥2 independent signals → confirmed) ──
# Gold sources confirm alone; everything else needs ≥2 corroborating signals. This
# stops two real people who share a NAME from cross-confirming, and stops one noisy
# free email-probe hit from auto-confirming.


def test_gold_pdl_source_confirmed_alone():
    # PDL enrichment is identity-grade (email-keyed, low false-positive) → confirmed
    # on its own, no second signal required.
    acc = OsintAccount("LinkedIn", "professional",
                       "https://linkedin.com/in/nathan", "profile",
                       "likely", "pdl", {"username": "nathan"})
    assert res._classify(acc, "Nathan Adams", set()) == "confirmed"


def test_gold_osint_industries_source_confirmed_alone():
    # Paid OSINT Industries is identity-grade → confirmed on its own.
    acc = OsintAccount("Telegram", "social", "https://t.me/nathan", "profile",
                       "likely", "osint-industries", {"username": "nathan"})
    assert res._classify(acc, "Nathan Adams", set()) == "confirmed"


def test_email_probe_alone_is_likely_not_confirmed():
    # A SINGLE free email-probe hit (user-scanner) is strong but noisy → ONE signal
    # → "likely", NOT auto-confirmed. (Was "confirmed" in Phase 1; downgraded here.)
    acc = OsintAccount("Spotify", "music", "https://spotify.com/u/ahmads", "profile",
                       "likely", "user-scanner", {"username": "ahmads"})
    assert res._classify(acc, "Ahmad Syamil", set()) == "likely"


def test_email_probe_plus_second_signal_confirms():
    # user-scanner (probe signal) + the email IS registered on this same site (2nd
    # signal) → 2 signals → confirmed.
    acc = OsintAccount("GitHub", "dev", "https://github.com/ahmads", "profile",
                       "likely", "user-scanner", {"username": "ahmads"})
    assert res._classify(acc, "Ahmad Syamil", {"github"}) == "confirmed"


def test_same_real_name_collision_is_likely_not_confirmed():
    # PHASE-2 WIN: two real people share the real name "Nathan Adams". An independent
    # name match is the ONLY signal (maigret, NOT a registered site, NOT a known
    # handle, NOT a probe) → exactly 1 signal → "likely", NOT confirmed. This is what
    # stops a same-named stranger's profile from cross-confirming as the target.
    acc = OsintAccount("GitHub", "dev", "https://github.com/nadams123", "profile",
                       "likely", "maigret",
                       {"name": "Nathan Adams", "username": "nadams123", "parsed": True})
    assert res._classify(acc, "Nathan Adams", set()) == "likely"


def test_two_signals_name_plus_registered_confirms():
    # Independent name match + email registered on this site → 2 signals → confirmed.
    acc = OsintAccount("GitHub", "dev", "https://github.com/nadams123", "profile",
                       "likely", "maigret",
                       {"name": "Nathan Adams", "username": "nadams123"})
    assert res._classify(acc, "Nathan Adams", {"github"}) == "confirmed"


def test_two_signals_known_plus_registered_confirms():
    # Known/verified handle + email registered on this site → 2 signals → confirmed
    # (no name needed).
    acc = OsintAccount("GitHub", "dev", "https://github.com/nadams123", "profile",
                       "likely", "maigret",
                       {"username": "nadams123", "cand_source": "known"})
    assert res._classify(acc, "Nathan Adams", {"github"}) == "confirmed"


def test_zero_signals_is_guess():
    # No name match, not known, not registered, not a probe → 0 signals → guess.
    acc = OsintAccount("GitHub", "dev", "https://github.com/randomhandle", "profile",
                       "likely", "maigret",
                       {"name": "Someone Else", "username": "randomhandle"})
    assert res._classify(acc, "Nathan Adams", set()) == "guess"
