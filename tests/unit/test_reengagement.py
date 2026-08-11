"""Unit tests for the inactivity lifecycle (remind / auto-pause / install nudge).

No DB and no network: the state machine lives in pure predicate helpers
(`_remind_due` / `_pause_due` / `_nudge_due`) and the emails in pure builders, so
everything worth asserting is reachable without Postgres. The sweep-level tests
drive `record_user_activity` against a fake session.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

# Register EVERY ORM model before anything touches the mappers (same rationale
# as conftest.test_engine — a partial registry blows up on lazy configure).
import apps.api.main  # noqa: F401
from apps.api.config import settings
from apps.api.services import reengagement
from apps.api.services.reengagement import (
    _install_nudge_email,
    _nudge_due,
    _pause_due,
    _paused_email,
    _remind_due,
    _reminder_email,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)


def _ago(**kw) -> datetime:
    return NOW - timedelta(**kw)


# ────────────────────────────── email builders ──────────────────────────────


class TestReminderEmail:
    def test_subject_names_the_count_and_site(self):
        subject, _ = _reminder_email(13, 357, ["Grade Coach"])
        assert subject == (
            "Beam identified 13 visitors on Grade Coach while you were away"
        )

    def test_singular_wording(self):
        subject, html = _reminder_email(1, 1, ["Solo"])
        assert "identified 1 visitor on Solo" in subject
        assert "1</strong> new visitor" in html
        assert "new visitors" not in html

    def test_it_mentions_the_auto_pause_without_shouting(self):
        _, html = _reminder_email(3, 9, ["Acme"])
        assert f"{settings.reengagement_pause_after_days} days" in html
        assert "pauses tracking" in html

    def test_cta_points_at_the_frontend(self):
        _, html = _reminder_email(3, 9, ["Acme"])
        assert settings.frontend_url in html

    def test_hostile_site_name_is_escaped(self):
        _, html = _reminder_email(1, 1, ['<script>alert("x")</script>'])
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_no_unsubscribe_text_the_sender_owns_it(self):
        _, html = _reminder_email(3, 9, ["Acme"])
        assert "unsubscribe" not in html.lower()

    def test_sign_off_present(self):
        _, html = _reminder_email(3, 9, ["Acme"])
        assert "&mdash; Beam" in html


class TestPausedEmail:
    def test_subject_says_paused_and_how_to_resume(self):
        subject, _ = _paused_email(["Grade Coach"])
        assert subject == "We paused tracking on Grade Coach — log in to resume"

    def test_body_states_the_tradeoff_plainly(self):
        _, html = _paused_email(["Grade Coach"])
        assert "no longer recorded" in html
        assert "deleted" in html
        assert "just log in" in html.lower()

    def test_multiple_sites_are_all_listed_and_escaped(self):
        _, html = _paused_email(["Acme", "<b>Evil</b>"])
        assert "Acme" in html
        assert "<b>Evil</b>" not in html
        assert "&lt;b&gt;Evil&lt;/b&gt;" in html

    def test_no_unsubscribe_text(self):
        _, html = _paused_email(["Acme"])
        assert "unsubscribe" not in html.lower()


class TestInstallNudgeEmail:
    def test_it_points_at_the_snippet(self):
        subject, html = _install_nudge_email("Acme")
        assert "Acme" in subject
        assert "snippet" in html.lower()
        assert settings.frontend_url in html

    def test_site_name_is_escaped(self):
        _, html = _install_nudge_email('<img src=x onerror="1">')
        assert "<img" not in html
        assert "&lt;img" in html

    def test_no_unsubscribe_text(self):
        _, html = _install_nudge_email("Acme")
        assert "unsubscribe" not in html.lower()


# ──────────────────────────── state machine ────────────────────────────


class TestRemindDue:
    def test_fresh_user_is_not_reminded(self):
        assert _remind_due(NOW, _ago(hours=2), None) is False

    def test_idle_past_threshold_and_never_reminded(self):
        assert _remind_due(NOW, _ago(days=8), None) is True

    def test_exactly_at_the_boundary_is_not_yet_due(self):
        just_under = _ago(days=settings.reengagement_remind_after_days) + timedelta(
            minutes=1
        )
        assert _remind_due(NOW, just_under, None) is False

    def test_outstanding_reminder_suppresses_a_repeat(self):
        """Reminder sent AFTER their last visit -> still outstanding."""
        assert _remind_due(NOW, _ago(days=20), _ago(days=10)) is False

    def test_returned_then_idle_again_re_fires(self):
        """They logged in (last_active moves past the old reminder), went quiet
        again -> the stale stamp no longer counts as outstanding."""
        assert _remind_due(NOW, _ago(days=8), _ago(days=30)) is True


class TestPauseDue:
    def test_idle_but_never_reminded_is_never_paused(self):
        assert _pause_due(NOW, _ago(days=20), None) is False

    def test_reminded_too_recently_waits_for_the_warning_gap(self):
        assert _pause_due(NOW, _ago(days=20), _ago(days=1)) is False

    def test_reminded_long_enough_ago_pauses(self):
        assert _pause_due(NOW, _ago(days=20), _ago(days=4)) is True

    def test_not_idle_enough_yet(self):
        assert _pause_due(NOW, _ago(days=8), _ago(days=1)) is False

    def test_stale_reminder_from_before_their_last_visit_does_not_count(self):
        """They came back after the reminder, then went idle again: the ladder
        restarts at remind, never jumping straight to pause."""
        assert _pause_due(NOW, _ago(days=20), _ago(days=30)) is False

    def test_a_20d_idle_never_reminded_user_reminds_but_does_not_pause(self):
        """The first sweep after enablement can only ever remind."""
        assert _remind_due(NOW, _ago(days=20), None) is True
        assert _pause_due(NOW, _ago(days=20), None) is False


class TestNudgeDue:
    def test_brand_new_site_gets_grace(self):
        assert _nudge_due(NOW, _ago(hours=6), None) is False

    def test_old_enough_and_never_nudged(self):
        assert _nudge_due(NOW, _ago(days=5), None) is True

    def test_once_only(self):
        assert _nudge_due(NOW, _ago(days=90), _ago(days=30)) is False


class TestOwnerCohortExclusions:
    """Every stage shares one exclusion set, enforced in SQL (not in Python, so
    an excluded row is never even fetched)."""

    def test_the_filters_exclude_admins_placeholders_and_inactive_rows(self):
        sql = " ".join(
            str(f.compile(compile_kwargs={"literal_binds": True}))
            for f in reengagement._owner_email_filters()
        )
        assert "users.is_active" in sql
        assert "users.is_admin" in sql
        assert "users.email IS NOT NULL" in sql
        assert "@clerk.user" in sql

    @pytest.mark.parametrize(
        "stage", ["_stage_remind", "_stage_pause", "_stage_install_nudge"]
    )
    def test_every_stage_applies_them(self, stage):
        import inspect

        src = inspect.getsource(getattr(reengagement, stage))
        assert "_owner_email_filters()" in src


# ──────────────────────── activity touch (hot path) ────────────────────────


class _FakeSession:
    def __init__(self, raise_on_execute: bool = False):
        self.statements: list = []
        self.committed = False
        self._raise = raise_on_execute

    async def execute(self, stmt, *a, **kw):
        if self._raise:
            raise RuntimeError("db is on fire")
        self.statements.append(stmt)
        return None

    async def commit(self):
        self.committed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _session_factory(session):
    def factory():
        return session

    return factory


def _user(last_active_at):
    return SimpleNamespace(
        id="11111111-1111-1111-1111-111111111111", last_active_at=last_active_at
    )


@pytest.mark.asyncio
async def test_touch_is_a_no_op_for_a_fresh_user(monkeypatch):
    """Steady state must not open a session at all — one datetime compare."""

    def explode():
        raise AssertionError("async_session must not be opened for a fresh user")

    monkeypatch.setattr(reengagement, "async_session", explode)
    await reengagement.record_user_activity(
        _user(datetime.now(timezone.utc) - timedelta(minutes=5))
    )


@pytest.mark.asyncio
async def test_touch_writes_and_resumes_when_stale(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(reengagement, "async_session", _session_factory(session))
    user = _user(datetime.now(timezone.utc) - timedelta(hours=5))

    await reengagement.record_user_activity(user)

    assert session.committed is True
    assert len(session.statements) == 2
    sqls = [str(s).lower() for s in session.statements]
    assert any("update users" in s and "last_active_at" in s for s in sqls)
    resume = next(s for s in sqls if "update sites" in s)
    assert "tracking_enabled" in resume
    assert "auto_paused_at" in resume
    # The in-memory row is refreshed so a second dependency call in the same
    # request doesn't write again.
    assert user.last_active_at > datetime.now(timezone.utc) - timedelta(minutes=1)


@pytest.mark.asyncio
async def test_touch_only_resumes_sites_it_paused_itself(monkeypatch):
    """A MANUAL pause has a NULL auto_paused_at and must survive a login."""
    session = _FakeSession()
    monkeypatch.setattr(reengagement, "async_session", _session_factory(session))

    await reengagement.record_user_activity(
        _user(datetime.now(timezone.utc) - timedelta(hours=5))
    )

    resume = next(s for s in (str(x) for x in session.statements) if "UPDATE sites" in s)
    assert "auto_paused_at IS NOT NULL" in resume


@pytest.mark.asyncio
async def test_touch_never_raises(monkeypatch):
    """A telemetry write must not be able to 500 an authed request."""
    monkeypatch.setattr(
        reengagement, "async_session", _session_factory(_FakeSession(raise_on_execute=True))
    )
    await reengagement.record_user_activity(
        _user(datetime.now(timezone.utc) - timedelta(days=3))
    )  # must not raise


@pytest.mark.asyncio
async def test_touch_tolerates_a_naive_stamp(monkeypatch):
    """SQLite/legacy rows can hand back a naive datetime; comparing it against
    an aware `now` would raise TypeError inside the hot path."""

    def explode():
        raise AssertionError("should have short-circuited on freshness")

    monkeypatch.setattr(reengagement, "async_session", explode)
    naive_fresh = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5)
    await reengagement.record_user_activity(_user(naive_fresh))


@pytest.mark.asyncio
async def test_touch_handles_a_null_stamp(monkeypatch):
    """Belt-and-braces: the column is NOT NULL, but a partially-constructed row
    must still write rather than crash."""
    session = _FakeSession()
    monkeypatch.setattr(reengagement, "async_session", _session_factory(session))
    await reengagement.record_user_activity(_user(None))
    assert session.committed is True


# ──────────────────────────── sweep orchestration ────────────────────────────


class _SweepSession(_FakeSession):
    """Enough of a session for run_reengagement_sweep's lock handling."""

    async def execute(self, stmt, *a, **kw):
        self.statements.append(stmt)
        return SimpleNamespace(scalar=lambda: True, all=lambda: [], first=lambda: None)

    async def rollback(self):
        pass


