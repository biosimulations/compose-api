import json
import os
import tempfile
import zipfile

import pytest

from compose_api_client import Client
from compose_api_client.types import File
from compose_api_client.utils import run_simulation_and_wait

readdy_doc = {
  "state": {
    "readdy": {
      "_type": "process",
      "address": "local:pb_multiscale_actin.processes.readdy_actin_membrane.ReaddyActinMembrane",
      "config": {
        "name": "actin_membrane",
        "random_seed": 0
      },
      "inputs": { "particles": ["particles"], "topologies": ["topologies"] },
      "outputs": { "particles": ["particles"], "topologies": ["topologies"] }
    }
  }
}


@pytest.mark.asyncio
async def test_run_sim_and_wait():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create Omex that gets sent to the server
        readdy_pbg = f"{tmpdir}{os.sep}readdy.pbg"
        omex_file = f"{tmpdir}{os.sep}submit.omex"

        with open(readdy_pbg, "w") as f:
          json.dump(readdy_doc, f)

        with zipfile.ZipFile(omex_file, "w") as f:
          f.write(filename=readdy_pbg, arcname="readdy.pbg")

        client = Client(base_url="https://compose.cam.uchc.edu")

        with open(omex_file, "rb") as input_file:
            sent_file = File(file_name=f"experiment.omex", payload=input_file)
            result, sim_id = await run_simulation_and_wait.async_call(
                experiment_file=sent_file, interval=0, client=client
            )

        with open(os.path.join(tmpdir, "output.zip"), "wb") as output_file:
            output_file.write(result.content)


