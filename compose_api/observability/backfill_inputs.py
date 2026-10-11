"""Register the submitted input of simulations that ran before the job script announced it (``announce_input``).

A one-off, safe to repeat: it only adds an ``input`` dataset to a simulation that reached SLURM and has none, reading
the file from the experiment directory on the mounted store, as the dataset routes do. Run it in the API pod:

    python -m compose_api.observability.backfill_inputs
"""

import asyncio
import hashlib
import logging
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from compose_api.common.gateway.models import Namespace
from compose_api.config import get_settings
from compose_api.db.database_service import DatabaseService
from compose_api.observability.datasets import INPUT_KIND, ORIGIN_MANIFEST, ArtifactRecord
from compose_api.simulation.hpc_utils import get_internal_experiment_dir
from compose_api.simulation.models import SimulationFileType

logger = logging.getLogger(__name__)

# Each simulation's latest run that reached SLURM, for simulations with no input dataset yet.
_MISSING = text("""
    SELECT s.id, s.experiment_id, max(h.id)
    FROM simulation s
    JOIN hpcrun h ON h.simulation_id = s.id AND h.job_type = 'SIMULATION' AND h.slurmjobid IS NOT NULL
    WHERE NOT EXISTS (SELECT 1 FROM dataset d WHERE d.simulation_id = s.id AND d.kind = :kind)
    GROUP BY s.id, s.experiment_id
    ORDER BY s.id
""")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def input_record(experiment_dir: Path, experiment_id: str) -> ArtifactRecord | None:
    """The input file the job ran (``<experiment_id>.<suffix>``), or None if the directory has none."""
    for suffix in sorted({t.get_files_suffix() for t in SimulationFileType}):
        path = experiment_dir / f"{experiment_id}.{suffix}"
        if path.is_file():
            return ArtifactRecord(
                path=path.name,
                origin=ORIGIN_MANIFEST,
                kind=INPUT_KIND,
                display_name="Simulation input",
                size_bytes=path.stat().st_size,
                sha256=_sha256(path),
                attributes={"file_type": suffix},
            )
    return None


async def backfill_inputs(engine: AsyncEngine, database_service: DatabaseService) -> tuple[int, int]:
    """Register every missing input that is still on the store; (registered, not found)."""
    namespace = Namespace(get_settings().namespace)
    async with engine.connect() as conn:
        missing = (await conn.execute(_MISSING, {"kind": INPUT_KIND})).tuples().all()
    registered = not_found = 0
    for simulation_id, experiment_id, hpcrun_id in missing:
        experiment_dir = get_internal_experiment_dir(experiment_id, namespace)
        record = await asyncio.to_thread(input_record, experiment_dir, experiment_id)
        if record is None:
            not_found += 1
            continue
        await database_service.get_datasets_db().register(simulation_id, hpcrun_id, [record])
        registered += 1
    return registered, not_found


async def _main() -> None:
    # Only the database: init_standalone would also start a job monitor, polling SLURM beside the API's own.
    from compose_api.db.database_service import DatabaseServiceSQL
    from compose_api.dependencies import get_async_engine

    s = get_settings()
    engine = get_async_engine(
        f"postgresql+asyncpg://{s.postgres_user}:{s.postgres_password}@{s.postgres_host}:{s.postgres_port}/{s.postgres_database}"
    )
    try:
        registered, not_found = await backfill_inputs(engine, DatabaseServiceSQL(async_engine=engine))
        logger.warning(f"Registered {registered} inputs; {not_found} simulations have no input file on the store.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(_main())
