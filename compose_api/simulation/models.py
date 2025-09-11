import datetime
import enum
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel as _BaseModel
from pydantic import Field

from compose_api.btools.bsander.bsandr_utils.input_types import ContainerizationFileRepr, ExperimentPrimaryDependencies


@dataclass
class FlexData:
    _data: dict[str, Any] = field(default_factory=dict)

    def __init__(self, **kwargs):  # type: ignore[no-untyped-def]
        self._data = kwargs

    def __getattr__(self, item):  # type: ignore[no-untyped-def]
        return self._data[item]

    def __getitem__(self, item):  # type: ignore[no-untyped-def]
        return self._data[item]

    def keys(self):  # type: ignore[no-untyped-def]
        return self._data.keys()

    def dict(self) -> dict[str, Any]:
        return self._data


class Payload(FlexData):
    pass


class BaseModel(_BaseModel):
    def as_payload(self) -> Payload:
        serialized = json.loads(self.model_dump_json())
        return Payload(**serialized)  # type: ignore[no-untyped-call]


class JobType(enum.Enum):
    SIMULATION = "simulation"
    BUILD_CONTAINER = "build_container"


class JobStatus(StrEnum):
    WAITING = "waiting"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class HpcRun(BaseModel):
    database_id: int
    slurmjobid: int  # Slurm job ID if applicable
    correlation_id: str  # to correlate with the WorkerEvent, if applicable ("N/A" if not applicable)
    job_type: JobType
    sim_id: int | None
    simulator_id: int | None
    status: JobStatus | None = None
    start_time: str | None = None  # ISO format datetime string
    end_time: str | None = None  # ISO format datetime string or None if still running
    error_message: str | None = None  # Error message if the simulation failed


class Simulator(BaseModel):
    singularity_def: ContainerizationFileRepr
    singularity_def_hash: str
    primary_packages: ExperimentPrimaryDependencies
    # primary_processes: str


class SimulatorVersion(Simulator):
    database_id: int  # Unique identifier for the simulator version
    created_at: datetime.datetime | None = None


class RegisteredSimulators(BaseModel):
    versions: list[SimulatorVersion]
    timestamp: datetime.datetime | None = Field(default_factory=datetime.datetime.now)


class SimulationRequest(BaseModel):
    omex_archive: Path


class Simulation(BaseModel):
    """
    Everything required to execute the simulation and produce the same results.
    Input file contains all the files required to run the simulation (process-bigraph.json, sbml, etc...).
    pb_cache_hash is the hash affiliated with the specific process bi-graph and it's dependencies.
    Args:
        database_id: SimulatorVersion
        sim_request: SimulationRequest
        slurmjob_id: int | None
    """

    database_id: int
    sim_request: SimulationRequest
    simulator_version: SimulatorVersion
    slurmjob_id: int | None = None


class PBAllowList(BaseModel):
    allow_list: list[str]


class SimulationExperiment(BaseModel):
    experiment_id: str
    simulation: Simulation
    last_updated: str = Field(default_factory=lambda: str(datetime.datetime.now()))
    metadata: Mapping[str, str] = Field(default_factory=dict)


class WorkerEvent(BaseModel):
    database_id: int | None = None  # Unique identifier for the worker event (created by the database)
    created_at: str | None = None  # ISO format datetime string (created by the database)
    hpcrun_id: int | None = None  # ID of the HpcRun this event is associated with (known in context of database)

    correlation_id: str  # to correlate with the HpcRun job - see hpc_utils.get_correlation_id()
    sequence_number: int  # Sequence number provided by the message producer (emitter)
    mass: dict[str, float]  # mass from the simulation
    time: float  # Global time of the simulation

    @classmethod
    def from_message_payload(cls, worker_event_message_payload: "WorkerEventMessagePayload") -> "WorkerEvent":
        """Create a WorkerEvent from a WorkerEventMessagePayload."""
        return cls(
            correlation_id=worker_event_message_payload.correlation_id,
            sequence_number=worker_event_message_payload.sequence_number,
            mass=worker_event_message_payload.mass,
            time=worker_event_message_payload.time,
        )


class WorkerEventMessagePayload(BaseModel):
    correlation_id: str  # to correlate with the HpcRun job - see hpc_utils.get_correlation_id()
    sequence_number: int  # Sequence number provided by the message producer (emitter)
    time: float  # global time of the simulation
    mass: dict[str, float]  # progress data from the simulation (e.g., mass of substances)


class RequestedObservables(BaseModel):
    items: list[str] = Field(default_factory=list)
