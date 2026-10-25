"""Environment versions

The tables ``environment`` and ``environment_version`` are new, so ``create_all`` creates them before this runs
(compose_api.db.db_utils.create_db). This adds the column that records a simulation's version
(docs/plan-environment-versions.md, step 2). Runs recorded before it have none.

Idempotent (``IF NOT EXISTS``): a database ``create_all`` built from the current models already has it.

Revision ID: 7c3a9e1d5b20
Revises: 6d2e8b4f1a97
Create Date: 2026-10-25 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "7c3a9e1d5b20"
down_revision: str | Sequence[str] | None = "6d2e8b4f1a97"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE simulation ADD COLUMN IF NOT EXISTS environment_version_id INTEGER "
        "REFERENCES environment_version(id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_simulation_environment_version_id ON simulation (environment_version_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_simulation_environment_version_id")
    op.execute("ALTER TABLE simulation DROP COLUMN IF EXISTS environment_version_id")
