"""SBML Test Suite sources (docs/plan-sbml-test-suite.md, step 2), against a release made here: the suite's cases are
not committed (finding 8), so these are hand-written cases in its layout, one per shape the writer must handle."""

import hashlib
import io
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from compose_api.config import override_settings
from compose_api.db.database_service import DatabaseServiceSQL
from compose_api.sedml import sbml_test_suite as sts
from compose_api.sedml import sources, suites
from compose_api.sedml.compare import score
from compose_api.sedml.service import chosen_solvers
from compose_api.sedml.suites import Suite
from compose_api.sedml.translator import translate
from tests.sedml.conftest import needs_translator
from tests.sedml.test_suites import _settled

RELEASE = "9.9.9"

_HEADER = """(*

category:      Test
synopsis:      {synopsis}
               on two lines.
componentTags: Compartment, Species, Reaction, Parameter
testTags:      {test_tags}
testType:      {test_type}
levels:        2.4, 3.2
generatedBy:   {generated_by}
{packages}
The model has one reaction.

*)
"""


def _model(level: int, version: int, *, compartment: str = 'size="2" constant="true"', extra: str = "") -> str:
    ns = f"http://www.sbml.org/sbml/level{level}/version{version}/core"
    hosu = 'hasOnlySubstanceUnits="{}" boundaryCondition="false" constant="false"'
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="{ns}" level="{level}" version="{version}">
  <model id="case">
    <listOfCompartments><compartment id="C" spatialDimensions="3" {compartment}/></listOfCompartments>
    <listOfSpecies>
      <species id="S1" compartment="C" initialConcentration="1" {hosu.format("false")}/>
      <species id="S2" compartment="C" initialAmount="0" {hosu.format("true")}/>
    </listOfSpecies>
    <listOfParameters><parameter id="k1" value="0.5" constant="true"/></listOfParameters>
    {extra}
    <listOfReactions>
      <reaction id="J1" reversible="false">
        <listOfReactants><speciesReference species="S1" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="S2" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML">
          <apply><times/><ci>k1</ci><ci>S1</ci><ci>C</ci></apply></math></kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>
