"""environments get an id: versions and suite runs refer to them by it, never by name

An environment's name may change (a mash-up given a curated name, say), so nothing may hold it as a reference: the
environment gets a surrogate primary key, its name becomes a unique column, its versions point at the id, and a suite
run stores the ids of the versions it ran in instead of {name: number}.

Idempotent: a database whose tables `create_all` has just made already has the new shape.

Revision ID: c3e8a1d5f904
Revises: 9a5c3e7f1b42
Create Date: 2026-10-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c3e8a1d5f904"
down_revision: str | Sequence[str] | None = "9a5c3e7f1b42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns WHERE table_name = 'environment' AND column_name = 'id'
  ) THEN
    ALTER TABLE environment ADD COLUMN id SERIAL;
    ALTER TABLE environment_version ADD COLUMN environment_id INTEGER;
    UPDATE environment_version v SET environment_id = e.id FROM environment e WHERE e.name = v.environment;
    ALTER TABLE environment_version ALTER COLUMN environment_id SET NOT NULL;
    ALTER TABLE environment_version DROP CONSTRAINT IF EXISTS uq_environment_version_number;
    ALTER TABLE environment_version DROP CONSTRAINT IF EXISTS uq_environment_version_simulator;
    -- drops its foreign key to environment.name and its index with it
    ALTER TABLE environment_version DROP COLUMN environment;
    ALTER TABLE environment DROP CONSTRAINT environment_pkey;
    ALTER TABLE environment ADD PRIMARY KEY (id);
    ALTER TABLE environment ADD CONSTRAINT environment_name_key UNIQUE (name);
    ALTER TABLE environment_version
      ADD CONSTRAINT environment_version_environment_id_fkey FOREIGN KEY (environment_id) REFERENCES environment (id);
    CREATE INDEX IF NOT EXISTS ix_environment_version_environment_id ON environment_version (environment_id);
    ALTER TABLE environment_version ADD CONSTRAINT uq_environment_version_number UNIQUE (environment_id, number);
    ALTER TABLE environment_version
      ADD CONSTRAINT uq_environment_version_simulator UNIQUE (environment_id, simulator_id);
  END IF;

  ALTER TABLE suite_run ADD COLUMN IF NOT EXISTS environment_version_ids JSONB NOT NULL DEFAULT '[]'::jsonb;
  IF EXISTS (
    SELECT 1 FROM information_schema.columns WHERE table_name = 'suite_run' AND column_name = 'environment_versions'
  ) THEN
    UPDATE suite_run s SET environment_version_ids = COALESCE((
      SELECT jsonb_agg(v.id ORDER BY v.id)
      FROM jsonb_each_text(s.environment_versions) AS named (name, number)
      JOIN environment e ON e.name = named.name
      JOIN environment_version v ON v.environment_id = e.id AND v.number = named.number::integer
    ), '[]'::jsonb);
    ALTER TABLE suite_run DROP COLUMN environment_versions;
  END IF;
END
$$;
""")


def downgrade() -> None:
    for statement in (
        """ALTER TABLE suite_run ADD COLUMN IF NOT EXISTS environment_versions JSONB NOT NULL DEFAULT '{}'::jsonb""",
        """UPDATE suite_run s SET environment_versions = COALESCE((
  SELECT jsonb_object_agg(e.name, v.number)
  FROM jsonb_array_elements_text(s.environment_version_ids) AS ids (id)
  JOIN environment_version v ON v.id = ids.id::integer
  JOIN environment e ON e.id = v.environment_id
), '{}'::jsonb)""",
        """ALTER TABLE suite_run DROP COLUMN IF EXISTS environment_version_ids""",
        """ALTER TABLE environment_version ADD COLUMN IF NOT EXISTS environment VARCHAR(64)""",
        """UPDATE environment_version v SET environment = e.name FROM environment e WHERE e.id = v.environment_id""",
        """ALTER TABLE environment_version DROP CONSTRAINT IF EXISTS uq_environment_version_number""",
        """ALTER TABLE environment_version DROP CONSTRAINT IF EXISTS uq_environment_version_simulator""",
        """ALTER TABLE environment_version DROP COLUMN IF EXISTS environment_id""",
        """ALTER TABLE environment DROP CONSTRAINT IF EXISTS environment_name_key""",
        """ALTER TABLE environment DROP CONSTRAINT environment_pkey""",
        """ALTER TABLE environment ADD PRIMARY KEY (name)""",
        """ALTER TABLE environment DROP COLUMN id""",
        """ALTER TABLE environment_version ALTER COLUMN environment SET NOT NULL""",
        """ALTER TABLE environment_version ADD CONSTRAINT environment_version_environment_fkey
  FOREIGN KEY (environment) REFERENCES environment (name)""",
        """ALTER TABLE environment_version ADD CONSTRAINT uq_environment_version_number UNIQUE (environment, number)""",
        """ALTER TABLE environment_version ADD CONSTRAINT uq_environment_version_simulator UNIQUE (environment, simulator_id)""",
    ):
        op.execute(statement)
