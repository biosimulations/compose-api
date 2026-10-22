"""Suite runs that resume

Adds a suite run's progress (docs/plan-durable-submission.md, Q4): ``sources``, ``next_source``, and the lease of the
submission worker submitting it. A run left ``submitting`` by the pre-queue code has no sources recorded; the worker
finds nothing left to submit and marks it ``submitted``.

Idempotent (``IF NOT EXISTS``): a database ``create_all`` built from the current models already has them.

Revision ID: 6d2e8b4f1a97
Revises: 4a7c1e9d2b63
Create Date: 2026-10-22 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "6d2e8b4f1a97"
down_revision: str | Sequence[str] | None = "4a7c1e9d2b63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE suite_run ADD COLUMN IF NOT EXISTS sources JSONB NOT NULL DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE suite_run ADD COLUMN IF NOT EXISTS next_source INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE suite_run ADD COLUMN IF NOT EXISTS lease_owner VARCHAR")
    op.execute("ALTER TABLE suite_run ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMP WITHOUT TIME ZONE")


def downgrade() -> None:
    for column in ("lease_expires_at", "lease_owner", "next_source", "sources"):
        op.execute(f"ALTER TABLE suite_run DROP COLUMN IF EXISTS {column}")