@pytest.mark.asyncio
async def test_sweep_short_circuits_when_locked_elsewhere(monkeypatch):
    session = _SweepSession()
    monkeypatch.setattr(reengagement, "async_session", _session_factory(session))
    monkeypatch.setattr(
        reengagement, "_try_acquire_lock", AsyncMock(return_value=False)
    )
    release = AsyncMock()
    monkeypatch.setattr(reengagement, "_release_lock", release)
    remind = AsyncMock()
    monkeypatch.setattr(reengagement, "_stage_remind", remind)

    counts = await reengagement.run_reengagement_sweep()

    assert counts == {"reminded": 0, "paused": 0, "nudged": 0}
    remind.assert_not_awaited()
    release.assert_not_awaited()


@pytest.mark.asyncio
async def test_sweep_proceeds_when_lock_unsupported(monkeypatch):
    """SQLite has no advisory locks — fail open, but never unlock a lock that
    was never taken."""
    monkeypatch.setattr(reengagement, "async_session", _session_factory(_SweepSession()))
    monkeypatch.setattr(reengagement, "_try_acquire_lock", AsyncMock(return_value=None))
    release = AsyncMock()
    monkeypatch.setattr(reengagement, "_release_lock", release)
    monkeypatch.setattr(reengagement, "_stage_remind", AsyncMock(return_value=2))
    monkeypatch.setattr(reengagement, "_stage_pause", AsyncMock(return_value=1))

    counts = await reengagement.run_reengagement_sweep()

    assert counts["reminded"] == 2
    assert counts["paused"] == 1
    release.assert_not_awaited()


