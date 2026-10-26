"""compliance: what the generic checks found in a version, and its entries' case runs

docs/plan-environment-composition.md, step 5b. `environment_version.findings` keeps the generic checks' findings from
its read-back; `compliance_run` (a new table, made by create_all) records each entry's case run in each version.

Revision ID: e5a8b3d1f926
Revises: d4f7a2c9e815
Create Date: 2026-10-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e5a8b3d1f926"
down_revision: str | Sequence[str] | None = "d4f7a2c9e815"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE environment_version ADD COLUMN IF NOT EXISTS findings JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE environment_version DROP COLUMN IF EXISTS findings")
