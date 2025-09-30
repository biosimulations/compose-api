import asyncio
import os
import random
import string
import tempfile
import time
from pathlib import Path

import pytest

from compose_api.common.hpc.models import SlurmJob
from compose_api.common.ssh.ssh_service import SSHService
from compose_api.config import get_settings
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.simulation import handlers
from compose_api.simulation.hpc_utils import (
    get_experiment_id,
)
from compose_api.simulation.job_scheduler import JobMonitor
from compose_api.simulation.models import JobType, PBAllowList, SimulationRequest, SimulatorVersion
from compose_api.simulation.simulation_service import SimulationServiceHpc
from tests.fixtures import simulation_fixtures