@pytest.mark.asyncio
async def test_sweep_runs_remind_before_pause(monkeypatch):
    """Order matters: a user reminded in this same run must not also be paused
    by it (the warning gap predicate enforces that, but the ordering makes the
    intent explicit)."""
    order: list[str] = []
    monkeypatch.setattr(reengagement, "async_session", _session_factory(_SweepSession()))
    monkeypatch.setattr(reengagement, "_try_acquire_lock", AsyncMock(return_value=True))
    monkeypatch.setattr(reengagement, "_release_lock", AsyncMock())

    async def remind(*a, **kw):
        order.append("remind")
        return 0

    async def pause(*a, **kw):
        order.append("pause")
        return 0

    monkeypatch.setattr(reengagement, "_stage_remind", remind)
    monkeypatch.setattr(reengagement, "_stage_pause", pause)

    await reengagement.run_reengagement_sweep()
    assert order == ["remind", "pause"]


@pytest.mark.asyncio
async def test_install_nudge_stage_is_flag_gated(monkeypatch):
    monkeypatch.setattr(settings, "reengagement_install_nudge_enabled", False)
    monkeypatch.setattr(reengagement, "async_session", _session_factory(_SweepSession()))
    monkeypatch.setattr(reengagement, "_try_acquire_lock", AsyncMock(return_value=True))
    monkeypatch.setattr(reengagement, "_release_lock", AsyncMock())
    monkeypatch.setattr(reengagement, "_stage_remind", AsyncMock(return_value=0))
    monkeypatch.setattr(reengagement, "_stage_pause", AsyncMock(return_value=0))
    nudge = AsyncMock(return_value=3)
    monkeypatch.setattr(reengagement, "_stage_install_nudge", nudge)

    counts = await reengagement.run_reengagement_sweep()
    assert counts["nudged"] == 0
    nudge.assert_not_awaited()

    monkeypatch.setattr(settings, "reengagement_install_nudge_enabled", True)
    counts = await reengagement.run_reengagement_sweep()
    assert counts["nudged"] == 3


