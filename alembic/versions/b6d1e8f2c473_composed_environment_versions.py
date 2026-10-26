"""composed environment versions: resolved in the background, with a failure explanation

docs/plan-environment-composition.md, step 4. A composed version is created `resolving`, before its lock exists, so it
has no simulator until the lock Job finishes; a lock that does not resolve leaves pixi's explanation in `failure`.

Revision ID: b6d1e8f2c473
Revises: c3e8a1d5f904
Create Date: 2026-10-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b6d1e8f2c473"
down_revision: str | Sequence[str] | None = "c3e8a1d5f904"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE environment_version ALTER COLUMN simulator_id DROP NOT NULL")
    op.execute("ALTER TABLE environment_version ADD COLUMN IF NOT EXISTS failure TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE environment_version DROP COLUMN IF EXISTS failure")
    op.execute("DELETE FROM environment_version WHERE simulator_id IS NULL")
    op.execute("ALTER TABLE environment_version ALTER COLUMN simulator_id SET NOT NULL")
