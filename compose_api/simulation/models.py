import datetime
import enum
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel as _BaseModel
from pydantic import ConfigDict, Field

from compose_api.simulation.containerization import ContainerizationFileRepr


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


class PackageType(enum.Enum):
    PYPI = "pypi"
    CONDA = "conda"


class BiGraphComputeType(enum.Enum):
    PROCESS = "process"
    STEP = "step"


class JobStatus(StrEnum):
    WAITING = "waiting"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PENDING = "pending"
    CANCELLED = "cancelled"
    OUT_OF_MEMORY = "out_of_memory"
    SUSPENDED = "suspended"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


class HpcRun(BaseModel):
    database_id: int
    slurmjobid: int | None  # Slurm job ID; None for a submission that failed before reaching SLURM
    backend: str = "slurm"  # where the job runs: slurm, k8s (docs/plan-environment-builds.md, E1)
    external_id: str | None = None  # its id there: the SLURM job id, or the Kubernetes Job's name
    correlation_id: str  # to correlate with the WorkerEvent, if applicable ("N/A" if not applicable)
    job_type: JobType
    sim_id: int | None
    simulator_id: int | None
    status: JobStatus | None = None
    start_time: str | None = None  # ISO format datetime string
    end_time: str | None = None  # ISO format datetime string or None if still running
    error_message: str | None = None  # Error message if the simulation failed
    trace_id: str | None = None  # W3C trace id of the run's events (plan-observability O1); None for older runs


class BiGraphComputeOutline(BaseModel):
    module: str
    name: str
    compute_type: BiGraphComputeType
    inputs: str
    outputs: str


class BiGraphCompute(BiGraphComputeOutline):
    database_id: int


class BiGraphProcess(BiGraphCompute):
    pass


class BiGraphStep(BiGraphCompute):
    pass


class PackageOutline(BaseModel):
    package_type: PackageType
    name: str
    compute: list[BiGraphComputeOutline]

    @staticmethod
    def from_pb_outline(pb_outline_json: dict[str, Any], name: str, package_type: PackageType) -> "PackageOutline":
        compute = []
        if "processes" in pb_outline_json:
            for process in pb_outline_json["processes"]:
                compute.append(BiGraphComputeOutline(compute_type=BiGraphComputeType.PROCESS, **process))
        if "steps" in pb_outline_json:
            for step in pb_outline_json["steps"]:
                compute.append(BiGraphComputeOutline(compute_type=BiGraphComputeType.STEP, **step))

        return PackageOutline(package_type=package_type, name=name, compute=compute)


class RegisteredPackage(BaseModel):
    database_id: int
    package_type: PackageType
    name: str
    processes: list[BiGraphProcess]
    steps: list[BiGraphStep]


class ContainerEngine(enum.Enum):
    DOCKER = "docker"
    APPTAINER = "apptaier"


class Simulator(BaseModel):
    container_def: ContainerizationFileRepr
    container_def_hash: str
    packages: list[RegisteredPackage] | None
    # primary_processes: str


class RemoteContainerImage(Simulator):
    source_url: str
    image_name_and_tag: str

    @staticmethod
    def from_container_version(
        simulator_version: "SimulatorVersion", source_url: str | None = None
    ) -> "RemoteContainerImage":
        from compose_api.config import get_settings

        repository = get_settings().simulator_image_repository
        tagged = f"{repository}:{simulator_version.container_def_hash}"
        if source_url is None:
            source_url = f"docker://{tagged}"
        return RemoteContainerImage(
            source_url=source_url,
            image_name_and_tag=tagged,
            container_def=simulator_version.container_def,
            container_def_hash=simulator_version.container_def_hash,
            packages=simulator_version.packages,
        )


class DownloadedContainerImage(RemoteContainerImage):
    database_id: int
    downloaded_at: datetime.datetime | None = None


class ImageKind(StrEnum):
    SIF = "sif"  # a SIF file on the shared filesystem, which the cluster's jobs run from
    OCI = "oci"  # an image in a registry (docs/plan-environment-builds.md, phase 5)


class EnvironmentImage(BaseModel):
    """A built or pulled image of a simulator's definition (docs/plan-environment-builds.md, E3).

    Images are write-once (E4): one that turns out missing is marked unavailable, never replaced in place.
    """

    database_id: int
    simulator_id: int
    kind: ImageKind
    location: str  # a path on the shared filesystem (sif), or a registry reference (oci)
    digest: str | None = None  # "sha256:<hex>" of the file, or the registry's manifest digest
    size_bytes: int | None = None
    hpcrun_id: int | None = None  # the build that produced it; None when adopted or pulled
    available: bool = True
    created_at: datetime.datetime | None = None
    verified_at: datetime.datetime | None = None


