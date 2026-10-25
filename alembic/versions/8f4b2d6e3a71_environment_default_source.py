"""Environment default source

Whether an environment's default version is the deployment's own definition (``deployment``, adopted by the run path
since step 2) or one an administrator chose (``api``), which the deployment's definition no longer overrides
(docs/plan-environment-versions.md, step 4).

Idempotent (``IF NOT EXISTS``): a database ``create_all`` built from the current models already has it.

Revision ID: 8f4b2d6e3a71
Revises: 7c3a9e1d5b20
Create Date: 2026-10-25 18:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "8f4b2d6e3a71"
down_revision: str | Sequence[str] | None = "7c3a9e1d5b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE environment ADD COLUMN IF NOT EXISTS default_source VARCHAR(16) NOT NULL DEFAULT 'deployment'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE environment DROP COLUMN IF EXISTS default_source")
