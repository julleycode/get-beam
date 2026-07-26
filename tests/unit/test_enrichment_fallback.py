"""Unit tests for the enrichment fallback chain: PDL → Apollo → email domain.

Before this chain existed, a PDL 404 meant zero enrichment for that visitor
(steps 2-4 of the waterfall consume PDL's own output), which is why sites with
non-US or small-company traffic showed enriched=0 with a pile of `failed` rows.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import apps.api.main  # noqa: F401 — registers ORM mappers before model construction
from apps.api.services.enricher import Enricher, _domain_enrichment


class TestDomainEnrichment:
    """Free last-resort fill. Pure — no I/O."""

    @pytest.mark.parametrize(
        "email,company,domain",
        [
            ("chris@dvrk.vn", "Dvrk", "dvrk.vn"),
            ("kietle@vinpixstudio.com", "Vinpixstudio", "vinpixstudio.com"),
            ("theo@bitsentry.ai", "Bitsentry", "bitsentry.ai"),
            ("a@acme-corp.co.uk", "Acme Corp", "acme-corp.co.uk"),
            ("b@ACME.COM", "Acme", "acme.com"),
        ],
    )
    def test_company_from_business_domain(self, email, company, domain):
        assert _domain_enrichment(email) == {
            "company_name": company,
            "company_domain": domain,
        }

    @pytest.mark.parametrize(
        "email",
        [
            "davidtuber710@gmail.com",
            "someone@yahoo.co.uk",
            "x@outlook.com",
            "y@icloud.com",
            "z@qq.com",
            "w@proton.me",
        ],
    )
    def test_consumer_mailboxes_yield_nothing(self, email):
        """A "Gmail" company on a lead is worse than an empty field."""
        assert _domain_enrichment(email) is None

    @pytest.mark.parametrize("email", [None, "", "not-an-email", "@nodomain", "a@b"])
    def test_malformed_input_yields_nothing(self, email):
        assert _domain_enrichment(email) is None

    def test_it_never_invents_a_job_title(self):
        """A domain says where someone works, never what they do."""
        assert "job_title" not in _domain_enrichment("chris@dvrk.vn")


def _visitor():
    v = MagicMock()
    v.visitor_id = "visitor_abcdef123"
    v.site_id = "site_x"
    v.enrichment_status = "pending"
    return v


def _apollo_response(person: dict | None, status: int = 200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = {"person": person} if person is not None else {}
    return resp


def _enricher() -> Enricher:
    e = Enricher(db=AsyncMock())
    e._log_enrich = AsyncMock()
    return e


@pytest.fixture
def apollo_configured(monkeypatch):
    """Force the key/toggle ON regardless of the developer's .env.

    Without this the suite passes locally (a real key is loaded) and fails on a
    keyless machine, where _enrich_apollo short-circuits before any HTTP.
    """
    from apps.api.config import settings

    monkeypatch.setattr(settings, "apollo_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "apollo_enabled", True, raising=False)


@pytest.mark.asyncio
@pytest.mark.usefixtures("apollo_configured")
class TestApolloEnrich:
    APOLLO_PERSON = {
        "name": "Chris Nguyen",
        "title": "Founder",
        "seniority": "founder",
        "linkedin_url": "https://linkedin.com/in/chrisn",
        "twitter_url": "https://twitter.com/chrisn",
        "city": "Ho Chi Minh City",
        "country": "Vietnam",
        "organization": {
            "name": "DVRK",
            "primary_domain": "dvrk.vn",
            "industry": "design",
            "estimated_num_employees": 12,
        },
    }

    async def _run(self, enricher, response):
        client = AsyncMock()
        client.post.return_value = response
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=client)
        cm.__aexit__ = AsyncMock(return_value=False)
        with patch("apps.api.services.enricher.httpx.AsyncClient", return_value=cm):
            return await enricher._enrich_apollo("chris@dvrk.vn", visitor=_visitor())

    async def test_it_maps_apollo_fields_to_the_pdl_dict_shape(self):
        """_upsert_profile consumes either provider's dict, so the keys must match."""
        e = _enricher()
        e._cache_get = AsyncMock(return_value=(False, None))
        e._cache_set = AsyncMock()
        data = await self._run(e, _apollo_response(self.APOLLO_PERSON))
        assert data["job_title"] == "Founder"
        assert data["company_name"] == "DVRK"
        assert data["company_domain"] == "dvrk.vn"
        assert data["industry"] == "design"
        assert data["seniority_level"] == "founder"
        assert data["linkedin_url"] == "https://linkedin.com/in/chrisn"
        assert data["twitter_handle"] == "chrisn"
        assert data["company_size"] == "12", "column is a string; Apollo sends an int"

    async def test_a_200_with_no_person_is_a_definitive_miss(self):
        e = _enricher()
        e._cache_get = AsyncMock(return_value=(False, None))
        e._cache_set = AsyncMock()
        assert await self._run(e, _apollo_response(None)) is None
        e._cache_set.assert_awaited()  # negative-cached

    async def test_an_unmappable_200_is_not_cached_as_a_miss(self):
        """If Apollo's response keys move, that's drift, not a no-match.
        Negative-caching it would hide the breakage for 7 days per address."""
        e = _enricher()
        e._cache_get = AsyncMock(return_value=(False, None))
        e._cache_set = AsyncMock()
        data = await self._run(e, _apollo_response({"id": "x", "photo_url": "y"}))
        assert data is None
        e._cache_set.assert_not_awaited()

    async def test_bad_key_returns_none_without_raising(self):
        """PDL already missed; a 401 here must still let the domain fill run."""
        e = _enricher()
        e._cache_get = AsyncMock(return_value=(False, None))
        e._cache_set = AsyncMock()
        assert await self._run(e, _apollo_response(None, status=401)) is None
        e._cache_set.assert_not_awaited()

    async def test_disabled_or_keyless_short_circuits_before_any_http(self, monkeypatch):
        from apps.api.config import settings

        monkeypatch.setattr(settings, "apollo_api_key", "", raising=False)
        e = _enricher()
        with patch("apps.api.services.enricher.httpx.AsyncClient") as client:
            assert await e._enrich_apollo("a@b.com", visitor=_visitor()) is None
            client.assert_not_called()

    async def test_no_personal_pii_is_requested(self):
        """reveal_personal_emails / reveal_phone_number cost credits and pull
        more PII than the product needs — we already hold the address."""
        e = _enricher()
        e._cache_get = AsyncMock(return_value=(False, None))
        e._cache_set = AsyncMock()
        client = AsyncMock()
        client.post.return_value = _apollo_response(self.APOLLO_PERSON)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=client)
        cm.__aexit__ = AsyncMock(return_value=False)
        with patch("apps.api.services.enricher.httpx.AsyncClient", return_value=cm):
            await e._enrich_apollo("chris@dvrk.vn", visitor=_visitor())
        payload = client.post.await_args.kwargs["json"]
        assert payload == {"email": "chris@dvrk.vn"}

    async def test_cache_hit_skips_http_entirely(self):
        e = _enricher()
        e._cache_get = AsyncMock(return_value=(True, {"job_title": "CTO"}))
        with patch("apps.api.services.enricher.httpx.AsyncClient") as client:
            data = await e._enrich_apollo("a@b.com", visitor=_visitor())
            assert data == {"job_title": "CTO"}
            client.assert_not_called()


