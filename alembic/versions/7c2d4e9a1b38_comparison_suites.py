"""Comparison suite columns

Adds ``comparison.collection`` and ``comparison.suite_run`` (a suite run's comparisons; docs/plan-sedml.md, phase 6).
The ``suite_run`` table is new and arrives through ``create_all``.

Idempotent (``IF NOT EXISTS``): a database ``create_all`` built from the current models already has them.

Revision ID: 7c2d4e9a1b38
Revises: 3f9a6c1e7b24
Create Date: 2026-10-13 08:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "7c2d4e9a1b38"
down_revision: str | Sequence[str] | None = "3f9a6c1e7b24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE comparison ADD COLUMN IF NOT EXISTS collection VARCHAR")
    op.execute("ALTER TABLE comparison ADD COLUMN IF NOT EXISTS suite_run INTEGER")
    op.execute("CREATE INDEX IF NOT EXISTS ix_comparison_collection ON comparison (collection)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_comparison_collection")
    op.execute("ALTER TABLE comparison DROP COLUMN IF EXISTS suite_run")
    op.execute("ALTER TABLE comparison DROP COLUMN IF EXISTS collection")