@pytest.mark.asyncio
async def test_sweep_releases_the_lock_it_acquired(monkeypatch):
    monkeypatch.setattr(reengagement, "async_session", _session_factory(_SweepSession()))
    monkeypatch.setattr(reengagement, "_try_acquire_lock", AsyncMock(return_value=True))
    release = AsyncMock()
    monkeypatch.setattr(reengagement, "_release_lock", release)
    monkeypatch.setattr(
        reengagement, "_stage_remind", AsyncMock(side_effect=RuntimeError("boom"))
    )

    with pytest.raises(RuntimeError):
        await reengagement.run_reengagement_sweep()
    release.assert_awaited_once()


# ─────────────────────────── flags ship OFF ───────────────────────────


def test_every_lifecycle_flag_defaults_off():
    """Repo posture: schema-applied != feature-enabled."""
    from apps.api.config import Settings

    fresh = Settings.model_fields
    assert fresh["reengagement_enabled"].default is False
    assert fresh["reengagement_install_nudge_enabled"].default is False
    assert fresh["reengagement_remind_after_days"].default == 7
    assert fresh["reengagement_pause_after_days"].default == 14
    assert fresh["reengagement_pause_warning_min_days"].default == 3


# ───────────────── stage-level invariants (scripted fake session) ─────────────────


