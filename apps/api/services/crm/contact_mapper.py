"""Map segment visitor rows → provider-agnostic CRMContact objects.

Reuses `_get_segment_visitors` from services/csv_exporter.py as the single
source of truth for row shaping AND the compliance guards (skips do_not_email
and "do_not_sell" suppressed contacts) — critical for an outbound push.
"""

from apps.api.services.crm.base import CRMContact

# CRMContact attributes that a field_mapping may remap onto a different source
# key in the visitor row. Empty mapping = identity (default).
_CONTACT_FIELDS = [
    "email",
    "first_name",
    "last_name",
    "phone",
    "company_name",
    "job_title",
    "city",
    "region",
    "country",
]


def visitor_to_contact(row: dict, field_mapping: dict | None = None) -> CRMContact:
    fm = field_mapping or {}
    values = {attr: (row.get(fm.get(attr, attr)) or "") for attr in _CONTACT_FIELDS}
    return CRMContact(**values)


def rows_to_contacts(rows: list[dict], field_mapping: dict | None = None) -> list[CRMContact]:
    return [visitor_to_contact(r, field_mapping) for r in rows]
