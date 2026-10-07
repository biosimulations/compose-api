import logging
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.responses import FileResponse

from compose_api.authorization import OptionalCaller, readable_simulation, readable_simulation_ids
from compose_api.common.gateway.models import Namespace, RouterConfig
from compose_api.common.gateway.utils import get_hpc_run_status
from compose_api.common.ssh.ssh_service import get_ssh_service
from compose_api.config import get_settings
from compose_api.dependencies import (
    get_data_service,
    get_database_service,
    get_required_database_service,
    get_simulation_service,
)
from compose_api.observability.chrome_trace import chrome_trace_document
from compose_api.observability.events import RunEvent, RunEventPage, RunSpan, RunTraceTree, build_span_tree
from compose_api.simulation.models import (
    HpcRun,
    JobType,
    SimulationAccess,
)

logger = logging.getLogger(__name__)

# Declared on every endpoint that resolves a resource by id. Without it the generated
# client has no notion of a 404: configured strictly it raises on one, and by default it
# returns a parsed value of None that a caller can mistake for "no data yet". The server
# has always returned 404 for some of these; the spec simply never said so.
NOT_FOUND_RESPONSE = {"description": "The requested resource does not exist"}

# The simulation named by the `simulation_id` query parameter, if the caller may read it (404 otherwise).
ReadableSimulation = Annotated[SimulationAccess, Depends(readable_simulation)]

# -- app components -- #

config = RouterConfig(router=APIRouter(), prefix="/results", dependencies=[])


@config.router.get(
    path="/simulations/status/batch",
    response_model=list[HpcRun],
    operation_id="get-simulations-status-batch",
    tags=["Results"],
    dependencies=[Depends(get_database_service)],
    summary="Get simulation status records for a list of IDs",
)
async def get_simulations_status_batch(ids: list[int], caller: OptionalCaller) -> list[HpcRun]:
    db_service = get_database_service()
    if db_service is None:
        raise HTTPException(status_code=500, detail="Database service is not initialized")
    try:
        readable = await readable_simulation_ids(caller, ids)
        return await db_service.get_hpc_db().get_hpcruns_by_refs(ref_ids=readable, job_type=JobType.SIMULATION)
    except Exception as e:
        logger.exception(f"Error fetching batch simulation statuses for ids: {ids}.")
        raise HTTPException(status_code=500, detail=str(e)) from e


@config.router.get(
    path="/simulation/status",
    response_model=HpcRun,
    operation_id="get-simulation-status",
    responses={404: NOT_FOUND_RESPONSE},
    tags=["Results"],
    dependencies=[Depends(get_database_service)],
    summary="Get the simulation status record by its ID",
)
async def get_simulation_status(simulation: ReadableSimulation) -> HpcRun:
    db_service = get_database_service()
    if db_service is None:
        raise HTTPException(status_code=500, detail="Database service is not initialized")
    return await get_hpc_run_status(db_service=db_service, ref_id=simulation.simulation_id, job_type=JobType.SIMULATION)


# @config.router.get(
#     path="/simulation/run/events",
#     response_model=list[WorkerEvent],
#     operation_id="get-simulation-worker-events",
#     tags=["Simulations"],
#     dependencies=[Depends(get_simulation_service), Depends(get_database_service)],
#     summary="Get the worker events for a simulation by its ID",
# )
# async def get_simulation_worker_events(
#     simulation_id: int = Query(...),
#     num_events: int | None = Query(default=None),
#     prev_sequence_number: int | None = Query(default=None),
# ) -> list[WorkerEvent]:
#     sim_service = get_simulation_service()
#     if sim_service is None:
#         logger.error("Simulation service is not initialized")
#         raise HTTPException(status_code=500, detail="Simulation service is not initialized")
#     db_service = get_database_service()
#     if db_service is None:
#         logger.error("SSH service is not initialized")
#         raise HTTPException(status_code=500, detail="SSH service is not initialized")
#     try:
#         simulation_hpcrun: HpcRun | None = await db_service.get_hpcrun_by_ref(
#             ref_id=simulation_id, job_type=JobType.SIMULATION
#         )
#         if simulation_hpcrun:
#             worker_events = await db_service.list_worker_events(
#                 hpcrun_id=simulation_hpcrun.database_id,
#                 prev_sequence_number=prev_sequence_number,
#             )
#             return worker_events[:num_events] if num_events else worker_events
#         else:
#             return []
#     except Exception as e:
#         logger.exception(f"Error fetching simulation results for simulation id: {simulation_id}.")
#         raise HTTPException(status_code=500, detail=str(e)) from e


