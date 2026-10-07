"""Observability identity and simulation ownership

Adds the run's trace identity and event-ingest bookkeeping to ``hpcrun``, and owner and visibility to ``simulation``
(docs/plan-observability.md O1, O4, O7).

Idempotent (``IF NOT EXISTS``): a database that ``create_all`` built from the current models already has these
columns, and the startup sequence can reach this revision either way (``compose_api.db.db_utils.create_db``).

Revision ID: c41f0b7a9d20
Revises: eb3903fb35a7
Create Date: 2026-10-07 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "c41f0b7a9d20"
down_revision: str | Sequence[str] | None = "eb3903fb35a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE hpcrun ADD COLUMN IF NOT EXISTS trace_id VARCHAR(32)")
    op.execute("ALTER TABLE hpcrun ADD COLUMN IF NOT EXISTS events_cursor JSONB NOT NULL DEFAULT '{}'::jsonb")
    op.execute("ALTER TABLE hpcrun ADD COLUMN IF NOT EXISTS last_event_at TIMESTAMP WITH TIME ZONE")
    op.execute("ALTER TABLE hpcrun ADD COLUMN IF NOT EXISTS exit_code INTEGER")
    op.execute("CREATE INDEX IF NOT EXISTS ix_hpcrun_trace_id ON hpcrun (trace_id)")
    op.execute("ALTER TABLE simulation ADD COLUMN IF NOT EXISTS owner_sub VARCHAR")
    op.execute("ALTER TABLE simulation ADD COLUMN IF NOT EXISTS visibility VARCHAR NOT NULL DEFAULT 'public'")
    op.execute("CREATE INDEX IF NOT EXISTS ix_simulation_owner_sub ON simulation (owner_sub)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_simulation_owner_sub")
    op.execute("ALTER TABLE simulation DROP COLUMN IF EXISTS visibility")
    op.execute("ALTER TABLE simulation DROP COLUMN IF EXISTS owner_sub")
    op.execute("DROP INDEX IF EXISTS ix_hpcrun_trace_id")
    op.execute("ALTER TABLE hpcrun DROP COLUMN IF EXISTS exit_code")
    op.execute("ALTER TABLE hpcrun DROP COLUMN IF EXISTS last_event_at")
    op.execute("ALTER TABLE hpcrun DROP COLUMN IF EXISTS events_cursor")
    op.execute("ALTER TABLE hpcrun DROP COLUMN IF EXISTS trace_id")
