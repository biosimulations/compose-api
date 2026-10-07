"""Find simulations: list them, newest first, and describe one with what its run recorded.

Every simulation the caller may read (docs/plan-observability.md O7, O8), with its latest SLURM job. A simulation's id
is what ``POST /simulation/run`` returned as ``simulation_database_id``, and what every other route takes.
"""

import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from compose_api.authentication import get_optional_principal
from compose_api.authorization import OptionalCaller, can_read, readable_clause
from compose_api.common.gateway.models import RouterConfig
from compose_api.config import get_settings
from compose_api.db.services.datasets_db import DatasetQuery
from compose_api.db.services.simulators_db import SUBMITTING, SimulationQuery, SimulationRow
from compose_api.dependencies import get_required_database_service
from compose_api.simulation.hpc_utils import get_singularity_hash
from compose_api.simulation.models import (
    SimulationDetail,
    SimulationPage,
    SimulationSummary,
    Visibility,
)
from compose_api.simulation.prebuilt import prebuilt_definition, prebuilt_image_of

config = RouterConfig(router=APIRouter(), prefix="/simulations", dependencies=[Depends(get_optional_principal)])

StatusFilter = Literal[
    "submitting",
    "waiting",
    "queued",
    "pending",
    "running",
    "completed",
    "failed",
    "cancelled",
    "out_of_memory",
    "suspended",
    "timeout",
    "unknown",
]


def _iso(value: datetime.datetime | None) -> str | None:
    if value is None:
        return None
    aware = value if value.tzinfo else value.replace(tzinfo=datetime.UTC)
    return aware.astimezone(datetime.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _simulator_label(container_def: str) -> str | None:
    """The prebuilt simulator's name if the deployment lists its image, else the image; None for a built container."""
    from pbest.utils.input_types import ContainerizationEngine, ContainerizationFileRepr

    image = prebuilt_image_of(
        ContainerizationFileRepr(representation=container_def, containerization_engine=ContainerizationEngine.APPTAINER)
    )
    if image is None:
        return None
    names = {img: name for name, img in get_settings().prebuilt_simulators.items()}
    return names.get(image, image)


def _summary(row: SimulationRow) -> SimulationSummary:
    run = row.run
    return SimulationSummary(
        simulation_id=row.simulation.id,
        created_at=_iso(row.simulation.created_at),
        experiment_id=row.simulation.experiment_id,
        simulator_id=row.simulator.id,
        simulator=_simulator_label(row.simulator.container_def),
        container_def_hash=row.simulator.container_def_hash,
        visibility=Visibility(row.simulation.visibility),
        status=run.status.to_job_status().value if run is not None else SUBMITTING,
        slurm_job_id=run.slurmjobid if run is not None else None,
        start_time=str(run.start_time) if run is not None and run.start_time else None,
        end_time=str(run.end_time) if run is not None and run.end_time else None,
        exit_code=run.exit_code if run is not None else None,
        error_message=run.error_message if run is not None else None,
        trace_id=run.trace_id if run is not None else None,
    )


def _container_hash(simulator: str) -> str:
    """A prebuilt simulator's name as its container definition's hash; anything else is taken as a hash prefix."""
    image = get_settings().prebuilt_simulators.get(simulator)
    return get_singularity_hash(prebuilt_definition(image)) if image is not None else simulator


@config.router.get(
    path="",
    response_model=SimulationPage,
    operation_id="list-simulations",
    tags=["Simulations"],
    summary="List simulations, newest first, each with its latest SLURM job",
)
async def list_simulations(
    caller: OptionalCaller,
    status: Annotated[StatusFilter | None, Query(description="Only simulations in this state")] = None,
    simulator: Annotated[
        str | None,
        Query(description="Only this prebuilt simulator (by name), or container definitions with this hash prefix"),
    ] = None,
    since: Annotated[
        datetime.datetime | None, Query(description="Only simulations created at or after this time")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SimulationPage:
    query = SimulationQuery(
        status=status,
        container_def_hash=_container_hash(simulator) if simulator else None,
        since=since if since is None or since.tzinfo else since.replace(tzinfo=datetime.UTC),
        limit=limit,
        offset=offset,
    )
    rows, total = (
        await get_required_database_service().get_simulator_db().page_simulations(query, readable_clause(caller))
    )
    following = offset + len(rows)
    return SimulationPage(
        simulations=[_summary(r) for r in rows], total=total, next_offset=following if following < total else None
    )


@config.router.get(
    path="/{simulation_id}",
    response_model=SimulationDetail,
    operation_id="get-simulation",
    responses={404: {"description": "The simulation does not exist, or the caller may not read it"}},
    tags=["Simulations"],
    summary="Describe one simulation: its latest SLURM job, and how many events and datasets its run recorded",
)
async def get_simulation(simulation_id: int, caller: OptionalCaller) -> SimulationDetail:
    db = get_required_database_service()
    row = await db.get_simulator_db().get_simulation_row(simulation_id)
    if row is None or not can_read(caller, row.simulation.to_simulation_access()):
        raise HTTPException(status_code=404, detail=f"Simulation with id {simulation_id} not found.")
    summary = _summary(row)
    event_count = await db.get_events_db().count_events(summary.trace_id) if summary.trace_id else 0
    _, dataset_count = await db.get_datasets_db().page(
        DatasetQuery(simulation_id=simulation_id, available=None, limit=1)
    )
    return SimulationDetail(**summary.model_dump(), event_count=event_count, dataset_count=dataset_count)
