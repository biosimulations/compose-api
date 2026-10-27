"""A bare `.pbg` upload is run as an archive holding it (compose_api/common/gateway/utils.py)."""

import json
from pathlib import Path

from compose_api.common.gateway.utils import wrap_document_in_omex
from compose_api.environments import runner
from compose_api.simulation.models import SimulationFileType, SimulationRequest


def test_a_document_is_wrapped_in_an_archive_the_runner_reads(tmp_path: Path) -> None:
    document = {"state": {"x": 1.0}}
    pbg = tmp_path / "upload.pbg"
    pbg.write_text(json.dumps(document))
    request = SimulationRequest(request_file_path=pbg, simulation_file_type=SimulationFileType.PBG, is_batch=False)

    wrapped = wrap_document_in_omex(request)

    assert wrapped.simulation_file_type is SimulationFileType.OMEX
    assert wrapped.request_file_path.suffix == ".omex" and not pbg.exists()
    # the runner composed images run reads the document back out of it
    work = tmp_path / "work"
    work.mkdir()
    assert runner.load_document(wrapped.request_file_path, work) == document


def test_an_archive_is_left_as_it_is(tmp_path: Path) -> None:
    omex = tmp_path / "upload.omex"
    omex.write_bytes(b"PK")
    request = SimulationRequest(request_file_path=omex, simulation_file_type=SimulationFileType.OMEX, is_batch=False)
    assert wrap_document_in_omex(request) is request