class SimulatorVersion(Simulator):
    database_id: int  # Unique identifier for the simulator version
    created_at: datetime.datetime | None = None


class VersionState(StrEnum):
    """An environment version's state (docs/plan-environment-versions.md)."""

    RESOLVING = "resolving"  # its lock is being compiled
    BUILDING = "building"  # its image is being built or pulled
    READY = "ready"  # runs may use it; a missing image is still fetched by the run path, as before
    FAILED = "failed"
    RETIRED = "retired"  # refuses new runs; its images are kept


class EnvironmentVersion(BaseModel):
    """One version of an environment: its simulator (definition, hash, images) and what it was made from
    (docs/plan-environment-versions.md, V1)."""

    database_id: int
    environment_id: int = Field(description="Its environment's identity; the name below may change")
    environment: str = Field(description="Its environment's current name")
    number: int
    state: VersionState
    simulator_id: int | None = Field(description="Its simulator: none while a composed version is resolving")
    image: str | None = Field(default=None, description="A prebuilt version's image, by digest")
    spec: dict[str, Any] | None = Field(default=None, description="What a shared version was made from")
    origin: str | None = Field(default=None, description="registry, or custom for libraries no review has seen")
    resolved_at: datetime.datetime | None = None
    lock_sha256: str | None = None
    runtime_contract: int = 1
    created_by: str | None = None
    created_at: datetime.datetime | None = None
    note: str | None = None
    failure: str | None = Field(default=None, description="Why it failed: for a composed version, its lock's conflict")
    last_used_at: datetime.datetime | None = Field(
        default=None, description="When a run last used it (its newest simulation); none if none has"
    )

    @property
    def label(self) -> str:
        """``registry_env@2``"""
        return f"{self.environment}@{self.number}"


class VersionRef(BaseModel):
    """An environment version as a link: its environment's current name and its number (``registry_env@5``)."""

    environment: str
    number: int


class SimulatorSummary(BaseModel):
    """A simulator (a container definition, identified by its hash) as runs used it (docs/plan-webapp-admin.md, 5c).
    One recorded before environment versions is no version's, and is reached only this way."""

    simulator_id: int
    created_at: datetime.datetime | None = None
    container_def_hash: str
    versions: list[VersionRef] = Field(
        default_factory=list, description="The environment versions it is; none for one from before versions"
    )
    run_count: int = Field(0, description="How many runs you can read used it")
    first_run_at: datetime.datetime | None = None
    last_run_at: datetime.datetime | None = None


class SimulatorDetail(SimulatorSummary):
    """A simulator with its container definition."""

    definition: str


class PackageChange(BaseModel):
    """A package added (``before`` None), removed (``after`` None) or at another version between two versions."""

    name: str
    before: str | None = None
    after: str | None = None


class EnvironmentVersionDetail(EnvironmentVersion):
    """A version with what it was resolved to and, once built, what it installed and provides."""

    lock: str | None = Field(default=None, description="A shared version's lock: every PyPI package, pinned")
    installed: str | None = Field(default=None, description="What its image installed, read from the image")
    interfaces: dict[str, Any] | None = Field(default=None, description="Its process interfaces (pbg-interfaces/1)")
    findings: list[dict[str, Any]] | None = Field(
        default=None,
        description="What the generic compliance checks found in its components: a component with a `fail` is"
        " refused in this version (docs/plan-environment-composition.md, step 5)",
    )
    against: int | None = Field(default=None, description="The version `changes` compares it with, when asked")
    changes: list[PackageChange] | None = Field(
        default=None,
        description="With `against`: how its installed packages differ from that version's, by name (PEP 503)",
    )


class EnvironmentVersions(BaseModel):
    """An environment's versions, newest first, and which one a run that names none gets."""

    environment: str
    kind: str
    default: int | None = Field(default=None, description="The default version's number")
    default_source: str = Field(
        default="deployment",
        description="deployment: the deployment's own definition is the default; api: an administrator chose it",
    )
    versions: list[EnvironmentVersion] = Field(default_factory=list)


class NewEnvironmentVersion(BaseModel):
    """What to make a version from. A composed environment (one that lists its registry entries): a date to resolve
    its entries at (default now); a mash-up is an environment of its own, never a version of another. A prebuilt one:
    its image by digest. (Library lists, the shared uv path's `custom` versions, are retired:
    docs/plan-environment-composition.md, D8.5; versions made that way stay readable.)"""

    model_config = ConfigDict(extra="forbid")  # a library list is refused, not ignored

    resolved_at: datetime.datetime | None = None
    image: str | None = None
    note: str | None = None


