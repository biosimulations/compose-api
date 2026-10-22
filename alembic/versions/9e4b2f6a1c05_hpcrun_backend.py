"""Run backend and external id

Adds ``hpcrun.backend`` (``slurm`` for every existing run) and ``hpcrun.external_id`` (the job's id on its backend,
backfilled from ``slurmjobid``): builds and runs may run elsewhere than SLURM (docs/plan-environment-builds.md, E1).

Idempotent (``IF NOT EXISTS``): a database ``create_all`` built from the current models already has them.

Revision ID: 9e4b2f6a1c05
Revises: 7c2d4e9a1b38
Create Date: 2026-10-13 10:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "9e4b2f6a1c05"
down_revision: str | Sequence[str] | None = "7c2d4e9a1b38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE hpcrun ADD COLUMN IF NOT EXISTS backend VARCHAR(16) NOT NULL DEFAULT 'slurm'")
    op.execute("ALTER TABLE hpcrun ADD COLUMN IF NOT EXISTS external_id VARCHAR")
    op.execute("UPDATE hpcrun SET external_id = slurmjobid::text WHERE external_id IS NULL AND slurmjobid IS NOT NULL")
    op.execute("CREATE INDEX IF NOT EXISTS ix_hpcrun_backend ON hpcrun (backend)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_hpcrun_backend")
    op.execute("ALTER TABLE hpcrun DROP COLUMN IF EXISTS external_id")
    op.execute("ALTER TABLE hpcrun DROP COLUMN IF EXISTS backend")
