"""Where SED-ML archives come from besides uploads (docs/plan-sedml.md, phase 4): EBI BioModels and biosimulations.org.

Read-only and public. Archives are cached on disk by id and upstream revision (`settings.sources_cache_dir`), so a
model is fetched once per revision; lists and metadata are cached in memory for a short while.

- BioModels: `GET /biomodels/search` (search), `GET /biomodels/{id}` (metadata, the latest revision),
  `GET /biomodels/model/download/{id}` (a COMBINE archive: the SBML, its SED-ML, extras).
- biosimulations.org: `GET /projects` (id and run), `GET /runs/{run}` (the run's simulator), `GET /runs/{run}/download`
  (the project's archive), `GET /results/{run}/download` (the run's outputs: `outputs/reports.h5`, the reference).
"""

import io
import re
import time
import zipfile
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel

from compose_api.config import get_settings

BIOMODELS = "https://www.ebi.ac.uk/biomodels"
BIOSIMULATIONS = "https://api.biosimulations.org"
_BIOMODEL_ID = re.compile(r"^(BIOMD|MODEL)\d{10}$")
_PROJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,199}$")
_TTL = 3600.0
_memo: dict[str, tuple[float, Any]] = {}

Series = list[float]


class SourceNotFoundError(LookupError):
    pass


class SourceUnavailableError(RuntimeError):
    """The upstream service did not answer as expected."""


class BiomodelHit(BaseModel):
    id: str
    name: str
    format: str | None = None
    url: str | None = None


class BiomodelInfo(BaseModel):
    id: str
    name: str
    format: str | None = None
    curation: str | None = None
    revision: int | None = None
    publication: str | None = None
    url: str


class ProjectInfo(BaseModel):
    id: str
    run: str
    created: str | None = None
    updated: str | None = None
    simulator: str | None = None
    simulator_version: str | None = None
    url: str


def check_biomodel_id(model_id: str) -> str:
    if not _BIOMODEL_ID.match(model_id):
        raise SourceNotFoundError(f"{model_id!r} is not a BioModels id (BIOMD0000000012, MODEL…)")
    return model_id


def check_project_id(project_id: str) -> str:
    if not _PROJECT_ID.match(project_id):
        raise SourceNotFoundError(f"{project_id!r} is not a biosimulations.org project id")
    return project_id


async def _get(url: str, *, json: bool = True, params: dict[str, Any] | None = None) -> Any:
    headers = {"Accept": "application/json"} if json else {}
    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            response = await client.get(url, params=params, headers=headers)
    except httpx.HTTPError as e:
        raise SourceUnavailableError(f"{url}: {e}") from e
    if response.status_code == 404:
        raise SourceNotFoundError(url)
    if response.status_code != 200:
        raise SourceUnavailableError(f"{url}: HTTP {response.status_code}")
    return response.json() if json else response.content


async def _memoized(key: str, fetch: Any) -> Any:
    now = time.monotonic()
    hit = _memo.get(key)
    if hit is not None and now - hit[0] < _TTL:
        return hit[1]
    value = await fetch()
    _memo[key] = (now, value)
    return value


def _cache(*parts: str) -> Path:
    path = Path(get_settings().sources_cache_dir).joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


# --- BioModels ----------------------------------------------------------------------------------------------------


async def search_biomodels(query: str, limit: int = 20, curated: bool = True) -> list[BiomodelHit]:
    text = f'{query} AND curationstatus:"Manually curated"' if curated else query
    data = await _get(f"{BIOMODELS}/search", params={"query": text, "numResults": limit, "format": "json"})
    return [
        BiomodelHit(id=m["id"], name=m.get("name") or m["id"], format=m.get("format"), url=m.get("url"))
        for m in data.get("models", [])
    ]


async def biomodel(model_id: str) -> BiomodelInfo:
    check_biomodel_id(model_id)

    async def fetch() -> BiomodelInfo:
        data = await _get(f"{BIOMODELS}/{model_id}", params={"format": "json"})
        revisions = (data.get("history") or {}).get("revisions") or []
        return BiomodelInfo(
            id=model_id,
            name=data.get("name") or model_id,
            format=(data.get("format") or {}).get("name"),
            curation=data.get("curationStatus"),
            revision=revisions[-1].get("version") if revisions else None,
            publication=(data.get("publication") or {}).get("title"),
            url=f"https://www.ebi.ac.uk/biomodels/{model_id}",
        )

    info: BiomodelInfo = await _memoized(f"biomodels:{model_id}", fetch)
    return info


async def biomodel_archive(model_id: str) -> Path:
    """The model's COMBINE archive (latest revision), cached."""
    info = await biomodel(model_id)
    path = _cache("biomodels", f"{model_id}.{info.revision or 0}.omex")
    if not path.exists():
        content = await _get(f"{BIOMODELS}/model/download/{model_id}", json=False)
        _check_zip(content, model_id)
        path.write_bytes(content)
    return path


