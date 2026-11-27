"""Model package.

Historically empty: every model is registered on ``Base.metadata`` transitively
by ``import apps.api.main`` (see ``apps/api/migrations/env.py`` and
``tests/conftest.py``). ``ip_org_prefix`` is imported HERE instead because it has
no router and is only referenced from a service, so nothing in the main import
graph would pull it in — and an unregistered model makes ``create_all`` skip the
table and makes alembic autogenerate propose a spurious DROP.

Safe against circular imports: ``ip_org_prefix`` imports only
``apps.api.models.database``, which imports ``apps.api.config`` and nothing from
this package.

``rpki_roa`` is registered here for exactly the same reason and with the same
import safety.
"""

from apps.api.models.ip_org_prefix import IpOrgPrefix  # noqa: F401
from apps.api.models.rpki_roa import RpkiRoa  # noqa: F401
from apps.api.models.site_exclusion import SiteExclusion  # noqa: F401
# Registered here too: written only by routers/click.py and read by
# routers/campaigns.py, but neither imports it at module load.
from apps.api.models.cta_click_event import CtaClickEvent  # noqa: F401

# conversion-apis: the sweep is the only writer; registered here so create_all /
# alembic autogenerate always see both tables (same rationale as above).
from apps.api.models.ad_conversion import AdConversionConfig, AdConversionDelivery  # noqa: F401,E402
from apps.api.models.crm_closed_won import CrmClosedWonContact  # noqa: F401,E402
# ad-insights-seo-aeo: written only by the ingest/suggestion services.
from apps.api.models.ad_connection import AdConnection  # noqa: F401,E402  # FK target of ad_performance_daily
from apps.api.models.ad_performance import AdPerformanceDaily  # noqa: F401,E402
from apps.api.models.content_opportunity import ContentOpportunity  # noqa: F401,E402
