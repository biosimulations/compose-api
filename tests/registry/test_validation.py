"""What the service accepts and refuses at submission (goal G6), with no cluster and no database."""

import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest
from jinja2 import Template

from compose_api.registry.manifest import CurationLevel, Manifest, RegistryEntry, load_manifest
from compose_api.registry.validation import (
    AddressPolicy,
    SubmissionRejectedError,
    find_violations,
    validate_submission,
)
from compose_api.simulation.models import SimulationFileType

RESOURCES = Path(__file__).parent.parent / "fixtures" / "resources"
TEMPLATES = Path(__file__).parent.parent.parent / "compose_api" / "api" / "routers" / "templates"
COPASI = "local:pbsim_common.simulators.copasi_process.CopasiUTCStep"


def composite(*addresses: Any) -> dict[str, Any]:
    return {"state": {f"step_{i}": {"_type": "step", "address": a} for i, a in enumerate(addresses)}}


def omex(tmp_path: Path, members: dict[str, bytes], name: str = "experiment.omex") -> Path:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as archive:
        for member, data in members.items():
            archive.writestr(member, data)
    return path


def omex_bytes(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for member, data in members.items():
            archive.writestr(member, data)
    return buffer.getvalue()


def document(*addresses: Any) -> bytes:
    return json.dumps(composite(*addresses)).encode()


@pytest.mark.parametrize("fixture", ["phase_cycle.omex", "readdy.omex"])
def test_existing_fixtures_are_accepted(fixture: str) -> None:
    assert find_violations(RESOURCES / fixture, SimulationFileType.OMEX, load_manifest()) == []


@pytest.mark.parametrize("template", ["copasi.jinja", "tellurium.jinja"])
def test_curated_templates_are_accepted(tmp_path: Path, template: str) -> None:
    rendered = Template((TEMPLATES / template).read_text()).render(
        start_time=0, duration=10, end_time=10, num_data_points=11, output_dir="/experiment/output"
    )
    path = tmp_path / "curated.pbg"
    path.write_text(rendered)
    assert find_violations(path, SimulationFileType.PBG, load_manifest()) == []


def test_quoted_address_type_default_is_not_an_address(tmp_path: Path) -> None:
    doc = composite(COPASI)
    doc["state"]["schema"] = {"address": {"_type": "quote", "_default": "local:time_course"}}
    path = tmp_path / "doc.pbg"
    path.write_text(json.dumps(doc))
    assert find_violations(path, SimulationFileType.PBG, load_manifest()) == []


@pytest.mark.parametrize(
    ("address", "reason", "always"),
    [
        ("local:!os.system", "imports arbitrary modules", True),
        ("rest:http://example.org/process", "protocol `rest`", True),
        ({"protocol": "parallel", "data": COPASI}, "protocol `parallel`", True),
        ({"protocol": "local", "data": {"not": "a string"}}, "must be a string", True),
        ("local:CopasiUTCStep", "short names", False),
        ("CopasiUTCStep", "short names", False),
        ("local:numpy.linalg.Solver", "not provided by any registered simulator", False),
        ("local:pbsim_commonplace.Step", "not provided by any registered simulator", False),
    ],
)
def test_refused_addresses(tmp_path: Path, address: Any, reason: str, always: bool) -> None:
    path = tmp_path / "doc.pbg"
    path.write_bytes(document(COPASI, address))
    (violation,) = find_violations(path, SimulationFileType.PBG, load_manifest())
    assert reason in violation.reason
    assert violation.always_rejected is always


def test_entry_below_tested_is_refused(tmp_path: Path) -> None:
    manifest = Manifest(
        entries=[
            RegistryEntry(
                id="viva-example",
                package="viva-example",
                source="https://github.com/vivarium-collective/viva-example",
                commit="0" * 40,
                module_roots=["viva_example"],
                level=CurationLevel.LISTED,
                bundles=["registry_env"],
            )
        ]
    )
    path = tmp_path / "doc.pbg"
    path.write_bytes(document("local:viva_example.processes.Example"))
    (violation,) = find_violations(path, SimulationFileType.PBG, manifest)
    assert "level `listed`" in violation.reason


def test_entry_outside_the_service_bundle_is_refused(tmp_path: Path) -> None:
    manifest = Manifest(
        entries=[
            RegistryEntry(
                id="viva-example",
                package="viva-example",
                source="https://github.com/vivarium-collective/viva-example",
                commit="0" * 40,
                module_roots=["viva_example"],
                level=CurationLevel.CURATED,
            )
        ]
    )
    path = tmp_path / "doc.pbg"
    path.write_bytes(document("local:viva_example.processes.Example"))
    (violation,) = find_violations(path, SimulationFileType.PBG, manifest)
    assert "not installed in the service image" in violation.reason


def test_bad_address_in_a_nested_bundle_is_found(tmp_path: Path) -> None:
    inner_good = omex_bytes({"a.pbg": document(COPASI)})
    inner_bad = omex_bytes({"b.pbg": document("local:!subprocess.run")})
    path = omex(tmp_path, {"omex_0.omex": inner_good, "omex_1.omex": inner_bad})
    (violation,) = find_violations(path, SimulationFileType.OMEX, load_manifest())
    assert violation.document == "experiment.omex/omex_1.omex/b.pbg"


def test_every_document_in_an_archive_is_checked(tmp_path: Path) -> None:
    """The container runs whichever document it finds first, so all of them must pass."""
    path = omex(tmp_path, {"a.pbg": document(COPASI), "z.json": document("local:evil.Process")})
    (violation,) = find_violations(path, SimulationFileType.OMEX, load_manifest())
    assert violation.document.endswith("z.json")


@pytest.mark.parametrize(
    ("members", "message"),
    [
        ({"model.sbml": b"<sbml/>"}, "contains no composite document"),
        ({"doc.pbg": b"not json"}, "not a valid JSON composite document"),
    ],
)
def test_unreadable_archives_are_rejected(tmp_path: Path, members: dict[str, bytes], message: str) -> None:
    with pytest.raises(SubmissionRejectedError, match=message):
        find_violations(omex(tmp_path, members), SimulationFileType.OMEX, load_manifest())


def test_not_a_zip_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "experiment.omex"
    path.write_bytes(b"plain text")
    with pytest.raises(SubmissionRejectedError, match="not a valid OMEX"):
        find_violations(path, SimulationFileType.OMEX, load_manifest())


def test_warn_policy_tolerates_registry_refusals_but_not_unsafe_forms(tmp_path: Path) -> None:
    unregistered = tmp_path / "unregistered.pbg"
    unregistered.write_bytes(document("local:numpy.Solver"))
    tolerated = validate_submission(unregistered, SimulationFileType.PBG, AddressPolicy.WARN)
    assert len(tolerated) == 1

    with pytest.raises(SubmissionRejectedError):
        validate_submission(unregistered, SimulationFileType.PBG, AddressPolicy.ENFORCE)

    unsafe = tmp_path / "unsafe.pbg"
    unsafe.write_bytes(document("local:!os.system"))
    with pytest.raises(SubmissionRejectedError) as raised:
        validate_submission(unsafe, SimulationFileType.PBG, AddressPolicy.WARN)
    assert raised.value.violations[0].always_rejected


def test_sbml_carries_no_addresses(tmp_path: Path) -> None:
    path = tmp_path / "model.sbml"
    path.write_text("<sbml/>")
    assert find_violations(path, SimulationFileType.SBML, load_manifest()) == []