class _ScriptedSession:
    """Returns queued results in order, recording commits/rollbacks.

    Each queued item is either a list (becomes .all()/.first()) or a scalar.
    """

    def __init__(self, queue):
        self._queue = list(queue)
        self.commits = 0
        self.rollbacks = 0
        self.statements: list = []

    async def execute(self, stmt, *a, **kw):
        self.statements.append(stmt)
        value = self._queue.pop(0) if self._queue else []
        if isinstance(value, list):
            return SimpleNamespace(
                all=lambda: value,
                first=lambda: (value[0] if value else None),
                scalar=lambda: (value[0] if value else None),
            )
        return SimpleNamespace(
            all=lambda: [], first=lambda: None, scalar=lambda: value
        )

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


class _Sender:
    _UNSET = object()

    def __init__(self, result=_UNSET, raises=False):
        # `result=None` must mean SUPPRESSED, not "use the default" — that
        # distinction is the whole point of these tests.
        self._result = {"ok": True} if result is _Sender._UNSET else result
        self._raises = raises
        self.calls: list = []

    async def send(self, **kw):
        self.calls.append(kw)
        if self._raises:
            raise RuntimeError("sendgrid exploded")
        return self._result


@pytest.mark.asyncio
async def test_remind_skips_and_does_not_stamp_when_nothing_happened():
    """No new visitors and no identifications while they were away: no email,
    and crucially NO stamp — an unstamped user can never become pause-eligible,
    so a dead site never gets 'warned' about a pause it will never receive."""
    db = _ScriptedSession(
        [
            [("u1", "dana@acme.com", NOW - timedelta(days=10))],  # cohort
            [("site-1", "Acme")],  # their live sites
            0,  # identified count
            0,  # new visitor count
        ]
    )
    sender = _Sender()
    sent = await reengagement._stage_remind(db, sender, NOW)

    assert sent == 0
    assert sender.calls == []
    assert db.commits == 0


@pytest.mark.asyncio
async def test_remind_stamps_only_after_a_real_send():
    db = _ScriptedSession(
        [
            [("u1", "dana@acme.com", NOW - timedelta(days=10))],
            [("site-1", "Acme")],
            13,
            357,
            [],  # the UPDATE users ... stamp
        ]
    )
    sender = _Sender()
    sent = await reengagement._stage_remind(db, sender, NOW)

    assert sent == 1
    assert sender.calls[0]["to_email"] == "dana@acme.com"
    # db= is passed so the suppression gate runs; branding on (owner-facing).
    assert sender.calls[0]["db"] is db
    assert sender.calls[0]["branding"] is True
    assert db.commits == 1
    assert "last_reengagement_sent_at" in str(db.statements[-1])


@pytest.mark.asyncio
async def test_remind_does_not_stamp_a_suppressed_recipient():
    """send() -> None means unsubscribed/bounced. No stamp, so this user can
    never satisfy the pause predicate — the confirmed 'no pause without a
    deliverable warning' rule, enforced one stage earlier."""
    db = _ScriptedSession(
        [
            [("u1", "dana@acme.com", NOW - timedelta(days=10))],
            [("site-1", "Acme")],
            5,
            9,
        ]
    )
    sender = _Sender(result=None)
    sent = await reengagement._stage_remind(db, sender, NOW)

    assert sent == 0
    assert db.commits == 0
    assert db.rollbacks == 1


