"""The SBML Test Suite as a source (docs/plan-sbml-test-suite.md, step 2): `sbml-test-suite:<release>/<case>`.

A release's semantic archive is fetched from GitHub once, checked against the sha256 pinned in `RELEASES`, and
cached (`settings.sources_cache_dir`); its cases are not committed here (finding 8). The release ships no SED-ML
(finding 3), so each case's archive is written from its files: the model at its highest SBML level and version, and a
SED-ML document with one uniform time course and one report of the case's variables, each an amount or a
concentration as its settings say (S2). The case's expected results are the reference, under an origin that says how
they were made (S3, S10).

`comp` models are written as they are, never flattened (S11): those cases test a solver's reading of `comp`.
"""

import hashlib
import io
import re
import tempfile
import zipfile
from pathlib import Path
from xml.sax.saxutils import quoteattr

from pydantic import BaseModel, Field

from compose_api.sedml.models import Tolerances
from compose_api.sedml.sources import (
    Series,
    SourceNotFoundError,
    SourceUnavailableError,
    _cache,
    _get_bytes,
)

KIND = "sbml-test-suite"
REPOSITORY = "https://github.com/sbmlteam/sbml-test-suite"


class Release(BaseModel):
    asset: str  # the semantic archive's file name on the GitHub release
    sha256: str


#: The releases a source may name, each pinned by its semantic archive's hash. A new release is a change here.
RELEASES: dict[str, Release] = {
    "3.5.0": Release(
        asset="semantic_tests_v3.5.0.zip",
        sha256="523bed258b384f761da211c233c5b4a7f28cd6cc2197ff709c6e253a6eacea77",
    ),
}

_IDENT = re.compile(r"^(?P<release>\d+\.\d+\.\d+)/(?P<case>\d{5})$")
SEDML_FILE = "simulation.sedml"
MODEL_FILE = "model.xml"
REPORT_ID = "report"
TIME_LABEL = "time"


class CaseSettings(BaseModel):
    """A case's `-settings.txt`."""

    start: float
    duration: float
    steps: int = Field(gt=0)
    variables: list[str]
    absolute: float
    relative: float
    amount: list[str] = Field(default_factory=list)
    concentration: list[str] = Field(default_factory=list)


class CaseInfo(BaseModel):
    """What a case's `-model.m` header says of it."""

    synopsis: str = ""
    component_tags: list[str] = Field(default_factory=list)
    test_tags: list[str] = Field(default_factory=list)
    test_type: str = ""
    levels: list[str] = Field(default_factory=list)
    generated_by: str = ""
    packages: list[str] = Field(default_factory=list)


class Case(BaseModel):
    release: str
    case: str
    settings: CaseSettings
    info: CaseInfo
    model_file: str  # the archive member chosen: the highest level and version
    model: str
    results: dict[str, Series]  # the expected values by column, `time` first

    @property
    def source(self) -> str:
        return f"{KIND}:{self.release}/{self.case}"

    @property
    def tolerances(self) -> Tolerances:
        """The case's own pass criterion, `|actual - expected| <= absolute + relative * |expected|` (finding 4), as the
        platform's score: with no scaled term its `atol` is `absolute`, and it scores a solver against the reference
        with the reference as `b` (docs/plan-sbml-test-suite.md, S4)."""
        return Tolerances(rel_tol=self.settings.relative, abs_tol_min=self.settings.absolute, abs_tol_scale=0.0)

    @property
    def origin(self) -> str:
        """The reference's origin: the release, and how its values were made (S10), `analytic` or `numeric`."""
        how = self.info.generated_by.strip().lower() or "unknown"
        return f"{KIND}:{self.release}:{how}"


class CaseNotSupportedError(ValueError):
    """The case cannot be written as a SED-ML time course; the message says why."""


def parse_source(ident: str) -> tuple[str, str]:
    """`<release>/<case>` as (release, case); :class:`SourceNotFoundError` if malformed or the release is unpinned."""
    m = _IDENT.match(ident)
    if m is None:
        raise SourceNotFoundError(f"{ident!r}: an SBML Test Suite source is {KIND}:<release>/<case>, e.g. 3.5.0/00001")
    if m["release"] not in RELEASES:
        raise SourceNotFoundError(
            f"SBML Test Suite release {m['release']} is not pinned; there are {', '.join(RELEASES)}"
        )
    return m["release"], m["case"]


