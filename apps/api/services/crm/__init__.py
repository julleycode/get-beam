"""CRM connector factory.

Phase 2 ships generic_webhook + hubspot. Pipedrive/Salesforce (Phase 3) plug
in here with no router/model/schema changes.
"""

from apps.api.services.crm.base import CRMConnector
from apps.api.services.crm.generic_webhook import GenericWebhookConnector
from apps.api.services.crm.hubspot import HubSpotConnector
from apps.api.services.crm.pipedrive import PipedriveConnector
from apps.api.services.crm.salesforce import SalesforceConnector

_CONNECTORS: dict[str, type[CRMConnector]] = {
    "generic_webhook": GenericWebhookConnector,
    "hubspot": HubSpotConnector,
    "pipedrive": PipedriveConnector,
    "salesforce": SalesforceConnector,
}


def get_crm_connector(provider: str) -> CRMConnector:
    cls = _CONNECTORS.get(provider)
    if cls is None:
        raise ValueError(f"Unknown or unsupported CRM provider: {provider}")
    return cls()


def supported_providers() -> set[str]:
    return set(_CONNECTORS.keys())