class ComplianceCase(BaseModel):
    """One compliance case of an entry, run in a version: `pending` until its run finishes, then `passed`, `failed`
    (an expectation not met) or `error` (the run did not finish)."""

    case: str
    state: str
    simulation_id: int | None = None
    failures: list[str] = Field(default_factory=list)


class EntryCompliance(BaseModel):
    """An entry's standing in a version: `tested` when its cases all passed there, `pending` while any runs,
    `failed` when one did not pass, `untested` when it has no cases yet."""

    entry: str
    level: str
    cases: list[ComplianceCase] = Field(default_factory=list)


class ComplianceReport(BaseModel):
    """What certifies a version's entries (docs/plan-environment-composition.md, step 5): their cases' runs there,
    and the generic checks over its components. A component that fails a check is refused in this version (`refused`),
    whatever its entry's level."""

    environment: str
    number: int
    entries: list[EntryCompliance] = Field(default_factory=list)
    findings: list[dict[str, Any]] = Field(default_factory=list)
    refused: list[str] = Field(default_factory=list, description="Components a generic check failed")


class EnvironmentExport(BaseModel):
    """A version's environment as files to recreate it with locally (docs/plan-environment-composition.md, C2a):
    `pixi` (pixi.toml and pixi.lock, `pixi install --frozen`) for a composed version, `requirements` (the uv lock,
    `uv pip install -r`) for a shared one."""

    environment: str
    number: int
    format: str
    files: dict[str, str] = Field(description="File name -> contents")


class DefaultVersion(BaseModel):
    number: int


class RegisteredSimulators(BaseModel):
    versions: list[SimulatorVersion]
    timestamp: datetime.datetime | None = Field(default_factory=datetime.datetime.now)


class RegisteredProcesses(BaseModel):
    versions: list[BiGraphProcess]
    timestamp: datetime.datetime | None = Field(default_factory=datetime.datetime.now)


class SimulationFileType(enum.Enum):
    OMEX = "omex"
    PBG = "pbg"
    SBML = "sbml"

    def get_files_suffix(self) -> str:
        return self.value

    @staticmethod
    def get_file_type(suffix: str) -> "SimulationFileType":
        match suffix:
            case ".omex":
                return SimulationFileType.OMEX
            case ".pbg":
                return SimulationFileType.PBG
            case ".sbml":
                return SimulationFileType.SBML
            case _:
                raise ValueError(f"Unknown simulation file type: {suffix}")


class SimulationRequest(BaseModel):
    """
    Files to kick off a simulation.
    """

    request_file_path: Path
    simulation_file_type: SimulationFileType
    end_time_point: float = 1.0
    is_batch: bool
    # A prebuilt environment by name (its default version's image, D8.3); None runs the shared one.
    simulator: str | None = None
    # The version of that environment to run in (docs/plan-environment-versions.md, step 5); None: its default.
    environment_version: int | None = None
    # A composed environment the deployment does not declare, by name: a mash-up (docs/plan-environment-composition.md,
    # step 7b). None: the environment `simulator` decides (the shared one, or a prebuilt image).
    environment: str | None = None
    # Stored on the simulation (compose_api/simulation/labels.py): the service's labels, the submitter's tags and text.
    labels: dict[str, str] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    description: str | None = None
    # A SED-ML run's original archive (docs/plan-sedml.md, D6): uploaded beside the input as `source.omex` and
    # announced as a `sedml-omex` dataset; the input is the process-bigraph archive translated from it.
    source_file_path: Path | None = None


class SubmissionState(StrEnum):
    """Where a run is on its way to SLURM (docs/plan-durable-submission.md, Q1). The public status stays
    ``submitting`` until the run has a SLURM job; this is the detail behind it."""

    REQUESTED = "requested"  # recorded and staged, waiting for the worker
    PREPARING = "preparing"  # its image is being fetched or built
    SUBMITTING = "submitting"  # the image is ready; sbatch is next
    SUBMITTED = "submitted"  # SLURM has the job (the run's status takes over)
    FAILED = "failed"  # it will not reach SLURM; the reason is on its FAILED run


#: The states the worker still owns.
ACTIVE_SUBMISSION_STATES = (SubmissionState.REQUESTED, SubmissionState.PREPARING, SubmissionState.SUBMITTING)