async def release_archive(release: str) -> Path:
    """The release's semantic archive, fetched once and checked against its pinned hash."""
    pinned = RELEASES[release]
    path = _cache(KIND, pinned.asset)
    if not path.exists():
        content = await _get_bytes(f"{REPOSITORY}/releases/download/{release}/{pinned.asset}")
        digest = hashlib.sha256(content).hexdigest()
        if digest != pinned.sha256:
            raise SourceUnavailableError(f"{pinned.asset}: sha256 {digest}, not the pinned {pinned.sha256}")
        partial = path.with_suffix(".partial")
        partial.write_bytes(content)
        partial.replace(path)
    return path


async def case(ident: str) -> Case:
    release, number = parse_source(ident)
    return read_case(await release_archive(release), release, number)


def read_case(archive: Path, release: str, number: str) -> Case:
    with zipfile.ZipFile(archive) as z:
        prefix = f"semantic/{number}/{number}-"
        names = [n for n in z.namelist() if n.startswith(prefix)]
        if not names:
            raise SourceNotFoundError(f"SBML Test Suite {release} has no case {number}")

        def text(suffix: str) -> str:
            name = prefix + suffix
            if name not in names:
                raise SourceNotFoundError(f"SBML Test Suite {release} case {number} has no {suffix}")
            return z.read(name).decode("utf-8")

        models = sorted(
            (n for n in names if re.search(r"-sbml-l\dv\d\.xml$", n)), key=lambda n: _level_version(n), reverse=True
        )
        if not models:
            raise SourceNotFoundError(f"SBML Test Suite {release} case {number} has no SBML model")
        info = parse_info(text("model.m"))
        if info.test_type != "TimeCourse":
            raise CaseNotSupportedError(f"case {number} is a {info.test_type or 'untyped'} test, not a time course")
        return Case(
            release=release,
            case=number,
            settings=parse_settings(text("settings.txt")),
            info=info,
            model_file=models[0].rsplit("/", 1)[-1],
            model=z.read(models[0]).decode("utf-8"),
            results=parse_results(text("results.csv")),
        )


def _level_version(name: str) -> tuple[int, int]:
    m = re.search(r"-sbml-l(\d)v(\d)\.xml$", name)
    return (int(m[1]), int(m[2])) if m else (0, 0)


def _names(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def parse_settings(text: str) -> CaseSettings:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip()] = value.strip()
    return CaseSettings(
        start=float(fields.get("start") or "0"),
        duration=float(fields["duration"]),
        steps=int(float(fields["steps"])),
        variables=_names(fields.get("variables", "")),
        absolute=float(fields["absolute"]),
        relative=float(fields["relative"]),
        amount=_names(fields.get("amount", "")),
        concentration=_names(fields.get("concentration", "")),
    )


_INFO_KEYS = {
    "synopsis": "synopsis",
    "componentTags": "component_tags",
    "testTags": "test_tags",
    "testType": "test_type",
    "levels": "levels",
    "generatedBy": "generated_by",
    "packagesPresent": "packages",
}


def parse_info(text: str) -> CaseInfo:
    """The `key: value` header of a `-model.m`; a value continues on the lines that follow it until the next key or a
    blank line."""
    fields: dict[str, str] = {}
    current: str | None = None
    for line in text.splitlines():
        m = re.match(r"^(\w+):\s*(.*)$", line)
        if m and m[1] in _INFO_KEYS:
            current = _INFO_KEYS[m[1]]
            fields[current] = m[2].strip()
        elif current and line.strip():
            fields[current] += " " + line.strip()
        else:
            current = None
    lists = {"component_tags", "test_tags", "levels", "packages"}
    return CaseInfo.model_validate({k: _names(v) if k in lists else v for k, v in fields.items()})


