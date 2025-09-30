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
    PENDING = "pending"


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
    simulation_id: int
    simulator_id: int
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

# class AllenInstituteMultiScaleActinSettings(BaseModel):
#     name: str = "actin_membrane",
#     internal_timestep: float = 0.1,  # ns
#     box_size: list[float] = [float(150.0)] * 3,  # nm
#     periodic_boundary: bool = True,
#     reaction_distance: float = 1.0,  # nm
#     n_cpu: int = 4,
#     only_linear_actin_constraints: bool = True,
#     reactions: bool = True,
#     dimerize_rate: float = 1e-30,  # 1/ns
#     dimerize_reverse_rate: float = 1.4e-9,  # 1/ns
#     trimerize_rate: float = 2.1e-2,  # 1/ns
#     trimerize_reverse_rate: float = 1.4e-9,  # 1/ns
#     pointed_growth_ATP_rate: float = 2.4e-5,  # 1/ns
#     pointed_growth_ADP_rate: float = 2.95e-6,  # 1/ns
#     pointed_shrink_ATP_rate: float = 8.0e-10,  # 1/ns
#     pointed_shrink_ADP_rate: float = 3.0e-10,  # 1/ns
#     barbed_growth_ATP_rate: float = 1e30,  # 1/ns
#     barbed_growth_ADP_rate: float = 7.0e-5,  # 1/ns
#     nucleate_ATP_rate: float = 2.1e-2,  # 1/ns
#     nucleate_ADP_rate: float = 7.0e-5,  # 1/ns
#     barbed_shrink_ATP_rate: float = 1.4e-9,  # 1/ns
#     barbed_shrink_ADP_rate: float = 8.0e-9,  # 1/ns
#     arp_bind_ATP_rate: float = 2.1e-2,  # 1/ns
#     arp_bind_ADP_rate: float = 7.0e-5,  # 1/ns
#     arp_unbind_ATP_rate: float = 1.4e-9,  # 1/ns
#     arp_unbind_ADP_rate: float = 8.0e-9,  # 1/ns
#     barbed_growth_branch_ATP_rate: float = 2.1e-2,  # 1/ns
#     barbed_growth_branch_ADP_rate: float = 7.0e-5,  # 1/ns
#     debranching_ATP_rate: float = 1.4e-9,  # 1/ns
#     debranching_ADP_rate: float = 7.0e-5,  # 1/ns
#     cap_bind_rate: float = 2.1e-2,  # 1/ns
#     cap_unbind_rate: float = 1.4e-9,  # 1/ns
#     hydrolysis_actin_rate: float = 1e-30,  # 1/ns
#     hydrolysis_arp_rate: float = 3.5e-5,  # 1/ns
#     nucleotide_exchange_actin_rate: float = 1e-5,  # 1/ns
#     nucleotide_exchange_arp_rate: float = 1e-5,  # 1/ns
#     verbose: bool = False,
#     use_box_actin: bool = True,
#     use_box_arp: bool = False,
#     use_box_cap: bool = False,
#     obstacle_radius: float = 0.0,
#     obstacle_diff_coeff: float = 0.0,
#     use_box_obstacle: bool = False,
#     position_obstacle_stride: int = 0,
#     displace_pointed_end_tangent: bool = False,
#     displace_pointed_end_radial: bool = False,
#     tangent_displacement_nm: float = 0.0,
#     radial_displacement_radius_nm: float = 0.0,
#     radial_displacement_angle_deg: float = 0.0,
#     longitudinal_bonds: bool = True,
#     displace_stride: int = 1,
#     bonds_force_multiplier: float = 0.2,
#     angles_force_constant: float = 1000.0,
#     dihedrals_force_constant: float = 1000.0,
#     actin_constraints: bool = True,
#     actin_box_center_x: float = 12.0,
#     actin_box_center_y: float = 0.0,
#     actin_box_center_z: float = 0.0,
#     actin_box_size_x: float = 20.0,
#     actin_box_size_y: float = 50.0,
#     actin_box_size_z: float = 50.0,
#     add_extra_box: bool = False,
#     barbed_binding_site: bool = True,
#     binding_site_reaction_distance: float = 3.0,
#     add_membrane: bool = True,
#     membrane_center_x: float = 25.0,
#     membrane_center_y: float = 0.0,
#     membrane_center_z: float = 0.0,
#     membrane_size_x: float = 0.0,
#     membrane_size_y: float = 100.0,
#     membrane_size_z: float = 100.0,
#     membrane_particle_radius: float = 2.5,
#     obstacle_controlled_position_x: float = 0.0,
#     obstacle_controlled_position_y: float = 0.0,
#     obstacle_controlled_position_z: float = 0.0,
#     random_seed: int | None = None,
#     output_base_name: str = "test",
#     output_dir_path: str = ""