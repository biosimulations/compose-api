"""environment versions keep the files that recreate them in other forms (the uv project and lock)

docs/plan-environment-composition.md, step 4b: a composed version that needs nothing from conda-forge is also offered
as a pyproject.toml and uv.lock, made once after it resolves and kept here, by format.

Revision ID: d4f7a2c9e815
Revises: b6d1e8f2c473
Create Date: 2026-10-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d4f7a2c9e815"
down_revision: str | Sequence[str] | None = "b6d1e8f2c473"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE environment_version ADD COLUMN IF NOT EXISTS exports JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE environment_version DROP COLUMN IF EXISTS exports")
