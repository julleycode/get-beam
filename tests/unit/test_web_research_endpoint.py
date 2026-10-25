"""POST /visitors/{site_id}/{visitor_id}/web-research — contract of the
undecorated helper `_web_research` (P2-G1) + detail schema field (P2-G3)."""
import importlib
import pkgutil
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from apps.api.routers import visitors as vr
from apps.api.schemas.visitors import VisitorDetailOut, VisitorOut

import apps.api.models as _models

# select(Visitor) configures every mapper; register all ORM models first so
# string relationships (e.g. User -> "SocialAccount") resolve.
for _m in pkgutil.iter_modules(_models.__path__):
    importlib.import_module(f"apps.api.models.{_m.name}")

pytestmark = pytest.mark.unit


def _res(obj):
    r = MagicMock()
    r.scalar_one_or_none.return_value = obj
    return r


def _db(*objs):
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[_res(o) for o in objs])
    db.commit = AsyncMock()
    return db


VISITOR = SimpleNamespace(visitor_id="abcdef123456", site_id="s1")


def _ident(full_name="Ava Chen", email="ava@examplelabs.com"):
    return SimpleNamespace(full_name=full_name, email=email)


def _profile(**kw):
    base = dict(job_title=None, company_name="Example Labs", linkedin_url=None,
                personal_website=None, social_context=None)
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(vr.settings, "tinyfish_enrichment_enabled", True)
    verify = AsyncMock(return_value=SimpleNamespace(id="s1"))
    monkeypatch.setattr(vr, "_verify_site_access", verify)
    enrich = AsyncMock(return_value=False)
    monkeypatch.setattr(vr, "enrich_from_web", enrich)
    return SimpleNamespace(verify=verify, enrich=enrich)


async def _call(db):
    return await vr._web_research(db, "s1", "abcdef123456", SimpleNamespace(id="u1"))


async def _status(db):
    with pytest.raises(HTTPException) as e:
        await _call(db)
    return e.value.status_code, e.value.detail


async def test_flag_off_404_before_any_db(env, monkeypatch):
    monkeypatch.setattr(vr.settings, "tinyfish_enrichment_enabled", False)
    db = _db()
    assert await _status(db) == (404, "Not Found")
    env.verify.assert_not_called()
    db.execute.assert_not_called()


async def test_foreign_site_404(env):
    env.verify.side_effect = HTTPException(status_code=404, detail="Site not found")
    db = _db()
    assert (await _status(db))[0] == 404
    env.enrich.assert_not_called()


async def test_missing_or_bot_visitor_404(env):
    assert await _status(_db(None)) == (404, "Visitor not found")


async def test_not_identified_409(env):
    assert await _status(_db(VISITOR, None)) == (409, "not_identified")


async def test_no_profile_409(env):
    assert await _status(_db(VISITOR, _ident(), None)) == (409, "no_profile")


async def test_missing_name_422(env):
    assert await _status(_db(VISITOR, _ident(full_name="  "), _profile())) == (422, "missing_name")


async def test_missing_company_422(env):
    db = _db(VISITOR, _ident(email="ava@gmail.com"), _profile(company_name=None))
    assert await _status(db) == (422, "missing_company")
    env.enrich.assert_not_called()


async def test_no_results_does_not_commit(env):
    db = _db(VISITOR, _ident(), _profile())
    assert await _call(db) == {"status": "no_results"}
    env.enrich.assert_awaited_once()
    db.commit.assert_not_called()


async def test_happy_path_commits_and_returns_web(env):
    profile = _profile(linkedin_url="https://www.linkedin.com/in/existing")
    web = {"summary": "s", "sources": ["https://x.com"], "fetched_at": "t"}

    async def fake_enrich(visitor, identified, prof, db):
        prof.job_title = "Head of Growth"
        prof.social_context = {"web": web}
        return True

    env.enrich.side_effect = fake_enrich
    db = _db(VISITOR, _ident(), profile)
    out = await _call(db)
    assert out == {"status": "updated", "filled": ["job_title"], "web": web}
    env.enrich.assert_awaited_once()
    db.commit.assert_awaited_once()
    # response never carries PII
    assert "Ava" not in repr(out) and "ava@" not in repr(out)


def test_detail_schema_has_flag_list_schema_does_not():
    assert "web_research_enabled" in VisitorDetailOut.model_fields
    assert VisitorDetailOut.model_fields["web_research_enabled"].default is False
    assert "web_research_enabled" not in VisitorOut.model_fields


def test_route_registered():
    paths = {(r.path, tuple(sorted(r.methods))) for r in vr.router.routes if hasattr(r, "methods")}
    assert ("/{site_id}/{visitor_id}/web-research", ("POST",)) in paths
