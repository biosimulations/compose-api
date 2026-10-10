"""The submitted file lands where the job script looks for it, for every accepted file type. A ``.pbg`` used to be
uploaded as ``<id>.omex`` while the script ran ``/experiment/<id>.pbg`` (simulation 4569)."""

import pytest

from compose_api.simulation.hpc_utils import get_slurm_sim_input_file_path
from compose_api.simulation.job_script import SimulationJob, simulation_job_script
from compose_api.simulation.models import SimulationFileType


@pytest.mark.parametrize("file_type", list(SimulationFileType))
def test_the_uploaded_input_is_the_file_the_job_runs(file_type: SimulationFileType) -> None:
    suffix = file_type.get_files_suffix()
    script = simulation_job_script(
        SimulationJob(
            job_name="job1",
            experiment_id="exp1",
            simulation_id=1,
            correlation_id="simulation-abc1234",
            experiment_dir="/store/sims/job1",
            container="image.sif",
            file_suffix=suffix,
            output_dir="/experiment/output",
            end_time=1.0,
            log_file="/store/job1.out",
            is_batch=False,
            partition="p",
            qos="q",
        )
    )
    uploaded = get_slurm_sim_input_file_path(experiment_id="job1", suffix=suffix)
    assert f"/experiment/{uploaded.name}" in script
