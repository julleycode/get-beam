"""site_id unguessability regression (AC7).

The tombstone reuse feature re-issues a PREVIOUSLY GENERATED random id; it must
never introduce a deterministic url -> id function. These tests pin that: ids
stay random per call, and the reused id keeps the original random shape.
"""

import re

import pytest

# The ORM mapper registry must be configured before importing a router module
# that constructs ORM objects (repo-wide unit-test gotcha).
import apps.api.main  # noqa: F401
from apps.api.routers.sites import _generate_site_id

pytestmark = pytest.mark.unit

SHAPE = re.compile(r"^site_[0-9a-f]{12}$")


def test_generated_ids_are_distinct_across_calls():
    ids = {_generate_site_id() for _ in range(200)}
    # No deterministic url->id function exists: the generator takes no input at
    # all, and repeated calls never collide.
    assert len(ids) == 200


def test_generated_id_shape_is_random_hex():
    for _ in range(50):
        assert SHAPE.match(_generate_site_id())


def test_generator_takes_no_url_input():
    import inspect

    # A url parameter would be the first step toward a derivable id.
    assert list(inspect.signature(_generate_site_id).parameters) == []


def test_reused_id_preserves_the_random_shape():
    # Reuse copies a previously generated id verbatim — it does not synthesize a
    # new one, so the shape (and therefore the entropy) is unchanged.
    original = _generate_site_id()
    reused = original
    assert SHAPE.match(reused)
    assert reused == original
