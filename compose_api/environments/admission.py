"""Admission by what a version certifies (docs/plan-environment-composition.md, step 5c): the standing of the version a
run will use, which the submission check (``registry/validation.py``) consults before the manifest's own levels.

A component a generic check failed in that version is refused there on its own; an entry whose compliance cases failed
there is refused, one whose cases passed is accepted; an entry with no cases yet, or whose cases are still running,
keeps the manifest's level. A composed version runs only its own entries.
"""

from compose_api.db.database_service import DatabaseService
from compose_api.environments import compliance_runs, pixi
from compose_api.registry.validation import Standing
from compose_api.simulation.models import EnvironmentVersionDetail


async def standing_of(database_service: DatabaseService, version: EnvironmentVersionDetail) -> Standing:
    """The version's standing, as recorded (finished runs are evaluated when the compliance report is read)."""
    report = await compliance_runs.report(database_service, version)
    refused = {
        str(f["component"]): str(f.get("detail", f.get("check", "")))
        for f in (version.findings or [])
        if f.get("severity") == "fail"
    }
    composed = version.runtime_contract == pixi.RUNTIME_CONTRACT
    return Standing(
        label=version.label,
        members=frozenset(compliance_runs.member_entries(version)) if composed else None,
        levels={e.entry: e.level for e in report.entries},
        refused=refused,
    )


async def standing_for(database_service: DatabaseService, environment: str, number: int | None) -> Standing | None:
    """The standing of ``environment@number``, or of its default without a number; None when there is none yet (the
    manifest alone decides, as before versions)."""
    environments_db = database_service.get_environments_db()
    version = (
        await environments_db.get_by_number(environment, number)
        if number is not None
        else await environments_db.get_default_detail(environment)
    )
    return await standing_of(database_service, version) if version is not None else None
