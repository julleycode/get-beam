"""Company exclusion list — CRUD (G2), flag-ON enforcement (G3), flag-OFF parity (G4).

Requires PG :5433 + Redis :6379. Flag ON is set by monkeypatching the shared
``settings`` object; flag-OFF-only evidence would be vacuous.
"""

import uuid as uuidlib
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import event, select

pytestmark = pytest.mark.integration


async def _signup(client, email: str) -> str:
    resp = await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "testpass123", "full_name": "CE Tester"},
    )
    if resp.status_code != 200:
        resp = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": "testpass123"}
        )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(t: str) -> dict:
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture
def flag_on(monkeypatch):
    from apps.api.config import settings

    monkeypatch.setattr(settings, "company_exclusion_enabled", True)


@pytest_asyncio.fixture
async def owner(test_client, test_db):
    """Signed-up user + an owned site. Returns dict(token, site_id, user_id)."""
    from apps.api.models.site import Site
    from apps.api.models.user import User

    sfx = uuidlib.uuid4().hex[:8]
    email = f"ce-{sfx}@test.com"
    token = await _signup(test_client, email)
    user = (await test_db.execute(select(User).where(User.email == email))).scalar_one()
    site_id = f"ce_site_{sfx}"
    test_db.add(Site(site_id=site_id, user_id=user.id, name="CE", url="https://ce.example.com"))
    await test_db.commit()
    return {"token": token, "site_id": site_id, "user_id": user.id}


async def _seed_audience(test_db, site_id: str) -> dict:
    """Segment with 4 members:
    v-cust  : email at sub.customer.com          -> excluded (email domain + walk)
    v-comp  : Visitor.company_domain rival.io    -> excluded (company domain)
    v-merged: merged visitor whose canonical has customer.com email -> excluded
    v-ok    : prospect.com                       -> kept
    Exclusions: customer.com=customer, rival.io=competitor.
    """
    from apps.api.models.segment import Segment, SegmentMember
    from apps.api.models.site_exclusion import SiteExclusion
    from apps.api.models.visitor import IdentifiedVisitor, Visitor
    from apps.api.models.visitor_email import VisitorEmail

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    def V(vid, **kw):
        return Visitor(site_id=site_id, visitor_id=vid, intent_score=80, first_seen=now,
                       last_seen=now, enrichment_status="enriched", **kw)

    test_db.add_all([
        V("v-cust"), V("v-comp", company_domain="www.rival.io"),
        V("v-merged", canonical_visitor_id="v-canon"), V("v-canon"), V("v-ok"),
    ])
    test_db.add_all([
        IdentifiedVisitor(site_id=site_id, visitor_id="v-cust", email="jane@sub.customer.com",
                          full_name="Jane C", resolution_provider="form_capture"),
        IdentifiedVisitor(site_id=site_id, visitor_id="v-comp", email="bob@rivalmail.net",
                          full_name="Bob R", resolution_provider="form_capture"),
        IdentifiedVisitor(site_id=site_id, visitor_id="v-merged", email="m@other.org",
                          full_name="Mer G", resolution_provider="form_capture"),
        IdentifiedVisitor(site_id=site_id, visitor_id="v-ok", email="ok@prospect.com",
                          full_name="Ok P", resolution_provider="form_capture"),
        VisitorEmail(site_id=site_id, visitor_id="v-canon", email="canon@customer.com"),
    ])
    seg = Segment(site_id=site_id, name="Aud", visitor_count=4)
    test_db.add(seg)
    await test_db.flush()
    for vid in ("v-cust", "v-comp", "v-merged", "v-ok"):
        test_db.add(SegmentMember(segment_id=seg.id, visitor_id=vid, site_id=site_id))
    test_db.add_all([
        SiteExclusion(site_id=site_id, domain="customer.com", reason="customer"),
        SiteExclusion(site_id=site_id, domain="rival.io", reason="competitor"),
    ])
    await test_db.commit()
    return {"segment_id": seg.id}