@pytest.mark.asyncio
class TestEnrichTier1FallbackWiring:
    """The regression itself: a PDL miss must no longer end enrichment.

    Production evidence (26-07-26): bravestep had 8 identified visitors with
    emails, 0 enrichment profiles and enrichment_status failed=10 — every one a
    PDL 404 that stopped the waterfall dead.
    """

    def _identified(self, email="chris@dvrk.vn"):
        ident = MagicMock()
        ident.email = email
        return ident

    @pytest.fixture(autouse=True)
    def _not_a_known_contact(self, monkeypatch):
        """enrich_tier1's first gate skips the whole waterfall for emails already
        in the customer's CRM. Stub it to "not known" so these tests exercise the
        provider chain rather than that gate (against a mock DB the real lookup
        returns a truthy coroutine and silently short-circuits everything)."""
        import apps.api.services.known_contacts_match as kcm

        monkeypatch.setattr(
            kcm, "is_known_contact", AsyncMock(return_value=(False, None))
        )

    def _enricher_with(self, pdl=None, apollo=None):
        e = Enricher(db=AsyncMock())
        e._enrich_pdl = AsyncMock(return_value=pdl)
        e._enrich_apollo = AsyncMock(return_value=apollo)
        e._upsert_profile = AsyncMock(return_value=MagicMock(
            linkedin_url=None, twitter_handle=None, social_context=None,
            avatar_url="set",
        ))
        e._fetch_and_store_content = AsyncMock()
        e._profile_completeness = MagicMock(return_value=0.5)
        return e

    async def test_pdl_miss_falls_through_to_apollo(self):
        e = self._enricher_with(pdl=None, apollo={"job_title": "Founder"})
        visitor = _visitor()
        profile = await e.enrich_tier1(visitor, self._identified())
        assert profile is not None
        e._enrich_apollo.assert_awaited_once()
        assert e._upsert_profile.await_args.args[1] == {"job_title": "Founder"}
        assert visitor.enrichment_status != "failed"

    async def test_both_providers_miss_falls_through_to_domain_fill(self):
        e = self._enricher_with(pdl=None, apollo=None)
        visitor = _visitor()
        profile = await e.enrich_tier1(visitor, self._identified("chris@dvrk.vn"))
        assert profile is not None
        assert e._upsert_profile.await_args.args[1] == {
            "company_name": "Dvrk",
            "company_domain": "dvrk.vn",
        }

    async def test_consumer_mailbox_with_no_provider_match_still_fails(self):
        """Honest outcome: nobody can name an employer for a Gmail address."""
        e = self._enricher_with(pdl=None, apollo=None)
        visitor = _visitor()
        profile = await e.enrich_tier1(visitor, self._identified("dave710@gmail.com"))
        assert profile is None
        assert visitor.enrichment_status == "failed"

    async def test_apollo_is_not_called_when_pdl_hits(self):
        """The fallback must not add cost to the path that already works."""
        e = self._enricher_with(pdl={"job_title": "VP"}, apollo={"job_title": "X"})
        await e.enrich_tier1(_visitor(), self._identified())
        e._enrich_apollo.assert_not_awaited()
