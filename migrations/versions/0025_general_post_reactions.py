"""Reactions on General posts become likes

Decision U.3: a post offers one reaction, chosen by its category. General posts
offer "like" (a heart), the others "helpful". Until now the app sent "helpful"
everywhere, so existing reactions on General posts are converted, as the product
owner chose, rather than left to show as likes while stored as something else.

Data only, no schema change. Counts are unaffected: a post's `reaction_count` was
already the total of every kind, and each person keeps their one reaction.

The downgrade does nothing. The kind each reaction had before is not kept, and
"like" on a General post is what the server stores from now on anyway.

Revision ID: 0025
Revises: 0024
Created: 2026-11-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Module-level so a test can run it against real rows.
CONVERT = (
    "UPDATE reactions SET kind = 'like' "
    "WHERE kind <> 'like' "
    "AND post_id IN (SELECT id FROM posts WHERE category = 'general')"
)


def upgrade() -> None:
    op.execute(sa.text(CONVERT))


def downgrade() -> None:
    """Nothing to undo: the earlier kinds were not kept (see the docstring)."""