@dataclass(frozen=True)
class SubmissionSpec:
    """How a new run is queued: its queue and priority (docs/plan-durable-submission.md, Q3), who asked, and whether
    its staged files are on the store the cluster sees (else in a local directory the worker uploads from)."""

    staged_on_store: bool
    queue: str = "interactive"
    priority: int = 0
    requested_by: str | None = None


class Submission(BaseModel):
    """A queued run as the worker sees it: enough to rebuild its job after a restart."""

    simulation_id: int
    experiment_id: str
    simulator_id: int
    state: SubmissionState
    queue: str
    priority: int
    requested_by: str | None = None
    request: SimulationRequest  # its paths are the staged files
    staged_on_store: bool
    attempts: int = 0
    last_error: str | None = None
    created_at: datetime.datetime


class SimulationResults(BaseModel):
    """
    Simulation has been sent to HPC, and can be in any of the SLURM job allowed states including finished.
    The content in the users request is saved on the servers distributed file system.
    """

    path_on_server: Path


class Simulation(BaseModel):
    """
    Everything required to execute the simulation and produce the same results.
    Input file contains all the files required to run the simulation (process-bigraph.json, sbml, etc...).
    pb_cache_hash is the hash affiliated with the specific process bi-graph and it's dependencies.
    Args:
        database_id: int
        sim_request: SimulationRequest
        simulator_version: SimulatorVersion
    """

    database_id: int
    sim_request: SimulationRequest
    simulator_version: SimulatorVersion


class Visibility(StrEnum):
    """Who may read a simulation and everything it produced (plan-observability O7)."""

    PUBLIC = "public"
    PRIVATE = "private"


class SimulationAccess(BaseModel):
    """What an authorization decision about a simulation needs: its owner and visibility (plan-observability O7, O8)."""

    simulation_id: int
    experiment_id: str
    owner_sub: str | None = None  # the submitter's identity-provider subject; None for anonymous and older runs
    visibility: Visibility = Visibility.PUBLIC


class SubmissionInfo(BaseModel):
    """Where a run is on its way to SLURM (docs/plan-durable-submission.md): the detail behind `submitting`."""

    state: SubmissionState
    queue: str
    position: int | None = None  # its place in line among queued runs (1 is next), while it is `requested`
    attempts: int = 0
    last_error: str | None = None


class SimulationSummary(BaseModel):
    """One simulation as a listing shows it: what ran, where, and how it went (its latest SLURM job)."""

    simulation_id: int
    created_at: str | None = None  # ISO 8601 UTC
    experiment_id: str
    simulator_id: int
    simulator: str | None = None  # the prebuilt simulator's name, or its image; None for a built container
    container_def_hash: str
    visibility: Visibility = Visibility.PUBLIC
    mine: bool = Field(
        default=False,
        description="The caller submitted it, signed in; its owner is never named (docs/plan-favorites-and-studies.md)",
    )
    status: str  # a JobStatus, or "submitting" while no SLURM job exists yet
    slurm_job_id: int | None = None
    start_time: str | None = None
    end_time: str | None = None
    exit_code: int | None = None
    error_message: str | None = None
    trace_id: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)  # written by the service: what the run is
    tags: list[str] = Field(default_factory=list)  # the submitter's
    description: str | None = None
    submission: SubmissionInfo | None = None  # None for simulations recorded before the submission queue
    environment_version: VersionRef | None = Field(
        default=None, description="The environment version it ran in; none for a run from before versions"
    )


class SimulationDetail(SimulationSummary):
    """A simulation with what its run recorded."""

    event_count: int = 0
    dataset_count: int = 0


class ErrorDetail(BaseModel):
    """An error's body, as FastAPI's ``HTTPException`` writes it. A route declares it for its error responses so the
    generated client parses them into this rather than typing them ``Any``, which would make the whole return type
    ``Any`` to a type checker."""

    detail: str


class SimulationCancellation(BaseModel):
    """A cancellation accepted. ``withdrawn``: the run was taken off the queue before SLURM had it, and is cancelled
    now. Otherwise SLURM was asked to cancel ``slurm_job_id``, and the run's status reads ``cancelled`` once the job
    monitor sees SLURM report it."""

    simulation_id: int
    withdrawn: bool
    slurm_job_id: int | None = None


class SimulationPage(BaseModel):
    simulations: list[SimulationSummary]
    total: int
    next_offset: int | None = None


class SubmittedSimulation(BaseModel):
    database_id: int
    sim_content: SimulationResults
    simulator_version: SimulatorVersion
    hpc_run: HpcRun | None


class SimulationExperiment(BaseModel):
    simulation_database_id: int
    simulator_database_id: int
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
