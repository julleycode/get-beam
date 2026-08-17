"""AC-2a / AC-3 / AC-10 — the {{booking_link}} token and its validator.

AC-2a: the token resolves in _personalize, _compose_generic, and
       _compose_for_recipient (both branches).
AC-3:  unset -> resolved to "" (never the literal "None"); both brace forms;
       and when SET the URL emerges from _personalize byte-for-byte, because
       _tidy runs AFTER substitution.
AC-10: the booking_url validator rejects non-http(s) schemes, < > " ' ), any
       whitespace, and values over 500 chars.
"""

import pytest
from pydantic import ValidationError

from apps.api.services.campaign_sender import (
    _compose_for_recipient,
    _compose_generic,
    _personalize,
)
from apps.api.schemas.sites import SiteUpdate

pytestmark = pytest.mark.unit

_URL = "https://cal.com/acme"


# ─────────────────────────── AC-2a: resolution ───────────────────────────


def test_personalize_renders_booking_link():
    out = _personalize("Book: {{booking_link}}", "Ada Lovelace", "Acme", "Sam", _URL)
    assert _URL in out


def test_personalize_renders_single_brace_form():
    """_LEFTOVER_TOKEN only strips the DOUBLE-brace form, so the single-brace
    form an LLM emits when escaping slips must be resolved explicitly."""
    out = _personalize("Book: {booking_link}", "Ada", "Acme", "Sam", _URL)
    assert _URL in out
    assert "{booking_link}" not in out


def test_compose_generic_renders_booking_link():
    """The non-verified branch must render it identically — booking_url is
    Beam-customer first-party data, not a guess about the recipient."""
    out = _compose_generic("Book: {{booking_link}}", "Sam", _URL)
    assert _URL in out


@pytest.mark.parametrize("identity_status", ["identified", "candidate", None])
def test_compose_for_recipient_renders_in_both_branches(identity_status):
    subject, body = _compose_for_recipient(
        identity_status,
        "Chat? {{booking_link}}",
        "Book here: {{booking_link}}",
        "Ada Lovelace",
        "Acme",
        "Sam",
        booking_url=_URL,
    )
    assert _URL in subject
    assert _URL in body


# ───────────────────────── AC-3: unset + integrity ─────────────────────────


@pytest.mark.parametrize("unset", [None, "", "   "])
def test_unset_booking_url_resolves_to_empty_never_none(unset):
    out = _personalize("Book: {{booking_link}} now", "Ada", "Acme", "Sam", unset)
    assert "None" not in out
    assert "booking_link" not in out


def test_unset_mid_sentence_leaves_readable_prose():
    out = _personalize(
        "Happy to chat {{booking_link}} whenever suits.", "Ada", "Acme", "Sam", None
    )
    assert "Happy to chat whenever suits." in out


def test_unset_single_brace_form_also_resolved():
    """_LEFTOVER_TOKEN cannot strip the single-brace form — it must be resolved
    or it ships as literal text in an outbound email."""
    out = _personalize("Book: {booking_link}", "Ada", "Acme", "Sam", None)
    assert "booking_link" not in out
    assert "{" not in out


def test_anchor_form_is_documented_bare_url_only():
    """The token is documented as bare-URL-only. When SET, the anchor form still
    yields a working href; when UNSET it yields href="" — the documented
    consequence of wrapping a bare-URL token in an anchor."""
    set_out = _personalize(
        '<a href="{{booking_link}}">Book</a>', "Ada", "Acme", "Sam", _URL
    )
    assert f'href="{_URL}"' in set_out

    unset_out = _personalize(
        '<a href="{{booking_link}}">Book</a>', "Ada", "Acme", "Sam", None
    )
    assert 'href=""' in unset_out
    assert "None" not in unset_out


def test_resolved_url_survives_tidy_byte_for_byte():
    """_personalize ends `return _tidy(out)`, so _tidy post-processes the
    SUBSTITUTED value. _LEFTOVER_HINT deletes lowercase-led [...] spans and
    _HOLLOW_PARENS / whitespace collapse also act on it. One generic assertion
    catches any _tidy mangling class."""
    gnarly = "https://cal.com/acme/[team](x)/book."
    out = _personalize("Book: {{booking_link}}", "Ada", "Acme", "Sam", gnarly)
    assert gnarly in out


# ────────────────────────── AC-10: validator ──────────────────────────


def test_valid_booking_url_accepted():
    assert SiteUpdate(booking_url=_URL).booking_url == _URL


@pytest.mark.parametrize(
    "hostile",
    [
        "javascript:alert(1)",          # non-http(s) scheme
        "data:text/html,<b>x</b>",      # non-http(s) scheme
        "cal.com/acme",                 # scheme-less / not absolute
        'https://x.com/"><script>',     # HTML-injection surface
        "https://x.com/<b>",
        "https://x.com/a'b",
        "https://x.com/a)b",            # _URL_RE terminator
        "https://x.com/a b",            # whitespace terminator
        "https://x.com/a\tb",
        "https://x.com/" + "a" * 500,   # 501+ chars
    ],
)
def test_hostile_booking_url_rejected(hostile):
    with pytest.raises(ValidationError):
        SiteUpdate(booking_url=hostile)


def test_blank_booking_url_normalizes_to_none():
    assert SiteUpdate(booking_url="   ").booking_url is None
