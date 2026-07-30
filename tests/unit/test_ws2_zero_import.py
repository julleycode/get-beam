"""Structural import-graph guard (INNOVATE decision D2, plan constraint risk #3).

WS2 is a PARALLEL detection layer, not one derived from cadence_bot_flag or
agent_classifier. This test asserts — via the AST, so it cannot be fooled by
mocking — that:

  * ws2_session_classifier{,_sweep}.py import NOTHING from cadence_bot_flag.py or
    agent_classifier.py, and
  * cadence_bot_flag{,_sweep}.py and agent_classifier.py import NOTHING from the
    ws2 modules (the reverse direction).

A future refactor that couples the layers fails here loudly instead of silently
collapsing the orthogonality guarantee.
"""

import ast
import pathlib

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SERVICES = _REPO_ROOT / "apps/api/services"

_WS2_MODULES = [
    _SERVICES / "ws2_session_classifier.py",
    _SERVICES / "ws2_session_classifier_sweep.py",
]
_FORBIDDEN_PEERS = ["cadence_bot_flag", "agent_classifier"]
_PEER_MODULES = [
    _SERVICES / "cadence_bot_flag.py",
    _SERVICES / "cadence_bot_flag_sweep.py",
    _SERVICES / "agent_classifier.py",
]


def _imported_module_names(path: pathlib.Path) -> set[str]:
    """Every dotted module name referenced by an import statement in the file."""
    tree = ast.parse(path.read_text(), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


@pytest.mark.parametrize("module", _WS2_MODULES, ids=lambda p: p.name)
def test_ws2_imports_no_forbidden_peer(module):
    imported = _imported_module_names(module)
    for name in imported:
        for peer in _FORBIDDEN_PEERS:
            assert peer not in name, (
                f"{module.name} imports '{name}' referencing '{peer}' — "
                "WS2 must stay a parallel, not derived, layer (INNOVATE D2)"
            )


@pytest.mark.parametrize("module", _PEER_MODULES, ids=lambda p: p.name)
def test_peers_do_not_import_ws2(module):
    imported = _imported_module_names(module)
    for name in imported:
        assert "ws2_session_classifier" not in name, (
            f"{module.name} imports '{name}' referencing ws2 — the reverse "
            "coupling is forbidden too (INNOVATE D2)"
        )
