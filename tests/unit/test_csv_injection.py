"""Phase 9 remainder: CSV formula-injection guard for plaintext exports."""

import pytest

from apps.api.services.csv_exporter import _csv_safe


@pytest.mark.parametrize("danger", ["=cmd()", "+1", "-2", "@SUM(A1)", "\t=x", "\r=y"])
def test_formula_triggers_are_escaped(danger):
    assert _csv_safe(danger).startswith("'")


@pytest.mark.parametrize("ok", ["Ann", "ann@example.com", "Acme Inc", "", "123 Main St"])
def test_plain_values_unchanged(ok):
    assert _csv_safe(ok) == ok


def test_none_becomes_empty_string():
    assert _csv_safe(None) == ""
