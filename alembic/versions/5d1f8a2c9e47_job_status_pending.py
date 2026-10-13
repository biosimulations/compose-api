"""Add PENDING to the job status enum

``JobStatusDB.PENDING`` was added to the model after ``create_all`` had built the deployed ``jobstatusdb`` type, and
``create_all`` never alters an existing type. So every poll that saw a SLURM job pending failed with "invalid input
value for enum jobstatusdb", which aborted the whole polling pass.

Idempotent (``IF NOT EXISTS``): a database ``create_all`` built from the current models already has the label.
``ADD VALUE`` runs inside the migration's transaction (PostgreSQL 12+); nothing here uses the new label before commit.

Revision ID: 5d1f8a2c9e47
Revises: c41f0b7a9d20
Create Date: 2026-10-11 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "5d1f8a2c9e47"
down_revision: str | Sequence[str] | None = "c41f0b7a9d20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE jobstatusdb ADD VALUE IF NOT EXISTS 'PENDING' AFTER 'FAILED'")


def downgrade() -> None:
    # PostgreSQL cannot drop a label from an enum type; leaving it is harmless to the older models.
    pass
