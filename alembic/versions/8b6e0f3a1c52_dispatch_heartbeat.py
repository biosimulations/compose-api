"""Simulation dispatch heartbeat

Adds ``simulation.dispatch_heartbeat_at``, written by the task that submits a simulation until it reaches SLURM. The
job monitor fails a submission whose heartbeat went stale, so a run whose task was lost (an API restart, #238) stops
looking alive forever.

Idempotent (``IF NOT EXISTS``): a database ``create_all`` built from the current models already has the column.

Revision ID: 8b6e0f3a1c52
Revises: 5d1f8a2c9e47
Create Date: 2026-10-11 14:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "8b6e0f3a1c52"
down_revision: str | Sequence[str] | None = "5d1f8a2c9e47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # TIMESTAMP WITHOUT TIME ZONE, like simulation.created_at, so the two compare in SQL.
    op.execute("ALTER TABLE simulation ADD COLUMN IF NOT EXISTS dispatch_heartbeat_at TIMESTAMP WITHOUT TIME ZONE")


def downgrade() -> None:
    op.execute("ALTER TABLE simulation DROP COLUMN IF EXISTS dispatch_heartbeat_at")