# @config.router.get(
#     path="/simulation/run/results/chunks",
#     response_class=ORJSONResponse,
#     operation_id="get-simulation-results",
#     tags=["Simulations"],
#     dependencies=[Depends(get_simulation_service), Depends(get_ssh_service)],
#     summary="Get simulation results in chunks",
# )
# async def get_result_chunks(
#     background_tasks: BackgroundTasks,
#     observable_names: RequestedObservables,
#     experiment_id: str = Query(default="experiment_96bb7a2_id_1_20250620-181422"),
#     database_id: int = Query(description="Database Id returned from /submit-simulation"),
#     git_commit_hash: str = Query(default="not-specified"),
# ) -> ORJSONResponse:
#     sim_service = get_simulation_service()
#     if sim_service is None:
#         logger.error("Simulation service is not initialized")
#         raise HTTPException(status_code=500, detail="Simulation service is not initialized")
#     ssh_service = get_ssh_service()
#     if ssh_service is None:
#         logger.error("SSH service is not initialized")
#         raise HTTPException(status_code=500, detail="SSH service is not initialized")
#     try:
#         service = DataServiceHpc()
#
#         local_dir, lazy_frame = await service.read_simulation_chunks(experiment_id, Namespace.TEST)
#         background_tasks.add_task(shutil.rmtree, local_dir)
#         selected_cols = observable_names.items if len(observable_names.items) else ["bulk", "^listeners__mass.*"]
#         data = (
#             lazy_frame.select(
#                 pl.col(selected_cols)  # regex pattern to match columns starting with this prefix
#             )
#             .collect()
#             .to_dict()
#         )
#         return ORJSONResponse(content=data)
#     except Exception as e:
#         logger.exception(f"Error fetching simulation results for id: {database_id}.")
#         raise HTTPException(status_code=500, detail=str(e)) from e


@config.router.get(
    path="/simulation/results/file",
    response_class=FileResponse,
    responses={
        200: {
            "content": {"application/octet-stream": {"schema": {"format": "binary"}}},
            "description": "Simulation result zip file",
        },
        404: {"description": "The simulation does not exist, or its results are not available"},
    },
    operation_id="get-simulation-results-file",
    tags=["Results"],
    dependencies=[Depends(get_simulation_service), Depends(get_ssh_service)],
    summary="Get simulation results as a zip file",
)
async def get_results(simulation: ReadableSimulation) -> FileResponse:
    service = get_data_service()
    if service is None:
        logger.error("Data service is not initialized")
        raise HTTPException(status_code=500, detail="Data service is not initialized")
    # A simulation that does not exist, or that the caller may not read, is a 404 from ReadableSimulation.
    simulation_id, experiment_id = simulation.simulation_id, simulation.experiment_id

    try:
        zip_path = await service.get_results_zip(experiment_id, Namespace(get_settings().namespace))
    except Exception as e:
        logger.exception(f"Error fetching simulation results for id: {simulation_id}.")
        raise HTTPException(status_code=500, detail=str(e)) from e

    # `DataServiceHpc.get_results_zip` builds a path without checking it, so a run whose
    # results do not exist yet would otherwise be handed to FileResponse and fail while
    # streaming, after the status line had already been sent.
    if not Path(zip_path).exists():
        raise HTTPException(status_code=404, detail=f"Results for simulation {simulation_id} are not available.")

    return FileResponse(path=zip_path, filename=f"{experiment_id}_results.zip", media_type="application/zip")


