"""private repositories: the roles a run's readers must hold (docs/plan-private-repo-usage.md, B)

A run in an environment made of a private repository's entry is readable only by callers holding that entry's role,
before its owner and visibility are consulted (compose_api.authorization). `simulation.access_roles` holds them; every
run before this one ran in no private environment, so they keep the empty default.

Revision ID: 83ef5772d093
Revises: a7d4c2e9b513
Create Date: 2026-11-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "83ef5772d093"
down_revision: str | Sequence[str] | None = "a7d4c2e9b513"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE simulation ADD COLUMN IF NOT EXISTS access_roles VARCHAR[] NOT NULL DEFAULT '{}'")


def downgrade() -> None:
    op.execute("ALTER TABLE simulation DROP COLUMN IF EXISTS access_roles")
