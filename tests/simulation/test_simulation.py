import asyncio
import math
import os
import random
import string
import tempfile
import time
from pathlib import Path

import numpy
import pytest

from compose_api.common.ssh.ssh_service import SSHService
from compose_api.config import get_settings
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.simulation.hpc_utils import get_correlation_id, get_slurm_job_name, get_slurm_sim_experiment_dir
from compose_api.simulation.models import JobType, PBWhiteList, SimulationRequest
from compose_api.simulation.simulation_service import SimulationServiceHpc


@pytest.mark.skipif(len(get_settings().slurm_submit_key_path) == 0, reason="slurm ssh key file not supplied")
@pytest.mark.asyncio
async def test_simulate(
    simulation_service_slurm: SimulationServiceHpc,
    database_service: DatabaseServiceSQL,
    simulation_request: SimulationRequest,
    ssh_service: SSHService,
) -> None:
    # insert the latest commit into the database
    random_string = "".join(random.choices(string.hexdigits, k=7))  # noqa: S311 doesn't need to be secure
    simulation = await database_service.insert_simulation(sim_request=simulation_request, pb_cache_hash=random_string)

    correlation_id = get_correlation_id(simulation=simulation, pb_cache_hash=random_string)
    sim_slurmjobid = await simulation_service_slurm.submit_simulation_job(
        white_list=PBWhiteList(white_list=["pypi:bspil-basico"]),
        simulation=simulation,
        database_service=database_service,
        correlation_id=correlation_id,
    )
    assert sim_slurmjobid is not None

    hpcrun = await database_service.insert_hpcrun(
        slurmjobid=sim_slurmjobid,
        job_type=JobType.SIMULATION,
        ref_id=simulation.database_id,
        correlation_id=correlation_id,
    )
    assert hpcrun is not None
    assert hpcrun.slurmjobid == sim_slurmjobid
    assert hpcrun.job_type == JobType.SIMULATION
    assert hpcrun.ref_id == simulation.database_id

    start_time = time.time()
    sim_slurmjob = None
    while start_time + 60 > time.time():
        sim_slurmjob = await simulation_service_slurm.get_slurm_job_status(slurmjobid=sim_slurmjobid)
        if sim_slurmjob is not None and sim_slurmjob.is_done():
            break
        await asyncio.sleep(5)

    assert sim_slurmjob is not None
    assert sim_slurmjob.is_done()
    assert not sim_slurmjob.is_failed()
    assert sim_slurmjob.job_id == sim_slurmjobid

    with tempfile.TemporaryDirectory() as temp_dir:
        remote_experiment_result = get_slurm_sim_experiment_dir(get_slurm_job_name(correlation_id)) / Path(
            "output/output/report.csv"
        )
        experiment_result = Path(temp_dir) / "report.csv"
        # SCP used because in test FS is not mounted
        await ssh_service.scp_download(experiment_result, remote_experiment_result)
        test_dir = os.path.dirname(__file__).rsplit("/", 1)[0]
        report_csv_file = Path(os.path.join(test_dir, "fixtures/resources/report.csv"))
        experiment_numpy = numpy.genfromtxt(experiment_result, delimiter=",", dtype=object)
        report_numpy = numpy.genfromtxt(report_csv_file, delimiter=",", dtype=object)
        assert report_numpy.shape == experiment_numpy.shape
        r, c = report_numpy.shape
        for i in range(r):
            for j in range(c):
                report_val = report_numpy[i, j].decode("utf-8")
                experiment_val = experiment_numpy[i, j].decode("utf-8")
                try:
                    f_report = float(report_val)
                    f_exp = float(experiment_val)
                    assert math.isclose(f_report, f_exp, rel_tol=0, abs_tol=1e-9)
                except ValueError:
                    assert report_val == experiment_val  # Must be string portion of report then (columns)


@pytest.mark.skipif(len(get_settings().slurm_submit_key_path) == 0, reason="slurm ssh key file not supplied")
@pytest.mark.asyncio
async def test_simulator_not_in_whitelist(
    simulation_service_slurm: SimulationServiceHpc,
    database_service: DatabaseServiceSQL,
    simulation_request: SimulationRequest,
) -> None:
    # insert the latest commit into the database
    random_string = "".join(random.choices(string.hexdigits, k=7))  # noqa: S311 doesn't need to be secure
    simulation = await database_service.insert_simulation(sim_request=simulation_request, pb_cache_hash=random_string)

    correlation_id = get_correlation_id(simulation=simulation, pb_cache_hash=random_string)
    with pytest.raises(ValueError):
        await simulation_service_slurm.submit_simulation_job(
            white_list=PBWhiteList(white_list=["pypi:bspil"]),
            simulation=simulation,
            database_service=database_service,
            correlation_id=correlation_id,
        )
