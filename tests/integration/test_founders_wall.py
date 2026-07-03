"""Founders wall roster: waitlist X-handle claims + Clerk-synced accounts.

The public /demo/founders endpoint merges two sources:
1. Waitlist signups that opted in with an X handle (linked tiles).
2. Registered accounts from the users table (anonymous initials tiles,
   derived from full name or email local part — never exposing PII).
"""

import pytest


@pytest.mark.asyncio
async def test_founders_wall_merges_waitlist_and_accounts(test_client, test_db):
    from apps.api.models.user import User
    from apps.api.models.waitlist import WaitlistSignup

    # Waitlist: one opted-in claim, one plain signup without a handle.
    test_db.add(WaitlistSignup(email="claimer@test.com", x_handle="claimer"))
    test_db.add(WaitlistSignup(email="lurker@test.com"))
    # Accounts: one duplicating the claim, one duplicating the plain signup,
    # one brand-new (never waitlisted), one with a full name.
    test_db.add(User(email="claimer@test.com"))
    test_db.add(User(email="lurker@test.com"))
    test_db.add(User(email="fresh.person@test.com"))
    test_db.add(User(email="named@test.com", full_name="Anh Thu Pham"))
    await test_db.commit()

    resp = await test_client.get("/api/v1/demo/founders")
    assert resp.status_code == 200
    data = resp.json()

    assert data["spots"] == 100
    # 2 waitlist signups + 2 accounts that never touched the waitlist.
    assert data["claimed"] == 4

    founders = data["founders"]
    handles = [f["handle"] for f in founders if "handle" in f]
    initials = {f["initials"] for f in founders if "initials" in f}

    # Handle tile first; the claimer's account row must NOT add a second tile.
    assert handles == ["claimer"]
    # lurker -> LU, fresh.person -> FP, "Anh Thu Pham" -> AT
    assert initials == {"LU", "FP", "AT"}
    # Positions are sequential with handle tiles leading.
    assert [f["position"] for f in founders] == list(range(len(founders)))
    assert "handle" in founders[0]

    # Public endpoint must never leak emails or full names.
    body = resp.text.lower()
    assert "@test.com" not in body
    assert "anh thu pham" not in body


@pytest.mark.asyncio
async def test_founders_wall_empty_db(test_client, test_db):
    resp = await test_client.get("/api/v1/demo/founders")
    assert resp.status_code == 200
    data = resp.json()
    assert data["claimed"] == 0
    assert data["founders"] == []