# --- biosimulations.org -------------------------------------------------------------------------------------------


async def _projects() -> list[dict[str, Any]]:
    async def fetch() -> list[dict[str, Any]]:
        data: list[dict[str, Any]] = await _get(f"{BIOSIMULATIONS}/projects")
        return data

    projects: list[dict[str, Any]] = await _memoized("biosimulations:projects", fetch)
    return projects


async def search_projects(query: str, limit: int = 20) -> list[ProjectInfo]:
    q = query.lower()
    found = [p for p in await _projects() if q in p["id"].lower()][:limit]
    return [_project(p) for p in found]


async def project(project_id: str) -> ProjectInfo:
    check_project_id(project_id)
    data = await _get(f"{BIOSIMULATIONS}/projects/{project_id}")
    info = _project(data)
    try:
        run = await _get(f"{BIOSIMULATIONS}/runs/{info.run}")
        info.simulator, info.simulator_version = run.get("simulator"), run.get("simulatorVersion")
    except (SourceNotFoundError, SourceUnavailableError):
        pass
    return info


async def legacy_projects(model_id: str) -> list[ProjectInfo]:
    """The biosimulations.org projects imported from a BioModels entry: those named ``<model id>_<simulator>_<title>``
    (275 of the first 300 curated entries have one; docs/plan-verify-oracle.md, V1)."""
    check_biomodel_id(model_id)
    prefix = f"{model_id}_"
    return [_project(p) for p in await _projects() if str(p.get("id", "")).startswith(prefix)]


async def biomodel_references(model_id: str) -> dict[str, dict[str, dict[str, Series]]]:
    """A BioModels entry's original BioSimulators results, from its biosimulations.org projects' runs, as references:
    ``{"biosimulations:<simulator>": {"<sedml>/<report>": {label: series}}}``. Their archives are the entry's own, so
    the report names line up with the comparison's. A project whose results cannot be read is skipped: a reference is
    evidence, never a reason to refuse the run."""
    references: dict[str, dict[str, dict[str, Series]]] = {}
    try:
        found = await legacy_projects(model_id)
    except (SourceNotFoundError, SourceUnavailableError):
        return references
    for legacy in found:
        try:
            info = await project(legacy.id)
            reference = await project_reference(legacy.id)
        except (SourceNotFoundError, SourceUnavailableError, OSError, zipfile.BadZipFile, ValueError, KeyError):
            continue
        if reference:
            references.setdefault(f"biosimulations:{info.simulator or info.run}", reference)
    return references


async def project_archive(project_id: str) -> Path:
    """The project's archive (its run's input), cached by its last update."""
    info = await project(project_id)
    stamp = re.sub(r"\W", "", info.updated or "0")
    path = _cache("biosimulations", f"{project_id}.{stamp}.omex")
    if not path.exists():
        content = await _get(f"{BIOSIMULATIONS}/runs/{info.run}/download", json=False)
        _check_zip(content, project_id)
        path.write_bytes(content)
    return path


async def project_reference(project_id: str) -> dict[str, dict[str, Series]]:
    """The original run's reports (`outputs/reports.h5`) as `{"<sedml>/<report>": {label: series}}`."""
    info = await project(project_id)
    stamp = re.sub(r"\W", "", info.updated or "0")
    path = _cache("biosimulations", f"{project_id}.{stamp}.results.zip")
    if not path.exists():
        path.write_bytes(await _get(f"{BIOSIMULATIONS}/results/{info.run}/download", json=False))
    with zipfile.ZipFile(path) as z:
        name = next((n for n in z.namelist() if n.endswith("reports.h5")), None)
        if name is None:
            return {}
        return reports_from_h5(z.read(name))


def reports_from_h5(content: bytes) -> dict[str, dict[str, Series]]:
    """A BioSimulators `reports.h5` as `{"<sedml>/<output>": {label: series}}`, reports only (not plots)."""
    import h5py  # type: ignore[import-untyped]

    out: dict[str, dict[str, Series]] = {}
    with h5py.File(io.BytesIO(content), "r") as f:

        def visit(name: str, obj: Any) -> None:
            if not isinstance(obj, h5py.Dataset) or obj.attrs.get("_type") not in ("SedReport", "SedRe"):
                return
            labels = [str(x) for x in obj.attrs.get("sedmlDataSetLabels", [])]
            values = obj[()]
            out[name] = {label: [float(v) for v in values[i]] for i, label in enumerate(labels)}

        f.visititems(visit)
    return out


def _project(data: dict[str, Any]) -> ProjectInfo:
    return ProjectInfo(
        id=data["id"],
        run=data["simulationRun"],
        created=data.get("created"),
        updated=data.get("updated"),
        url=f"https://biosimulations.org/projects/{data['id']}",
    )


def _check_zip(content: bytes, what: str) -> None:
    if not zipfile.is_zipfile(io.BytesIO(content)):
        raise SourceUnavailableError(f"{what}: the download is not an archive")