def parse_results(text: str) -> dict[str, Series]:
    rows = [line.split(",") for line in text.splitlines() if line.strip()]
    header = [h.strip() for h in rows[0]]
    columns: dict[str, Series] = {h: [] for h in header}
    for row in rows[1:]:
        for h, value in zip(header, row, strict=True):
            columns[h].append(float(value))
    if header[0].lower() != TIME_LABEL:
        raise ValueError(f"the results' first column is {header[0]!r}, not time")
    return {TIME_LABEL: columns.pop(header[0]), **columns}


# --- the archive ----------------------------------------------------------------------------------------------------


class _Target(BaseModel):
    xpath: str
    # what the value read at `xpath` is multiplied by: a species' compartment size, or its inverse, when the settings
    # ask for an amount and the species is a concentration or the other way round (finding 5)
    scale: float = 1.0


def _targets(model_xml: str, settings: CaseSettings) -> dict[str, _Target]:
    """Each variable's SED-ML target in the model as written: an element of the top-level model, by id.

    process-bigraph-lang translates a data generator only when it is a linear combination of its variables (`2*x`,
    `x+y`), so an amount is made from a concentration with the compartment's size as a number, which needs a size fixed
    in the model: a constant compartment, with a size, that no rule or initial assignment sets."""
    import libsbml  # type: ignore[import-untyped]

    document = libsbml.readSBMLFromString(model_xml)
    if document.getNumErrors(libsbml.LIBSBML_SEV_FATAL) or document.getModel() is None:
        raise CaseNotSupportedError("libsbml cannot read the model")
    model = document.getModel()
    found: dict[str, _Target] = {}
    for name in settings.variables:
        element = model.getElementBySId(name)
        if element is None:
            # a `comp` case names its submodels' elements by their flattened id (`submod1__p`), which the unflattened
            # model does not have (S11): there is no SED-ML target for it yet
            raise CaseNotSupportedError(f"{name!r} is not an element of the model as written (unflattened)")
        target = _Target(xpath=_xpath(element))
        if element.getTypeCode() == libsbml.SBML_SPECIES:
            only_substance = bool(element.getHasOnlySubstanceUnits())
            to_amount = name in settings.amount and not only_substance
            to_concentration = name in settings.concentration and only_substance
            if to_amount or to_concentration:
                size = _fixed_size(model, element.getCompartment())
                if size is None or size == 0:
                    raise CaseNotSupportedError(
                        f"{name!r} is reported as {'an amount' if to_amount else 'a concentration'}, which needs its "
                        f"compartment {element.getCompartment()!r} to have a fixed, nonzero size"
                    )
                target.scale = size if to_amount else 1 / size
        found[name] = target
    return found


def _fixed_size(model: object, compartment_id: str) -> float | None:
    compartment = model.getCompartment(compartment_id)  # type: ignore[attr-defined]
    if compartment is None or not compartment.getConstant() or not compartment.isSetSize():
        return None
    if model.getInitialAssignmentBySymbol(compartment_id) is not None:  # type: ignore[attr-defined]
        return None
    if model.getRuleByVariable(compartment_id) is not None:  # type: ignore[attr-defined]
        return None
    return float(compartment.getSize())


def _xpath(element: object) -> str:
    """`/sbml:sbml/sbml:model/sbml:listOfSpecies/sbml:species[@id='S1']`, from the element up to the document."""
    steps: list[str] = []
    current = element
    while current is not None and current.getElementName() != "sbml":  # type: ignore[attr-defined]
        step = f"sbml:{current.getElementName()}"  # type: ignore[attr-defined]
        if current.isSetId() and current.getElementName() != "model":  # type: ignore[attr-defined]
            step += f"[@id='{current.getId()}']"  # type: ignore[attr-defined]
        steps.append(step)
        current = current.getParentSBMLObject()  # type: ignore[attr-defined]
    return "/sbml:sbml/" + "/".join(reversed(steps))


