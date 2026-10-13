"""Simulation labels, tags and description

Adds ``simulation.labels`` (JSONB, written by the service), ``simulation.tags`` (the submitter's) and
``simulation.description``, with GIN indexes for containment queries (docs/plan-sedml.md, phase 0).

Idempotent (``IF NOT EXISTS``): a database ``create_all`` built from the current models already has them.

Revision ID: 3f9a6c1e7b24
Revises: 8b6e0f3a1c52
Create Date: 2026-10-12 23:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "3f9a6c1e7b24"
down_revision: str | Sequence[str] | None = "8b6e0f3a1c52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE simulation ADD COLUMN IF NOT EXISTS labels JSONB NOT NULL DEFAULT '{}'::jsonb")
    op.execute("ALTER TABLE simulation ADD COLUMN IF NOT EXISTS tags VARCHAR[] NOT NULL DEFAULT '{}'::varchar[]")
    op.execute("ALTER TABLE simulation ADD COLUMN IF NOT EXISTS description TEXT")
    op.execute("CREATE INDEX IF NOT EXISTS ix_simulation_labels ON simulation USING gin (labels)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_simulation_tags ON simulation USING gin (tags)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_simulation_tags")
    op.execute("DROP INDEX IF EXISTS ix_simulation_labels")
    op.execute("ALTER TABLE simulation DROP COLUMN IF EXISTS description")
    op.execute("ALTER TABLE simulation DROP COLUMN IF EXISTS tags")
    op.execute("ALTER TABLE simulation DROP COLUMN IF EXISTS labels")
