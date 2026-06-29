"""Phase 6 part 2: posts use a per-account composite unique, not a global one.

A global UNIQUE on platform_post_id let one customer's import block every other
customer from importing the same public post. Guard the model metadata so the
constraint can't silently regress to global.
"""

from sqlalchemy import UniqueConstraint

from apps.api.models.post import Post


def test_platform_post_id_not_globally_unique():
    col = Post.__table__.c.platform_post_id
    assert col.unique is not True


def test_composite_unique_on_account_and_post_id():
    uniques = {
        tuple(c.name for c in con.columns)
        for con in Post.__table__.constraints
        if isinstance(con, UniqueConstraint)
    }
    assert ("social_account_id", "platform_post_id") in uniques