EXCLUDED = {"v-cust", "v-comp", "v-merged"}


# ─────────────────────────── G2: CRUD ───────────────────────────

class TestCrud:
    async def test_crud_create_list_delete(self, test_client, owner):
        h, sid = _auth(owner["token"]), owner["site_id"]
        r = await test_client.post(f"/api/v1/sites/{sid}/exclusions",
                                   json={"domain": "https://www.Acme.com/x", "reason": "customer",
                                         "company_name": "Acme"}, headers=h)
        assert r.status_code == 201, r.text
        assert r.json()["domain"] == "acme.com"
        # upsert on same domain
        r2 = await test_client.post(f"/api/v1/sites/{sid}/exclusions",
                                    json={"domain": "acme.com", "reason": "competitor"}, headers=h)
        assert r2.status_code == 201 and r2.json()["reason"] == "competitor"
        lst = (await test_client.get(f"/api/v1/sites/{sid}/exclusions", headers=h)).json()
        assert [e["domain"] for e in lst] == ["acme.com"]
        d = await test_client.delete(f"/api/v1/sites/{sid}/exclusions/{lst[0]['id']}", headers=h)
        assert d.status_code == 204
        assert (await test_client.get(f"/api/v1/sites/{sid}/exclusions", headers=h)).json() == []
        d2 = await test_client.delete(f"/api/v1/sites/{sid}/exclusions/{lst[0]['id']}", headers=h)
        assert d2.status_code == 404

    async def test_crud_rejects_freemail_and_suffix(self, test_client, owner):
        h, sid = _auth(owner["token"]), owner["site_id"]
        for dom, err in [("gmail.com", "freemail_domain"), ("co.uk", "public_suffix")]:
            r = await test_client.post(f"/api/v1/sites/{sid}/exclusions",
                                       json={"domain": dom}, headers=h)
            assert r.status_code == 422 and r.json()["detail"] == err

    async def test_crud_import_csv(self, test_client, owner):
        h, sid = _auth(owner["token"]), owner["site_id"]
        csv = b"domain,company_name,reason\nacme.com,Acme,customer\ngmail.com,,other\nrival.io,,competitor\n"
        r = await test_client.post(f"/api/v1/sites/{sid}/exclusions/import",
                                   files={"file": ("x.csv", csv, "text/csv")}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["upserted"] == 2
        assert r.json()["errors"] == [{"row": 3, "error": "freemail_domain"}]
        # idempotent re-import
        r = await test_client.post(f"/api/v1/sites/{sid}/exclusions/import",
                                   files={"file": ("x.csv", csv, "text/csv")}, headers=h)
        lst = (await test_client.get(f"/api/v1/sites/{sid}/exclusions", headers=h)).json()
        assert sorted(e["domain"] for e in lst) == ["acme.com", "rival.io"]

    async def test_crud_import_too_large_413(self, test_client, owner):
        h, sid = _auth(owner["token"]), owner["site_id"]
        big = b"a" * (1_048_576 + 10)
        r = await test_client.post(f"/api/v1/sites/{sid}/exclusions/import",
                                   files={"file": ("x.csv", big, "text/csv")}, headers=h)
        assert r.status_code == 413

    async def test_crud_foreign_site_404(self, test_client, owner):
        other = await _signup(test_client, f"ce-other-{uuidlib.uuid4().hex[:6]}@test.com")
        sid = owner["site_id"]
        h = _auth(other)
        assert (await test_client.get(f"/api/v1/sites/{sid}/exclusions", headers=h)).status_code == 404
        assert (await test_client.post(f"/api/v1/sites/{sid}/exclusions",
                                       json={"domain": "acme.com"}, headers=h)).status_code == 404
        assert (await test_client.delete(f"/api/v1/sites/{sid}/exclusions/{uuidlib.uuid4()}",
                                         headers=h)).status_code == 404
        assert (await test_client.post(f"/api/v1/sites/{sid}/exclusions/import",
                                       files={"file": ("x.csv", b"acme.com\n", "text/csv")},
                                       headers=h)).status_code == 404

    async def test_crud_requires_auth(self, test_client, owner):
        r = await test_client.get(f"/api/v1/sites/{owner['site_id']}/exclusions")
        assert r.status_code in (401, 403)

    async def test_crud_site_delete_cascades(self, test_db, owner):
        from sqlalchemy import delete

        from apps.api.models.site import Site
        from apps.api.models.site_exclusion import SiteExclusion

        sid = owner["site_id"]
        test_db.add(SiteExclusion(site_id=sid, domain="acme.com", reason="customer"))
        await test_db.commit()
        await test_db.execute(delete(Site).where(Site.site_id == sid))
        await test_db.commit()
        left = (await test_db.execute(
            select(SiteExclusion).where(SiteExclusion.site_id == sid))).scalars().all()
        assert left == []


# ─────────────────────────── G3: flag ON ───────────────────────────

class TestFlagOn:
    async def test_flag_on_helper_and_merged(self, test_db, owner, flag_on):
        from apps.api.services.company_exclusion import excluded_visitor_ids

        await _seed_audience(test_db, owner["site_id"])
        ex = await excluded_visitor_ids(
            test_db, owner["site_id"], ["v-cust", "v-comp", "v-merged", "v-ok", "v-unknown"])
        assert ex == {"v-cust": "customer", "v-comp": "competitor", "v-merged": "customer"}

    async def test_flag_on_campaign_send_skips(self, test_db, owner, flag_on, monkeypatch):
        from apps.api.models.campaign import Campaign
        from apps.api.services import campaign_sender

        seed = await _seed_audience(test_db, owner["site_id"])
        camp = Campaign(site_id=owner["site_id"], segment_id=seed["segment_id"], name="C",
                        campaign_type="email", status="active",
                        plan={"touchpoints": [{"channel": "email", "step": 1,
                                               "subject": "Hi", "body": "Hello"}]})
        test_db.add(camp)
        await test_db.commit()
        sends: list[str] = []

        async def _fake_send(self, *, to_email, **kw):
            sends.append(to_email)

        async def _no_gmail(db, site_id):
            return None

        monkeypatch.setattr(campaign_sender.EmailSender, "send", _fake_send)
        monkeypatch.setattr(campaign_sender, "resolve_sender_for_site", _no_gmail)
        summary = await campaign_sender.send_campaign_emails(test_db, camp)
        assert summary["skipped_company_excluded"] == 3
        assert sends == ["ok@prospect.com"]

    async def test_flag_on_export_ads_crm_drop(self, test_db, owner, flag_on):
        # ads_push / crm_push / exports all read _get_segment_visitors (census G7).
        from apps.api.services.csv_exporter import _get_segment_visitors

        seed = await _seed_audience(test_db, owner["site_id"])
        rows = await _get_segment_visitors(test_db, str(seed["segment_id"]))
        assert {r["email"] for r in rows} == {"ok@prospect.com"}

    async def test_flag_on_linkedin_targets_drop(self, test_db, owner, flag_on):
        from apps.api.models.campaign import Campaign
        from apps.api.models.enrichment import EnrichmentProfile
        from apps.api.routers.campaigns import _resolve_linkedin_targets

        sid = owner["site_id"]
        seed = await _seed_audience(test_db, sid)
        for vid in ("v-cust", "v-comp", "v-merged", "v-ok"):
            test_db.add(EnrichmentProfile(site_id=sid, visitor_id=vid,
                                          linkedin_url=f"https://www.linkedin.com/in/{vid}"))
        camp = Campaign(site_id=sid, segment_id=seed["segment_id"], name="L",
                        campaign_type="linkedin", status="active", plan={})
        test_db.add(camp)
        await test_db.commit()
        urls, _skipped = await _resolve_linkedin_targets(test_db, sid, camp, 50)
        assert urls == ["https://www.linkedin.com/in/v-ok"]

    async def test_flag_on_segmentation_omits_but_ai_ask_profiles_keep(
        self, test_db, owner, flag_on, monkeypatch
    ):
        from apps.api.agents import segmenter
        from apps.api.config import settings
        from apps.api.models.visitor import Visitor

        sid = owner["site_id"]
        await _seed_audience(test_db, sid)
        visitors = list((await test_db.execute(
            select(Visitor).where(Visitor.site_id == sid,
                                  Visitor.visitor_id.in_(["v-cust", "v-comp", "v-ok"])))
        ).scalars().all())
        seen_prompt: list[str] = []

        async def _fake_json(prompt, **kw):
            seen_prompt.append(prompt)
            return {"segments": [{"name": "All", "visitor_ids": ["v-cust", "v-comp", "v-ok"]}]}

        monkeypatch.setattr(segmenter, "gemini_generate_json", _fake_json)
        monkeypatch.setattr(settings, "gemini_api_key", "test-key")
        segs = await segmenter.run_segmentation(test_db, sid, "S", "", "", visitors)
        from apps.api.models.segment import SegmentMember

        members = (await test_db.execute(
            select(SegmentMember.visitor_id).where(SegmentMember.segment_id == segs[0].id))
        ).scalars().all()
        assert list(members) == ["v-ok"]
        assert "v-cust" not in seen_prompt[0] and "v-comp" not in seen_prompt[0]
        # build_visitor_profiles (the /ai/ask builder) is NOT filtered
        profiles = await segmenter.build_visitor_profiles(test_db, sid, visitors)
        assert {p["visitor_id"] for p in profiles} == {"v-cust", "v-comp", "v-ok"}

    async def test_flag_on_segmentation_all_excluded_returns_empty_no_gemini(
        self, test_db, owner, flag_on, monkeypatch
    ):
        from apps.api.agents import segmenter
        from apps.api.models.visitor import Visitor

        sid = owner["site_id"]
        await _seed_audience(test_db, sid)
        visitors = list((await test_db.execute(
            select(Visitor).where(Visitor.site_id == sid,
                                  Visitor.visitor_id.in_(["v-cust", "v-comp"])))).scalars().all())

        async def _boom(*a, **kw):
            raise AssertionError("Gemini must not be called")

        monkeypatch.setattr(segmenter, "gemini_generate_json", _boom)
        assert await segmenter.run_segmentation(test_db, sid, "S", "", "", visitors) == []

    async def test_flag_on_segmentation_celery_task_path(self, test_db, owner, flag_on, monkeypatch):
        from apps.api.agents import segmenter
        from apps.api.config import settings
        from apps.api.models.site import Site
        from apps.api.tasks import segmentation_tasks

        sid = owner["site_id"]
        await _seed_audience(test_db, sid)

        async def _fake_json(prompt, **kw):
            return {"segments": [{"name": "All", "visitor_ids":
                                  ["v-cust", "v-comp", "v-merged", "v-canon", "v-ok"]}]}

        planned: list[set] = []

        async def _fake_plan(db, segment, profiles, *a, **kw):
            planned.append({p["visitor_id"] for p in profiles})

        monkeypatch.setattr(segmenter, "gemini_generate_json", _fake_json)
        monkeypatch.setattr(settings, "gemini_api_key", "test-key")
        monkeypatch.setattr(segmentation_tasks, "plan_campaign", _fake_plan)
        site = (await test_db.execute(select(Site).where(Site.site_id == sid))).scalar_one()
        await segmentation_tasks._run_segmentation_for_site(test_db, site)
        assert planned and all(not (s & EXCLUDED) for s in planned)
        assert "v-ok" in planned[0]

    async def test_flag_on_segments_run_route(self, test_client, test_db, owner, flag_on, monkeypatch):
        from apps.api.agents import segmenter
        from apps.api.config import settings
        from apps.api.models.segment import Segment, SegmentMember

        sid = owner["site_id"]
        await _seed_audience(test_db, sid)

        async def _fake_json(prompt, **kw):
            return {"segments": [{"name": "Route", "visitor_ids":
                                  ["v-cust", "v-comp", "v-merged", "v-canon", "v-ok"]}]}

        monkeypatch.setattr(segmenter, "gemini_generate_json", _fake_json)
        monkeypatch.setattr(settings, "gemini_api_key", "test-key")
        r = await test_client.post(f"/api/v1/segments/{sid}/run", headers=_auth(owner["token"]))
        assert r.status_code == 200, r.text
        seg = (await test_db.execute(
            select(Segment).where(Segment.site_id == sid, Segment.name == "Route"))).scalar_one()
        members = set((await test_db.execute(
            select(SegmentMember.visitor_id).where(SegmentMember.segment_id == seg.id))
        ).scalars().all())
        assert not (members & EXCLUDED) and "v-ok" in members

    async def test_flag_on_planner_input_filtered(self, test_client, test_db, owner, flag_on, monkeypatch):
        from apps.api.models.campaign import Campaign
        from apps.api.routers import campaigns as campaigns_router

        sid = owner["site_id"]
        seed = await _seed_audience(test_db, sid)
        seen: list[set] = []

        async def _fake_plan(db, segment, visitor_profiles, connected_accounts=None, **kw):
            seen.append({p["visitor_id"] for p in visitor_profiles})
            c = Campaign(site_id=segment.site_id, segment_id=segment.id, name="P",
                         campaign_type="email", status="draft", plan={})
            db.add(c)
            await db.commit()
            await db.refresh(c)
            return c

        monkeypatch.setattr(campaigns_router, "plan_campaign", _fake_plan)
        r = await test_client.post(f"/api/v1/campaigns/{sid}/create/{seed['segment_id']}",
                                   headers=_auth(owner["token"]))
        assert r.status_code == 200, r.text
        assert seen == [{"v-ok"}]

    async def test_flag_on_auto_drafter_no_draft(self, test_db, owner, flag_on, monkeypatch):
        from apps.api.models.user import User
        from apps.api.models.visitor import Visitor
        from apps.api.services.auto_drafter import AutoDrafter

        sid = owner["site_id"]
        await _seed_audience(test_db, sid)
        v = (await test_db.execute(select(Visitor).where(
            Visitor.site_id == sid, Visitor.visitor_id == "v-cust"))).scalar_one()
        user = (await test_db.execute(select(User).where(User.id == owner["user_id"]))).scalar_one()
        res = await AutoDrafter(test_db).generate_for_visitor(
            v, {"full_name": "Jane"}, {"recent_posts": [{"text": "x"}] * 5}, user,
            trigger_reason="job_change:A->B")
        assert res is None

    async def _draft(self, test_db, owner, status, visitor_id="v-cust", site=True):
        from apps.api.models.draft import Draft, DraftStatus, DraftType
        from apps.api.models.social_account import Platform

        d = Draft(user_id=owner["user_id"], type=DraftType.reply, platform=Platform.twitter,
                  ai_content="hi", status=getattr(DraftStatus, status), visitor_id=visitor_id,
                  site_id=owner["site_id"] if site else None, auto_generated=True)
        test_db.add(d)
        await test_db.commit()
        return d

    async def test_flag_on_approve_excluded_draft_409(self, test_client, test_db, owner, flag_on, monkeypatch):
        from apps.api.models.draft import Draft, DraftStatus
        from apps.api.routers import drafts as drafts_router

        await _seed_audience(test_db, owner["site_id"])
        d = await self._draft(test_db, owner, "pending")
        sent: list = []

        async def _spy(db, draft):
            sent.append(draft.id)
            return True

        monkeypatch.setattr(drafts_router, "send_draft", _spy)
        r = await test_client.post(f"/api/v1/drafts/{d.id}/approve", headers=_auth(owner["token"]))
        assert r.status_code == 409 and r.json()["detail"] == "company_excluded"
        assert sent == []
        await test_db.refresh(d)
        assert d.status == DraftStatus.pending

    async def test_flag_on_retry_excluded_draft_409(self, test_client, test_db, owner, flag_on):
        from apps.api.models.draft import DraftStatus

        await _seed_audience(test_db, owner["site_id"])
        d = await self._draft(test_db, owner, "failed")
        r = await test_client.post(f"/api/v1/drafts/{d.id}/retry", headers=_auth(owner["token"]))
        assert r.status_code == 409 and r.json()["detail"] == "company_excluded"
        await test_db.refresh(d)
        assert d.status == DraftStatus.failed

    async def test_flag_on_send_draft_raises_typed_error(self, test_db, owner, flag_on):
        from apps.api.services.company_exclusion import CompanyExcludedError
        from apps.api.services.sender import send_draft

        await _seed_audience(test_db, owner["site_id"])
        d = await self._draft(test_db, owner, "approved")
        with pytest.raises(CompanyExcludedError):
            await send_draft(test_db, d)
        # null site_id fails open (no lookup) — send_draft proceeds to its own guards
        d2 = await self._draft(test_db, owner, "approved", site=False)
        assert await send_draft(test_db, d2) is False

    async def test_flag_on_visitor_list_badge(self, test_client, test_db, owner, flag_on):
        await _seed_audience(test_db, owner["site_id"])
        r = await test_client.get(f"/api/v1/visitors/{owner['site_id']}?page_size=50",
                                  headers=_auth(owner["token"]))
        assert r.status_code == 200, r.text
        by = {v["visitor_id"]: v.get("excluded_reason") for v in r.json()["visitors"]}
        assert by.get("v-cust") == "customer"
        assert by.get("v-comp") == "competitor"
        assert by.get("v-ok") is None


# ─────────────────────────── G4: flag OFF ───────────────────────────

class TestFlagOff:
    async def test_flag_off_zero_new_queries(self, test_engine, test_client, test_db, owner, monkeypatch):
        from apps.api.config import settings
        from apps.api.services import campaign_sender, company_exclusion
        from apps.api.services.csv_exporter import _get_segment_visitors
        from apps.api.models.campaign import Campaign

        assert settings.company_exclusion_enabled is False
        seed = await _seed_audience(test_db, owner["site_id"])

        async def _boom(*a, **kw):
            raise AssertionError("exclusion helper called with flag OFF")

        monkeypatch.setattr(company_exclusion, "excluded_visitor_ids", _boom)
        monkeypatch.setattr(company_exclusion, "filter_visitor_ids", _boom)
        monkeypatch.setattr(company_exclusion, "draft_is_company_excluded", _boom)

        stmts: list[str] = []

        def _cap(conn, cursor, statement, *a):
            stmts.append(statement)

        event.listen(test_engine.sync_engine, "before_cursor_execute", _cap)
        try:
            rows = await _get_segment_visitors(test_db, str(seed["segment_id"]))
            assert len(rows) == 4  # nobody dropped
            camp = Campaign(site_id=owner["site_id"], segment_id=seed["segment_id"], name="C",
                            campaign_type="email", status="active",
                            plan={"touchpoints": [{"channel": "email", "step": 1,
                                                   "subject": "Hi", "body": "Hello"}]})
            test_db.add(camp)
            await test_db.commit()

            async def _fake_send(self, *, to_email, **kw):
                return None

            async def _no_gmail(db, site_id):
                return None

            monkeypatch.setattr(campaign_sender.EmailSender, "send", _fake_send)
            monkeypatch.setattr(campaign_sender, "resolve_sender_for_site", _no_gmail)
            summary = await campaign_sender.send_campaign_emails(test_db, camp)
            assert "skipped_company_excluded" not in summary
            assert summary["sent"] == 4
            r = await test_client.get(f"/api/v1/visitors/{owner['site_id']}?page_size=50",
                                      headers=_auth(owner["token"]))
            assert r.status_code == 200
            assert all(v.get("excluded_reason") is None for v in r.json()["visitors"])
        finally:
            event.remove(test_engine.sync_engine, "before_cursor_execute", _cap)
        assert not [s for s in stmts if "site_exclusions" in s], "flag OFF touched site_exclusions"