@config.router.get(
    path="/simulator/build/status",
    response_model=HpcRun,
    operation_id="get-simulator-build-status",
    responses={404: NOT_FOUND_RESPONSE},
    tags=["Results"],
    dependencies=[Depends(get_database_service)],
    summary="Get the simulator build status record by its ID",
)
async def get_simulator_build_status(simulator_id: int = Query(...)) -> HpcRun:
    db_service = get_database_service()
    if db_service is None:
        raise HTTPException(status_code=500, detail="Database service is not initialized")
    return await get_hpc_run_status(db_service=db_service, ref_id=simulator_id, job_type=JobType.BUILD_CONTAINER)


# -- a run's events and trace (docs/plan-observability.md O3, O4) -- #

MAX_TRACE_EVENTS = 20_000


@config.router.get(
    path="/simulation/events",
    response_model=RunEventPage,
    operation_id="get-simulation-events",
    responses={404: NOT_FOUND_RESPONSE},
    tags=["Results"],
    summary="Get a page of a simulation's events, in the order they were recorded",
)
async def get_simulation_events(
    simulation: ReadableSimulation,
    after: int | None = Query(default=None, description="Return events after this cursor (a previous page's next)"),
    limit: int = Query(default=500, ge=1, le=5000),
    level: str | None = Query(default=None, description="Only events at this level (debug, info, warning, error)"),
    event: str | None = Query(default=None, description="Only events with this name, e.g. job.end"),
    span_id: str | None = Query(default=None, description="Only events inside this span"),
) -> RunEventPage:
    events_db = get_required_database_service().get_events_db()
    run = await events_db.get_run_for_simulation(simulation.simulation_id)
    if run is None or run.trace_id is None:
        return RunEventPage(simulation_id=simulation.simulation_id, trace_id=None, events=[])
    events = await events_db.list_events(
        run.trace_id, after=after, limit=limit, level=level, event=event, span_id=span_id
    )
    return RunEventPage(
        simulation_id=simulation.simulation_id,
        trace_id=run.trace_id,
        events=events,
        next_cursor=events[-1].cursor if len(events) == limit else None,
    )


async def _trace_of(simulation: SimulationAccess) -> tuple[str | None, bool, list[RunSpan], list[RunEvent]]:
    events_db = get_required_database_service().get_events_db()
    run = await events_db.get_run_for_simulation(simulation.simulation_id)
    if run is None or run.trace_id is None:
        return None, False, [], []
    spans = await events_db.get_spans(run.trace_id)
    events = await events_db.list_events(run.trace_id, limit=MAX_TRACE_EVENTS)
    return run.trace_id, not run.terminal, list(spans.values()), events


@config.router.get(
    path="/simulation/trace",
    response_model=RunTraceTree,
    operation_id="get-simulation-trace",
    responses={404: NOT_FOUND_RESPONSE},
    tags=["Results"],
    summary="Get a simulation's spans as a tree, each span with its own events",
)
async def get_simulation_trace(simulation: ReadableSimulation) -> RunTraceTree:
    trace_id, _live, spans, events = await _trace_of(simulation)
    return RunTraceTree(simulation_id=simulation.simulation_id, trace_id=trace_id, roots=build_span_tree(spans, events))


@config.router.get(
    path="/simulation/trace/chrome",
    response_model=dict[str, Any],
    operation_id="get-simulation-trace-chrome",
    responses={404: NOT_FOUND_RESPONSE},
    tags=["Results"],
    summary="Get a simulation's trace as a Chrome Trace Event document (open it in ui.perfetto.dev)",
)
async def get_simulation_trace_chrome(simulation: ReadableSimulation) -> dict[str, Any]:
    trace_id, live, spans, events = await _trace_of(simulation)
    document = chrome_trace_document(
        spans,
        events,
        trace_id=trace_id,
        other_data={"simulation_id": str(simulation.simulation_id)},
        live=live,
    )
    return dict(document)
