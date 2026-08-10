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
