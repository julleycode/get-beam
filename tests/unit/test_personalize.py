"""Unit tests for campaign template personalization + leftover-placeholder tidy."""

from apps.api.services.campaign_sender import _personalize, _tidy


def test_fills_first_and_company_and_signature():
    body = "Hi {{first_name}}, growth at {{company_name}}.\nBest,\n[Your Name]"
    out = _personalize(body, "Dan Martell", "Acme Inc", "Julley Thai")
    assert "Hi Dan," in out
    assert "growth at Acme Inc." in out
    assert "Julley Thai" in out
    assert "{{" not in out and "[Your Name]" not in out


def test_fallbacks_when_data_missing():
    out = _personalize("Hi {{first_name}} at {{company_name}}.", None, None, None)
    assert "Hi there at your company." in out
    assert "The Beam Team" == _personalize("[Your Name]", None)


def test_hollow_parenthetical_from_stripped_placeholder_is_removed():
    # The exact artifact seen live: "(especially in {{industry}})" -> "(especially in )".
    out = _personalize("focus at {{company_name}} (especially in {{industry}}).", "Alex", "Acme")
    assert out == "focus at Acme."
    assert "( )" not in out and "()" not in out and "in )" not in out


def test_legit_parenthetical_is_preserved():
    assert _tidy("Read the guide (see below) today.") == "Read the guide (see below) today."
    assert _tidy("Great in your area (New York) already.") == "Great in your area (New York) already."


def test_lowercase_bracket_hint_stripped_but_signature_kept():
    assert _tidy("Perfect for [their industry] teams.") == "Perfect for teams."
    # Capitalized [Your Name] is handled by _personalize, not _tidy — _tidy leaves it.
    assert "[Your Name]" in _tidy("Best, [Your Name]")


def test_no_leftover_mustache_ever_ships():
    assert "{{" not in _tidy("Hi {{unknown_field}}!")
    # Stripping the token then tidying the orphaned space gives clean "Hi!".
    assert _tidy("Hi {{unknown_field}}!") == "Hi!"


def test_spacing_cleanup():
    assert _tidy("Too    many   spaces .") == "Too many spaces."