@pytest.mark.asyncio
async def test_pause_commits_and_stamps_naive():
    db = _ScriptedSession(
        [
            [("u1", "dana@acme.com")],  # cohort
            [("Acme",)],  # guarded UPDATE ... RETURNING name
        ]
    )
    sender = _Sender()
    paused = await reengagement._stage_pause(db, sender, NOW)

    assert paused == 1
    assert db.commits == 1
    update_sql = str(db.statements[1])
    assert "tracking_enabled" in update_sql and "auto_paused_at" in update_sql
    # `sites` is a naive-UTC table; an aware value would be a silent tz bug.
    params = db.statements[1].compile().params
    stamp = params.get("auto_paused_at")
    assert stamp is not None and stamp.tzinfo is None


@pytest.mark.asyncio
async def test_pause_rolls_back_for_a_suppressed_recipient():
    """Nobody is paused silently: if the notice can't be delivered, the pause
    is rolled back and the sites stay live."""
    db = _ScriptedSession([[("u1", "dana@acme.com")], [("Acme",)]])
    sender = _Sender(result=None)

    paused = await reengagement._stage_pause(db, sender, NOW)

    assert paused == 0
    assert db.commits == 0
    assert db.rollbacks == 1


@pytest.mark.asyncio
async def test_pause_rolls_back_when_the_send_raises():
    """Pause + notice are atomic: a transport failure leaves tracking ON and the
    whole thing is simply retried tomorrow."""
    db = _ScriptedSession([[("u1", "dana@acme.com")], [("Acme",)]])
    sender = _Sender(raises=True)

    paused = await reengagement._stage_pause(db, sender, NOW)

    assert paused == 0
    assert db.commits == 0
    assert db.rollbacks == 1


@pytest.mark.asyncio
async def test_pause_is_a_no_op_when_the_guarded_update_matches_nothing():
    """The guarded UPDATE re-checks inactivity at write time. If the owner
    logged in between the SELECT and the UPDATE, zero rows come back and no
    email is sent."""
    db = _ScriptedSession([[("u1", "dana@acme.com")], []])
    sender = _Sender()

    paused = await reengagement._stage_pause(db, sender, NOW)

    assert paused == 0
    assert sender.calls == []
    assert db.rollbacks == 1


@pytest.mark.asyncio
async def test_install_nudge_skips_accounts_whose_pixel_did_fire():
    """Events exist -> this is not an install problem. No email, and the
    once-only stamp is NOT burned."""
    db = _ScriptedSession(
        [
            [("u1", "dana@acme.com")],  # cohort
            [("site-1", "Acme")],  # their sites
            [1],  # an event exists
        ]
    )
    sender = _Sender()
    nudged = await reengagement._stage_install_nudge(db, sender, NOW)

    assert nudged == 0
    assert sender.calls == []
    assert db.commits == 0


@pytest.mark.asyncio
async def test_install_nudge_sends_once_and_stamps():
    db = _ScriptedSession(
        [
            [("u1", "dana@acme.com")],
            [("site-1", "Acme")],
            [],  # no events at all
            [],  # the UPDATE users ... stamp
        ]
    )
    sender = _Sender()
    nudged = await reengagement._stage_install_nudge(db, sender, NOW)

    assert nudged == 1
    assert db.commits == 1
    assert "install_nudge_sent_at" in str(db.statements[-1])


def test_manual_tracking_toggle_clears_the_auto_pause_stamp():
    """PATCH /sites/{id} — an explicit owner write in EITHER direction clears
    auto_paused_at, so a deliberately-paused site is never surprise-resumed by
    the next login."""
    import pathlib

    src = (
        pathlib.Path(reengagement.__file__).resolve().parents[1]
        / "routers"
        / "sites.py"
    ).read_text(encoding="utf-8")
    branch = src.split("if body.tracking_enabled is not None:")[1].split("if body.")[0]
    assert "site.tracking_enabled = body.tracking_enabled" in branch
    assert "site.auto_paused_at = None" in branch
