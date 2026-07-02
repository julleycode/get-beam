"""POST /api/v1/demo/identify — fingerprint paths must not leak graph PII.

History: the demo originally returned the real person from the cross-customer
beam_identity_graph when the client-supplied fingerprint matched (b3a41d6).
That was a cross-tenant PII leak — an unauthenticated caller could replay any
fingerprint and receive another tenant's stored name + email — and was removed
in the Phase 6 security fix (7e798ab). The demo now keeps only the
device-level fingerprint *proof* ("the pixel saw this device") and the
resolve-the-caller's-own-IP waterfall.

These tests pin the secure behavior:
- Known device (Visitor row + graph node for the same fingerprint) gets at
  most a device-level match — the graph identity is never echoed.
- Unknown device never gets a fabricated person.

See tests/integration/test_demo_security.py for the node-only leak test.
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
async def test_identify_known_device_matches_without_leaking_graph_pii(
    test_db, test_client
):
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
    # Even with a graph identity stored for this exact fingerprint, the demo
    # must not return it — that path was the cross-tenant leak.
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
    # Fingerprint proof: the pixel saw this device.
    assert data["fingerprint_matched"] is True
    assert "fingerprint" in data["providers_tried"]
    # But never the stored graph identity.
    assert data.get("email") != "jordan@acme.com"
    assert data.get("full_name") != "Jordan Lee"
    assert data.get("resolution_provider") != "beam_identity_graph"
    assert "beam_identity_graph" not in data["providers_tried"]
    # With no provider keys configured the match caps at device level.
    if data.get("matched"):
        assert data["level"] in ("device", "company")


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
