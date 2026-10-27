"""runs link their version: backfill `simulation.environment_version_id` (docs/plan-webapp-admin.md, step 5c)

A run records its simulator, and since environment versions also the version it ran in. A run recorded before its
simulator became a version (registry_env@1 is simulator 286, which runs used before @1 was recorded) ran in that
version's image all the same, so it gains the link. Only a simulator that is exactly one version's is linked; the
rest stay unlinked. Idempotent: it touches only runs with no version.

Revision ID: a7d4c2e9b513
Revises: f6b2c9d4e017
Create Date: 2026-10-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a7d4c2e9b513"
down_revision: str | Sequence[str] | None = "f6b2c9d4e017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE simulation s SET environment_version_id = sole.id
        FROM (
            SELECT simulator_id, min(id) AS id FROM environment_version
            WHERE simulator_id IS NOT NULL GROUP BY simulator_id HAVING count(*) = 1
        ) AS sole
        WHERE s.environment_version_id IS NULL AND s.simulator_id = sole.simulator_id
        """
    )


def downgrade() -> None:
    # The backfilled links are not told apart from those recorded at submission; they stay, and are true either way.
    pass
