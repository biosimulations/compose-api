"""biosim's verify API as an oracle for SED-ML comparisons (docs/plan-verify-oracle.md, V2).

`POST /verify/omex` runs an archive on BioSimulators' simulators at biosimulations.org and scores every pair of them;
`GET /verify/{workflow_id}` reads the result when it is done. We send the archive the comparison ran (D4) and keep two
things from the output: each simulator's series as a reference (D1, scored against our solvers by our own
`compare.py`), and whether the simulators agree with each other (`verify_close`).

The models mirror biosim-server's `biosim_verify/models.py` (kept in step by a recorded response,
`tests/fixtures/resources/verify/`), with only the fields used here typed; the rest is kept as it came.
"""

import io
import time
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Callable
from enum import StrEnum
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict

from compose_api.config import get_settings
from compose_api.sedml.models import Tolerances

Series = list[float]
#: The dataset types `reports.h5` gives a report (a plot's data is the same series again, and our comparisons are
#: over reports).
REPORT_TYPES = ("SedReport", "SedRe")
MANIFEST = "manifest.xml"
OMEX_NS = "http://identifiers.org/combine.specifications/omex-manifest"


class VerifyStatus(StrEnum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RUN_ID_NOT_FOUND = "RUN_ID_NOT_FOUND"

    @property
    def is_done(self) -> bool:
        return self in (VerifyStatus.COMPLETED, VerifyStatus.FAILED, VerifyStatus.RUN_ID_NOT_FOUND)


class _Loose(BaseModel):
    model_config = ConfigDict(extra="allow")


class ComparisonStatistics(_Loose):
    dataset_name: str
    simulator_version_i: str  # <name>:<version>
    simulator_version_j: str
    var_names: list[str]
    score: list[float] | None = None
    is_close: list[bool] | None = None
    error_message: str | None = None


class Hdf5Values(_Loose):
    shape: list[int]
    values: list[float]


class RunData(_Loose):
    run_id: str
    dataset_name: str  # <sedml>/<output>
    var_names: list[str]  # the SED-ML data set labels
    data: Hdf5Values  # row-major, shape (len(var_names), time points)


class SimulatorFailure(_Loose):
    simulator_version: str
    biosimulations_run_id: str | None = None
    error_message: str | None = None


class VerifyResults(_Loose):
    sims_run_info: list[dict[str, Any]] = []
    comparison_statistics: dict[str, list[list[ComparisonStatistics]]] = {}
    sim_run_data: list[RunData] | None = None


class VerifyOutput(_Loose):
    workflow_id: str
    workflow_status: VerifyStatus
    workflow_error: str | None = None
    failed_simulators: list[SimulatorFailure] = []
    workflow_results: VerifyResults | None = None


class VerifyRateLimitedError(Exception):
    """biosim's workflow budget is spent: try again after ``retry_after`` seconds."""

    def __init__(self, retry_after: float) -> None:
        super().__init__(f"rate limited; retry after {retry_after:.0f} s")
        self.retry_after = retry_after


class VerifyRejectedError(Exception):
    """biosim refused the request (a 4xx other than 429): retrying the same request cannot help."""


class VerifyClient:
    """The two calls the oracle needs. A transport error or a 5xx raises ``httpx.HTTPError`` (transient)."""

    def __init__(self, base_url: str | None = None, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.base_url = (base_url or get_settings().biosim_api_url).rstrip("/")
        self.transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base_url, transport=self.transport, timeout=60.0)

    async def verify_omex(
        self, archive: bytes, filename: str, simulators: list[str], tolerances: Tolerances, description: str,
        workflow_id_prefix: str,
    ) -> VerifyOutput:  # fmt: skip
        params: list[tuple[str, str | int | float | bool | None]] = [
            ("include_outputs", "true"),
            ("user_description", description),
            ("workflow_id_prefix", workflow_id_prefix),
            ("rel_tol", tolerances.rel_tol),
            ("abs_tol_min", tolerances.abs_tol_min),
            ("abs_tol_scale", tolerances.abs_tol_scale),
            *(("simulators", s) for s in simulators),
        ]
        async with self._client() as client:
            response = await client.post(
                "/verify/omex", params=params, files={"uploaded_file": (filename, archive, "application/zip")}
            )
        return VerifyOutput.model_validate_json(_checked(response))

    async def get(self, workflow_id: str) -> VerifyOutput:
        async with self._client() as client:
            response = await client.get(f"/verify/{workflow_id}")
        return VerifyOutput.model_validate_json(_checked(response))


def _checked(response: httpx.Response) -> bytes:
    if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
        try:
            retry_after = float(response.headers.get("Retry-After", "60"))
        except ValueError:
            retry_after = 60.0
        raise VerifyRateLimitedError(retry_after)
    if 400 <= response.status_code < 500:
        raise VerifyRejectedError(f"{response.status_code}: {response.text[:500]}")
    response.raise_for_status()
    return response.content


class RateBudget:
    """A token bucket: at most ``per_minute`` requests a minute, in a burst of at most ``burst``. biosim's budget is
    per caller over a fixed window; staying under it keeps the 429 the exception (D5)."""

    def __init__(self, per_minute: float, burst: int = 1, clock: Callable[[], float] = time.monotonic) -> None:
        self.rate = per_minute / 60.0
        self.burst = float(burst)
        self.clock = clock
        self.tokens = float(burst)
        self.stamp = clock()

    def take(self) -> float:
        """Take a token and return 0, or return the seconds until one is available (taking nothing)."""
        now = self.clock()
        self.tokens = min(self.burst, self.tokens + (now - self.stamp) * self.rate)
        self.stamp = now
        if self.tokens >= 1:
            self.tokens -= 1
            return 0.0
        return (1 - self.tokens) / self.rate


def sanitize_archive(content: bytes) -> tuple[bytes, list[str]]:
    """The archive with manifest entries whose files it does not contain removed, and those locations.

    BioModels archives often list files they do not ship (13 in BIOMD0000000012's); BioSimulators refuses such an
    archive, so the verification would come back with no runs (docs/plan-verify-oracle.md, D4 amended). The archive
    is otherwise unchanged."""
    with zipfile.ZipFile(io.BytesIO(content)) as src:
        names = set(src.namelist())
        manifest_name = next((n for n in names if n.lstrip("./") == MANIFEST), None)
        if manifest_name is None:
            return content, []
        ET.register_namespace("", OMEX_NS)
        root = ET.fromstring(src.read(manifest_name))  # noqa: S314 -- our own fetched archive, rewritten only
        dropped: list[str] = []
        for entry in list(root):
            location = entry.get("location", "")
            path = location.removeprefix("./")
            if path in ("", ".", MANIFEST):  # the archive itself, and the manifest
                continue
            if path not in names and f"./{path}" not in names:
                root.remove(entry)
                dropped.append(location)
        if not dropped:
            return content, []
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
            for info in src.infolist():
                data = src.read(info) if info.filename != manifest_name else ET.tostring(root, xml_declaration=True)
                dst.writestr(info, data)
        return out.getvalue(), dropped


def _run_simulators(output: VerifyOutput) -> dict[str, str]:
    """Each run's origin, ``biosimulators:<name>:<version>``, by run id."""
    results = output.workflow_results
    origins: dict[str, str] = {}
    for info in results.sims_run_info if results else []:
        run = info.get("biosim_sim_run", {})
        version = run.get("simulator_version", {})
        if run.get("id") and version.get("id"):
            origins[run["id"]] = f"biosimulators:{version['id']}:{version.get('version', '')}"
    return origins


def _report_datasets(output: VerifyOutput) -> set[str]:
    """The datasets `reports.h5` marks as reports."""
    results = output.workflow_results
    found: set[str] = set()
    for info in results.sims_run_info if results else []:
        for group in info.get("hdf5_file", {}).get("groups", []):
            for dataset in group.get("datasets", []):
                kind = next((a.get("value") for a in dataset.get("attributes", []) if a.get("key") == "_type"), None)
                if kind in REPORT_TYPES:
                    found.add(dataset["name"])
    return found


def references_from_output(output: VerifyOutput) -> dict[str, dict[str, dict[str, Series]]]:
    """Each BioSimulators simulator's reports, as references: ``{origin: {"<sedml>/<report>": {label: series}}}``,
    the shape `sources.biomodel_references` gives (V1)."""
    results = output.workflow_results
    if results is None or not results.sim_run_data:
        return {}
    origins = _run_simulators(output)
    reports = _report_datasets(output)
    references: dict[str, dict[str, dict[str, Series]]] = {}
    for run in results.sim_run_data:
        origin = origins.get(run.run_id)
        if origin is None or run.dataset_name not in reports:
            continue
        rows, columns = [*run.data.shape, 0, 0][:2]
        if rows != len(run.var_names) or len(run.data.values) != rows * columns:
            continue  # not the layout biosim documents; better no reference than a wrong one
        values = run.data.values
        references.setdefault(origin, {})[run.dataset_name] = {
            label: values[i * columns : (i + 1) * columns] for i, label in enumerate(run.var_names)
        }
    return references


def verify_close(output: VerifyOutput, datasets: set[str] | None = None) -> bool | None:
    """Whether BioSimulators' simulators agree with each other on every report (or ``datasets``): every distinct pair
    close on every variable. None when fewer than two simulators produced results, or nothing was scored."""
    results = output.workflow_results
    if results is None or len(_run_simulators(output)) < 2:
        return None
    wanted = datasets if datasets is not None else _report_datasets(output)
    scored = False
    for name, matrix in results.comparison_statistics.items():
        if wanted and name not in wanted:
            continue
        for i, row in enumerate(matrix):
            for stats in row[i + 1 :]:
                if stats.is_close is None:
                    return False  # an error comparing them (different lengths, a missing variable)
                scored = True
                if not all(stats.is_close):
                    return False
    return True if scored else None


def agrees_with(result: dict[str, Any] | None, origins: list[str]) -> list[str]:
    """Our solvers BioSimulators' simulators agree with (docs/plan-verify-oracle.md, V5): those whose every data set
    scored against the verification's references (``origins``) is close to each of them. A data set that could not be
    scored (missing on one side) is no evidence either way; a solver with nothing scored against them is not counted."""
    verdicts: dict[str, bool] = {}
    for report in ((result or {}).get("reports") or {}).values():
        for pairs in (report.get("labels") or {}).values():
            for pair, scored in pairs.items():
                solver, _, origin = pair.partition("|")
                if origin in origins and scored.get("close") is not None:
                    verdicts[solver] = verdicts.get(solver, True) and scored["close"] is True
    return sorted(solver for solver, close in verdicts.items() if close)


def stored_output(output: VerifyOutput) -> dict[str, Any]:
    """The output as kept on the verification: without the series, which are kept as references."""
    data = output.model_dump(mode="json")
    if data.get("workflow_results"):
        data["workflow_results"].pop("sim_run_data", None)
    return data
