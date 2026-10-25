"""Suite run environment versions

The environment versions a suite run's simulations use, ``{environment: number}``
(docs/plan-environment-versions.md, step 5). Runs started before suites named them have none: theirs got the default.

Idempotent (``IF NOT EXISTS``): a database ``create_all`` built from the current models already has it.

Revision ID: 9a5c3e7f1b42
Revises: 8f4b2d6e3a71
Create Date: 2026-10-25 21:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "9a5c3e7f1b42"
down_revision: str | Sequence[str] | None = "8f4b2d6e3a71"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE suite_run ADD COLUMN IF NOT EXISTS environment_versions JSONB NOT NULL DEFAULT '{}'::jsonb"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE suite_run DROP COLUMN IF EXISTS environment_versions")
