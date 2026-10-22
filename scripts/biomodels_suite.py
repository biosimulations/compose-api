"""Write a suite of the first N curated BioModels entries (docs/plan-sedml.md, phase 6; docs/plan-durable-submission.md).

    uv run python scripts/biomodels_suite.py --count 300 --name biomodels-curated-300

Walks BIOMD0000000001 upward and keeps every entry BioModels has that is manually curated and in SBML, until it has
``--count``. Every one goes in: an entry that does not translate, or that a solver cannot run, shows up as a failure of
the suite's first run, which is the point at this scale. Known disagreements become `expected` entries afterwards,
as they did for biomodels-ode-sample.
"""

import argparse
import asyncio
import datetime
from pathlib import Path

from compose_api.sedml import sources

HEADER = """# A regression and reproducibility suite (docs/plan-sedml.md, phase 6): the first {count} curated SBML models in EBI
# BioModels (BIOMD0000000001 upward), each run on every solver and compared. Generated on {date} by
# scripts/biomodels_suite.py; regenerate rather than edit the sources. Every curated SBML entry is included, whether or
# not it translates: the first run's failures are its findings, and known disagreements become `expected` entries.
# Its runs are queued behind interactive ones, at most half of submission_max_active_jobs at a time
# (docs/plan-durable-submission.md, Q3).
name: {name}
description: The first {count} curated SBML models in EBI BioModels, each run on COPASI and Tellurium and compared.
solvers: [copasi, tellurium]
tolerances: {{rel_tol: 1.0e-4, abs_tol_min: 1.0e-3, abs_tol_scale: 1.0e-5}}
expected: []
sources:
"""


async def curated(model_number: int, gate: asyncio.Semaphore) -> sources.BiomodelInfo | None:
    model_id = f"BIOMD{model_number:010d}"
    async with gate:
        try:
            info = await sources.biomodel(model_id)
        except sources.SourceNotFoundError:
            return None
    is_curated = (info.curation or "").upper() in ("CURATED", "MANUALLY CURATED")
    is_sbml = "SBML" in (info.format or "").upper()
    return info if is_curated and is_sbml else None


async def main(count: int, name: str, start: int) -> None:
    gate = asyncio.Semaphore(8)  # polite to EBI
    found: list[sources.BiomodelInfo] = []
    number = start
    while len(found) < count:
        batch = await asyncio.gather(*(curated(n, gate) for n in range(number, number + 50)))
        found += [info for info in batch if info is not None]
        number += 50
    found = found[:count]
    lines = [f"  - biomodels:{info.id}  # {info.name.replace('#', '')[:90]}" for info in found]
    path = Path("examples") / name / "suite.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    header = HEADER.format(count=count, name=name, date=datetime.date.today().isoformat())
    path.write_text(header + "\n".join(lines) + "\n")
    print(f"{path}: {len(found)} models, {found[0].id} to {found[-1].id} (checked up to BIOMD{number - 1:010d})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--count", type=int, default=300)
    parser.add_argument("--name", default="biomodels-curated-300")
    parser.add_argument("--start", type=int, default=1)
    args = parser.parse_args()
    asyncio.run(main(args.count, args.name, args.start))
