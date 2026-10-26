"""mash-ups: an environment's own entries (docs/plan-environment-composition.md, step 7a)

A mash-up is an environment identified by its set of registry entries (D7.6), so `environment.entries` holds them;
declared environments keep theirs in environments.yaml and leave it null.

Revision ID: f6b2c9d4e017
Revises: e5a8b3d1f926
Create Date: 2026-10-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f6b2c9d4e017"
down_revision: str | Sequence[str] | None = "e5a8b3d1f926"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE environment ADD COLUMN IF NOT EXISTS entries JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE environment DROP COLUMN IF EXISTS entries")
