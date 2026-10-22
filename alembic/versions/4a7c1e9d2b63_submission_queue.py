"""The durable submission queue

``create_all`` makes the ``submission`` table (docs/plan-durable-submission.md, Q1). This backfills a row for every
simulation that has none, so the queue holds only runs the worker should take:

- ``submitted`` for a simulation that reached SLURM;
- ``failed`` for one that never did. It was queued in a process's memory, which is gone or going; #256's stale check
  gives it its FAILED run and reason.

Idempotent (``IF NOT EXISTS``, ``NOT EXISTS``), so it is a no-op on a database ``create_all`` built from these models.

Revision ID: 4a7c1e9d2b63
Revises: 9e4b2f6a1c05
Create Date: 2026-10-22 10:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "4a7c1e9d2b63"
down_revision: str | Sequence[str] | None = "9e4b2f6a1c05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_submission_due ON submission (state, priority, created_at)")
    op.execute(
        """
        INSERT INTO submission (simulation_id, state, created_at, updated_at)
        SELECT s.id,
               CASE WHEN EXISTS (
                   SELECT 1 FROM hpcrun h
                   WHERE h.simulation_id = s.id AND h.job_type = 'SIMULATION' AND h.slurmjobid IS NOT NULL
               ) THEN 'submitted' ELSE 'failed' END,
               s.created_at, localtimestamp
        FROM simulation s
        WHERE NOT EXISTS (SELECT 1 FROM submission q WHERE q.simulation_id = s.id)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS submission")
