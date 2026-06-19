"""POST /api/v1/demo/identify — known-device path.

When a fingerprint was already identified on ANY Beam site (a row in the
cross-customer beam_identity_graph), the demo must return that real person
immediately — not punt to "drop your work email". This is the "detect for
real" behavior: device-level should only ask for email when the device is
genuinely unknown.
"""

from datetime import datetime

import pytest

from apps.api.models.beam_identity import BeamIdentityNode
from apps.api.models.visitor import Visitor

FP = "fp2_knowndevice99"
# x-forwarded-for is required — demo_identify returns early when it can't
# resolve a client IP, before the fingerprint lookup runs.
HEADERS = {"x-forwarded-for": "1.2.3.4"}


@pytest.mark.asyncio
async def test_identify_returns_known_person_from_fingerprint(test_db, test_client):
    now = datetime.utcnow()
    test_db.add(
        Visitor(
            site_id="beam_getbeam_fyi",
            visitor_id="vis_known_1",
            first_seen=now,
            last_seen=now,
            fingerprint=FP,
        )
    )
    test_db.add(
        BeamIdentityNode(
            fingerprint=FP,
            email="jordan@acme.com",
            full_name="Jordan Lee",
            confidence_score=0.9,
            source_site_id="beam_getbeam_fyi",
            source_provider="leadpipe",
        )
    )
    await test_db.commit()

    resp = await test_client.post(
        "/api/v1/demo/identify", json={"fingerprint": FP}, headers=HEADERS
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["matched"] is True
    assert data["level"] == "person"
    assert data["email"] == "jordan@acme.com"
    assert data["full_name"] == "Jordan Lee"
    assert "beam_identity_graph" in data["providers_tried"]


@pytest.mark.asyncio
async def test_identify_unknown_device_does_not_fabricate_person(test_client):
    # Fingerprint not in the graph → must NOT return a person-level match.
    resp = await test_client.post(
        "/api/v1/demo/identify", json={"fingerprint": "fp2_unknowndev"}, headers=HEADERS
    )
    assert resp.status_code == 200
    data = resp.json()
    # Either no match, or at most device/company level — never a fabricated person.
    if data.get("matched"):
        assert data.get("level") != "person" or data.get("resolution_provider") != "beam_identity_graph"
