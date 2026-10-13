"""SED-ML translation by process-bigraph-lang's CLI (`sedml translate`), run in its own environment
(`settings.pblang_python`; it needs a newer bigraph-schema than this service's). Its contract is files: one template
per task, one archive per accepted task and solver, `findings.json`."""

import asyncio
import json
import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from compose_api.config import get_settings
from compose_api.registry.environments import manifest_path
from compose_api.registry.solvers import Solver
from compose_api.sedml.models import SedmlFinding

logger = logging.getLogger(__name__)


class TranslatorUnavailableError(RuntimeError):
    """process-bigraph-lang's environment is missing (settings.pblang_python)."""


@dataclass
class TranslatedTask:
    sedml: str
    task: str
    name: str
    template: str
    archives: dict[str, Path] = field(default_factory=dict)  # solver -> the archive a run takes
    reports: dict[str, dict[str, object]] = field(default_factory=dict)  # report id -> {file, labels}


@dataclass
class Translation:
    source: str
    tasks: list[TranslatedTask]
    findings: list[SedmlFinding]
    workdir: Path


def pblang_python() -> Path:
    python = Path(get_settings().pblang_python)
    if not python.exists():
        raise TranslatorUnavailableError(f"process-bigraph-lang is not installed at {python} (settings.pblang_python)")
    return python


async def _run(*args: str) -> tuple[int, str]:
    process = await asyncio.create_subprocess_exec(
        str(pblang_python()), "-m", "process_bigraph_lang.v2", *args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )  # fmt: skip
    out, _ = await process.communicate()
    return process.returncode or 0, out.decode(errors="replace")


async def describe(source: Path) -> dict[str, Any]:
    """What the archive's SED-ML asks for (`pblang-sedml/0`)."""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "description.json"
        code, output = await _run("sedml", "describe", str(source), "-o", str(target))
        if code != 0 or not target.exists():
            raise ValueError(f"not a SED-ML archive process-bigraph-lang can read: {output.strip()[-2000:]}")
        description: dict[str, Any] = json.loads(target.read_text())
        return description


async def translate(source: Path, solvers: list[Solver], workdir: Path) -> Translation:
    """Every task of the archive, compiled per solver against its environment's manifest, into `workdir`."""
    description = await describe(source)
    solvers_file = workdir / "solvers.yaml"
    solvers_file.write_text(yaml.safe_dump({"solvers": [s.as_translation_data() for s in solvers]}))
    out = workdir / "translated"
    manifests = sorted({str(manifest_path(s.environment)) for s in solvers})
    args = ["sedml", "translate", str(source), "--solvers", str(solvers_file), "-o", str(out)]
    args += ["--output-dir", get_settings().containers_output_dir, "--addresses", "registered"]
    for m in manifests:
        args += ["-i", m]
    _code, output = await _run(*args)  # exit 1 when some task or solver was refused: the findings say which
    findings_file = out / "findings.json"
    if not findings_file.exists():
        raise ValueError(f"the translation failed: {output.strip()[-2000:]}")
    findings = [SedmlFinding.model_validate(f) for f in json.loads(findings_file.read_text())]
    tasks: list[TranslatedTask] = []
    for sed in description.get("files", []):
        for task in sed["tasks"]:
            name = _identifier(task["id"])
            template = out / f"{name}.pblang"
            if not template.exists():
                continue
            translated = TranslatedTask(sedml=sed["path"], task=task["id"], name=name, template=template.read_text())
            translated.archives = {
                s.id: out / f"{name}.{s.id}.omex" for s in solvers if (out / f"{name}.{s.id}.omex").exists()
            }
            translated.reports = _reports(sed, task["id"])
            tasks.append(translated)
    return Translation(source=source.name, tasks=tasks, findings=findings, workdir=workdir)


def _reports(sed: dict[str, Any], task_id: str) -> dict[str, dict[str, object]]:
    """Each report of the task: where its CSV is (as the translation names it) and its labels."""
    generators = {g["id"]: {v["task"] for v in g["variables"]} for g in sed["data_generators"]}
    stem = _identifier(Path(str(sed["path"])).stem)
    reports: dict[str, dict[str, object]] = {}
    for r in sed["reports"]:
        if all(generators.get(d["data_generator"]) == {task_id} for d in r["data_sets"]):
            reports[r["id"]] = {
                "file": f"output/reports/{stem}/{_identifier(r['id'])}.csv",
                "labels": [d["label"] for d in r["data_sets"]],
            }
    return reports


def _identifier(text: str) -> str:
    import re

    name = re.sub(r"\W", "_", text)
    return name if re.match(r"^[A-Za-z_]", name) else f"_{name}"