"""


_SETTINGS = """start: 0
duration: 2
steps: 2
variables: {variables}
absolute: 1.000000e-007
relative: 0.0001
amount: {amount}
concentration: {concentration}
"""


def _case(z: zipfile.ZipFile, number: str, files: dict[str, str]) -> None:
    for suffix, content in files.items():
        z.writestr(f"semantic/{number}/{number}-{suffix}", content)


def _release() -> bytes:
    buffer = io.BytesIO()
    results = "time,S1,S2,k1\n0,2,0,0.5\n1,1.2,0.8,0.5\n2,0.7,1.3,0.5\n"
    with zipfile.ZipFile(buffer, "w") as z:
        # 00001: S1 asked as an amount (a concentration in the model), S2 as a concentration (an amount in it)
        _case(
            z,
            "00001",
            {
                "model.m": _HEADER.format(
                    synopsis="One reaction",
                    test_tags="Amount, Concentration",
                    test_type="TimeCourse",
                    generated_by="Analytic",
                    packages="",
                ),
                "settings.txt": _SETTINGS.format(variables="S1, S2, k1", amount="S1", concentration="S2"),
                "results.csv": results,
                "sbml-l2v4.xml": _model(2, 4).replace('constant="false"', "").replace('constant="true"', ""),
                "sbml-l3v2.xml": _model(3, 2),
            },
        )
        # 00002: the same, but the compartment's size is set by a rule, so it is not a number the SED-ML can carry
        _case(
            z,
            "00002",
            {
                "model.m": _HEADER.format(
                    synopsis="Varying compartment",
                    test_tags="Amount",
                    test_type="TimeCourse",
                    generated_by="Numeric",
                    packages="",
                ),
                "settings.txt": _SETTINGS.format(variables="S1", amount="S1", concentration=""),
                "results.csv": "time,S1\n0,2\n1,1.2\n2,0.7\n",
                "sbml-l3v2.xml": _model(
                    3,
                    2,
                    compartment='size="2" constant="false"',
                    extra='<listOfRules><assignmentRule variable="C"><math xmlns="http://www.w3.org/1998/Math/MathML">'
                    "<cn>2</cn></math></assignmentRule></listOfRules>",
                ),
            },
        )
        # 00003: a `comp` case names a submodel's element by its flattened id, which the model as written lacks
        _case(
            z,
            "00003",
            {
                "model.m": _HEADER.format(
                    synopsis="A submodel",
                    test_tags="Amount",
                    test_type="TimeCourse",
                    generated_by="Numeric",
                    packages="packagesPresent: comp",
                ),
                "settings.txt": _SETTINGS.format(variables="sub1__k1", amount="", concentration=""),
                "results.csv": "time,sub1__k1\n0,1\n1,1\n2,1\n",
                "sbml-l3v2.xml": _model(3, 2),
            },
        )
        # 00004: a flux balance case, which is not a time course
        _case(
            z,
            "00004",
            {
                "model.m": _HEADER.format(
                    synopsis="FBA",
                    test_tags="",
                    test_type="FluxBalanceSteadyState",
                    generated_by="Analytic",
                    packages="",
                ),
                "settings.txt": "variables: J1\nabsolute:\nrelative:\n",
                "results.csv": "J1\n1\n",
                "sbml-l3v2.xml": _model(3, 2),
            },
        )
    return buffer.getvalue()


@pytest.fixture
def release(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[list[str]]:
    """A release pinned by its hash and answered from memory; every URL asked is listed."""
    content = _release()
    asked: list[str] = []

    async def get_bytes(url: str, **_: Any) -> bytes:
        asked.append(url)
        return content

    monkeypatch.setitem(
        sts.RELEASES, RELEASE, sts.Release(asset="semantic.zip", sha256=hashlib.sha256(content).hexdigest())
    )
    monkeypatch.setattr(sts, "_get_bytes", get_bytes)
    with override_settings(sources_cache_dir=str(tmp_path / "cache")):
        yield asked


def test_a_source_names_a_pinned_release_and_a_case() -> None:
    assert sts.parse_source("3.5.0/00001") == ("3.5.0", "00001")
    with pytest.raises(sources.SourceNotFoundError, match="is not pinned"):
        sts.parse_source("1.0.0/00001")
    with pytest.raises(sources.SourceNotFoundError, match="<release>/<case>"):
        sts.parse_source("00001")


@pytest.mark.asyncio
async def test_the_release_is_fetched_once_and_checked_against_its_hash(
    release: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    await sts.case(f"{RELEASE}/00001")
    await sts.case(f"{RELEASE}/00001")
    assert release == [f"{sts.REPOSITORY}/releases/download/{RELEASE}/semantic.zip"]

    monkeypatch.setitem(sts.RELEASES, "9.9.8", sts.Release(asset="other.zip", sha256="0" * 64))
    with pytest.raises(sources.SourceUnavailableError, match="not the pinned"):
        await sts.case("9.9.8/00001")
    with pytest.raises(sources.SourceNotFoundError, match="no case 00042"):
        await sts.case(f"{RELEASE}/00042")


@pytest.mark.asyncio
async def test_a_case_is_read_at_its_highest_level_with_its_tags_and_origin(release: list[str]) -> None:
    case = await sts.case(f"{RELEASE}/00001")
    assert case.model_file == "00001-sbml-l3v2.xml"
    assert case.info.synopsis == "One reaction on two lines."
    assert case.info.test_tags == ["Amount", "Concentration"]
    assert case.info.levels == ["2.4", "3.2"]
    assert (case.settings.steps, case.settings.amount, case.settings.concentration) == (2, ["S1"], ["S2"])
    # the expected results are the reference, whatever made them, and the origin says which (S10)
    assert case.origin == f"sbml-test-suite:{RELEASE}:analytic"
    assert (await sts.case(f"{RELEASE}/00002")).origin == f"sbml-test-suite:{RELEASE}:numeric"
    assert sts.reference(case) == {
        case.origin: {
            "simulation.sedml/report": {
                "time": [0.0, 1.0, 2.0],
                "S1": [2.0, 1.2, 0.7],
                "S2": [0.0, 0.8, 1.3],
                "k1": [0.5, 0.5, 0.5],
            }
        }
    }


@pytest.mark.asyncio
async def test_the_sedml_asks_for_amounts_and_concentrations_as_the_settings_do(release: list[str]) -> None:
    case = await sts.case(f"{RELEASE}/00001")
    sedml = sts.sedml_document(case)
    assert 'numberOfPoints="2"' in sedml and 'outputEndTime="2.0"' in sedml
    assert 'xmlns:sbml="http://www.sbml.org/sbml/level3/version2/core"' in sedml
    assert "target=\"/sbml:sbml/sbml:model/sbml:listOfSpecies/sbml:species[@id='S1']\"" in sedml
    # S1 is a concentration in a compartment of size 2: its amount is twice it; S2 is an amount: its concentration half
    assert "<apply><times/><cn>2.0</cn><ci>v_S1</ci></apply>" in sedml
    assert "<apply><times/><cn>0.5</cn><ci>v_S2</ci></apply>" in sedml
    assert "<ci>v_k1</ci></math>" in sedml
    assert [label for label in ("time", "S1", "S2", "k1") if f'label="{label}"' in sedml] == ["time", "S1", "S2", "k1"]


@pytest.mark.asyncio
async def test_cases_the_sedml_cannot_express_say_why(release: list[str]) -> None:
    with pytest.raises(sts.CaseNotSupportedError, match="fixed, nonzero size"):
        sts.sedml_document(await sts.case(f"{RELEASE}/00002"))
    # unflattened (S11): the flattened id is not in the model as written
    with pytest.raises(sts.CaseNotSupportedError, match="unflattened"):
        sts.sedml_document(await sts.case(f"{RELEASE}/00003"))
    with pytest.raises(sts.CaseNotSupportedError, match="not a time course"):
        await sts.case(f"{RELEASE}/00004")


@pytest.mark.asyncio
async def test_a_case_is_judged_by_its_own_tolerances(release: list[str]) -> None:
    """The platform's score with the case's tolerances is the suite's own criterion, `|a - e| <= absolute + relative *
    |e|` with `e` the expected value (S4): just inside it is close, just outside it is not."""
    case = await sts.case(f"{RELEASE}/00001")
    tolerances = case.tolerances
    assert (tolerances.rel_tol, tolerances.abs_tol_min, tolerances.abs_tol_scale) == (1e-4, 1e-7, 0.0)
    expected = [0.0, 1.2, 1000.0]
    allowed = [1e-7 + 1e-4 * abs(e) for e in expected]
    inside = [e + 0.99 * a for e, a in zip(expected, allowed, strict=True)]
    outside = [e + 1.01 * a for e, a in zip(expected, allowed, strict=True)]
    assert score(inside, expected, tolerances) < 1 <= score(outside, expected, tolerances)


def test_a_suite_takes_sbml_test_suite_sources() -> None:
    Suite(name="s", description="d", sources=["sbml-test-suite:3.5.0/00001"])
    with pytest.raises(ValueError, match="sbml-test-suite:<release>/<case>"):
        Suite(name="s", description="d", sources=["sbml:00001"])


@needs_translator
@pytest.mark.asyncio
async def test_the_archive_translates_for_every_solver_with_the_references_labels(
    release: list[str], tmp_path: Path
) -> None:
    case, path = await sts.case_archive(f"{RELEASE}/00001")
    with zipfile.ZipFile(path) as z:
        assert z.read("model.xml").decode() == case.model  # as written: never flattened (S11)
    solvers = chosen_solvers(["copasi", "tellurium", "vcell"])
    manifests = [Path(__file__).resolve().parents[1] / "fixtures" / "resources" / "registry_env.interfaces.json"]
    translation = await translate(path, solvers, tmp_path, manifests)
    (task,) = translation.tasks
    assert sorted(task.archives) == ["copasi", "tellurium", "vcell"]
    expected = sts.reference(case)[case.origin]
    assert {f"{task.sedml}/{r}": info["labels"] for r, info in task.reports.items()} == {
        key: list(series) for key, series in expected.items()
    }


@needs_translator
@pytest.mark.asyncio
async def test_a_suite_run_compares_with_the_expected_results(
    client: httpx.AsyncClient,
    submitted: dict[str, Any],
    release: list[str],
    database_service: DatabaseServiceSQL,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_suite = Suite(
        name="sbml-test",
        description="two cases, one the SED-ML cannot express",
        sources=[f"sbml-test-suite:{RELEASE}/00001", f"sbml-test-suite:{RELEASE}/00003"],
        solvers=["copasi", "tellurium", "vcell"],
    )
    monkeypatch.setattr(suites, "load_suites", lambda: {"sbml-test": test_suite})
    assert (await client.post("/suites/sbml-test/run", params={"environment_version": "default"})).status_code == 200
    await _settled(database_service)

    runs = submitted["runs"]
    assert sorted(r[0].labels["solver"] for r in runs) == ["copasi", "tellurium", "vcell"]
    assert {r[0].labels["source"] for r in runs} == {"sbml-test-suite"}
    assert {r[0].labels["sbml_test_case"] for r in runs} == {f"{RELEASE}/00001"}

    view = (await client.get("/suites/sbml-test/runs/1")).json()
    failed = next(r for r in view["rows"] if r["failure"])
    assert failed["source"] == f"sbml-test-suite:{RELEASE}/00003" and "unflattened" in failed["failure"]
    row = next(r for r in view["rows"] if not r["failure"])
    comparison = (await client.get(f"/comparisons/{row['comparison_id']}")).json()
    assert comparison["source"] == f"sbml-test-suite:{RELEASE}/00001"
    found = await database_service.get_comparisons_db().get(row["comparison_id"])
    assert found is not None and [r.origin for r in found.references] == [f"sbml-test-suite:{RELEASE}:analytic"]
    # the case's tolerances, not the suite's, and the page can say where they came from (S4)
    assert comparison["settings"]["tolerances"] == {"rel_tol": 1e-4, "abs_tol_min": 1e-7, "abs_tol_scale": 0.0}
    assert comparison["settings"]["tolerances_from"] == f"sbml-test-suite:{RELEASE}/00001"