def sedml_document(case: Case) -> str:
    """One uniform time course and one report: `time`, then each variable, as an amount or a concentration as the
    settings ask whatever the species' own `hasOnlySubstanceUnits` (finding 5)."""
    import libsbml

    s = case.settings
    targets = _targets(case.model, s)
    document = libsbml.readSBMLFromString(case.model)
    namespace = libsbml.SBMLNamespaces.getSBMLNamespaceURI(document.getLevel(), document.getVersion())
    generators: list[str] = [
        '<dataGenerator id="dg_time"><listOfVariables>'
        '<variable id="v_time" taskReference="task" symbol="urn:sedml:symbol:time"/>'
        '</listOfVariables><math xmlns="http://www.w3.org/1998/Math/MathML"><ci>v_time</ci></math></dataGenerator>'
    ]
    data_sets = ['<dataSet id="ds_time" label="time" dataReference="dg_time"/>']
    for name in s.variables:
        t = targets[name]
        math = f"<ci>v_{name}</ci>"
        if t.scale != 1.0:
            math = f"<apply><times/><cn>{t.scale!r}</cn>{math}</apply>"
        generators.append(
            f'<dataGenerator id="dg_{name}"><listOfVariables>'
            f'<variable id="v_{name}" taskReference="task" target={quoteattr(t.xpath)}/></listOfVariables>'
            f'<math xmlns="http://www.w3.org/1998/Math/MathML">{math}</math></dataGenerator>'
        )
        data_sets.append(f'<dataSet id="ds_{name}" label={quoteattr(name)} dataReference="dg_{name}"/>')
    end = s.start + s.duration
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<sedML xmlns="http://sed-ml.org/sed-ml/level1/version3" level="1" version="3" '
        f"xmlns:sbml={quoteattr(namespace)}>"
        f'<listOfSimulations><uniformTimeCourse id="sim" initialTime="{s.start!r}" outputStartTime="{s.start!r}" '
        f'outputEndTime="{end!r}" numberOfPoints="{s.steps}"><algorithm kisaoID="KISAO:0000019"/></uniformTimeCourse>'
        "</listOfSimulations>"
        f'<listOfModels><model id="model" language="urn:sedml:language:sbml" source="{MODEL_FILE}"/></listOfModels>'
        '<listOfTasks><task id="task" modelReference="model" simulationReference="sim"/></listOfTasks>'
        f"<listOfDataGenerators>{''.join(generators)}</listOfDataGenerators>"
        f'<listOfOutputs><report id="{REPORT_ID}" name={quoteattr(f"case {case.case}")}><listOfDataSets>'
        f"{''.join(data_sets)}</listOfDataSets></report></listOfOutputs>"
        "</sedML>\n"
    )


_MANIFEST = """<?xml version="1.0" encoding="UTF-8"?>
<omexManifest xmlns="http://identifiers.org/combine.specifications/omex-manifest">
  <content location="." format="http://identifiers.org/combine.specifications/omex"/>
  <content location="./manifest.xml" format="http://identifiers.org/combine.specifications/omex-manifest"/>
  <content location="./{model}" format="http://identifiers.org/combine.specifications/sbml"/>
  <content location="./{sedml}" format="http://identifiers.org/combine.specifications/sed-ml" master="true"/>
</omexManifest>
"""


def write_archive(case: Case, path: Path) -> Path:
    """The case as a COMBINE archive: the model unchanged (never flattened, S11), its SED-ML, a manifest."""
    sedml = sedml_document(case)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.xml", _MANIFEST.format(model=MODEL_FILE, sedml=SEDML_FILE))
        z.writestr(MODEL_FILE, case.model)
        z.writestr(SEDML_FILE, sedml)
    path.write_bytes(buffer.getvalue())
    return path


async def case_archive(ident: str) -> tuple[Case, Path]:
    """The case and its archive, written afresh (it is cheap, and a cached one would outlive a change to the writer)."""
    found = await case(ident)
    directory = Path(tempfile.mkdtemp(prefix="sbml-test-suite-"))
    return found, write_archive(found, directory / f"{found.case}.omex")


def reference(case: Case) -> dict[str, dict[str, dict[str, Series]]]:
    """The expected results as `{origin: {"<sedml>/<report>": {label: series}}}`, the shape `service.submit` takes."""
    return {case.origin: {f"{SEDML_FILE}/{REPORT_ID}": case.results}}
