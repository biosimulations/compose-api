"""Who may read a simulation, and everything it produced (docs/plan-observability.md O7, O8).

Every route that reads something a simulation owns (its status, results, events, trace and datasets) resolves the
simulation through :func:`readable_simulation` or :func:`readable_simulation_ids`. That keeps the permission check in
one place, so adding auth changes only who the caller is (:func:`get_caller`), never which routes check.

- **Ownership lives on the simulation.** Runs, events and datasets inherit it through their foreign keys.
- **A simulation the caller may not read is reported as not found**, the same as one that does not exist, so its id
  reveals nothing.
- **The caller is the verified bearer-token principal** (:mod:`compose_api.authentication`, #192), or None when the
  request is anonymous.
- **A signed-in submitter owns the run, and it is private unless they ask for public**
  (docs/plan-favorites-and-studies.md, F1, F3; :func:`ownership_at_submit`). Anonymous runs, and runs the service
  starts (suites, compliance), have no owner and are public.
"""

from typing import Annotated, Protocol

from fastapi import Depends, HTTPException, Query
from sqlalchemy import ColumnElement, or_

from compose_api.authentication import OptionalPrincipal
from compose_api.config import get_settings
from compose_api.db.services.comparisons_db import ComparisonRow
from compose_api.db.tables.simulator_tables import ORMSimulation
from compose_api.dependencies import get_required_database_service
from compose_api.simulation.models import Ownership, SimulationAccess, Visibility


class Caller(Protocol):
    """A verified caller: the identity provider's subject and the caller's roles."""

    @property
    def subject(self) -> str: ...

    @property
    def roles(self) -> frozenset[str]: ...


async def get_caller(principal: OptionalPrincipal) -> Caller | None:
    """The verified caller, or None if anonymous. A bearer token that is present but invalid never gets here:
    get_optional_principal has already answered it with 401."""
    return principal


OptionalCaller = Annotated[Caller | None, Depends(get_caller)]


def _is_admin(caller: Caller | None) -> bool:
    if caller is None:
        return False
    configured = get_settings().admin_role.strip()
    return bool(configured) and configured in caller.roles


def is_environment_admin(caller: Caller | None) -> bool:
    """Whether the caller may create and change environment versions (docs/plan-environment-versions.md)."""
    if caller is None:
        return False
    configured = get_settings().environment_admin_role.strip()
    return bool(configured) and configured in caller.roles


async def require_environment_admin(caller: OptionalCaller) -> Caller:
    """The caller, if an environment administrator: otherwise 401 when anonymous, 403 when signed in."""
    if caller is None:
        raise HTTPException(status_code=401, detail="sign in as an environment administrator")
    if not get_settings().environment_admin_role.strip():
        raise HTTPException(status_code=403, detail="environment administration is not configured on this service")
    if not is_environment_admin(caller):
        raise HTTPException(status_code=403, detail="this needs the environment administrator role")
    return caller


EnvironmentAdmin = Annotated[Caller, Depends(require_environment_admin)]


def is_suite_curator(caller: Caller | None) -> bool:
    """Whether the caller may mark, edit and clear a suite's known problems (docs/plan-known-problems.md, K6)."""
    if caller is None:
        return False
    configured = get_settings().suite_curator_role.strip()
    return bool(configured) and configured in caller.roles


async def require_suite_curator(caller: OptionalCaller) -> Caller:
    """The caller, if a suite curator: otherwise 401 when anonymous, 403 when signed in."""
    if caller is None:
        raise HTTPException(status_code=401, detail="sign in as a suite curator")
    if not get_settings().suite_curator_role.strip():
        raise HTTPException(status_code=403, detail="suite curation is not configured on this service")
    if not is_suite_curator(caller):
        raise HTTPException(status_code=403, detail="this needs the suite curator role")
    return caller


SuiteCurator = Annotated[Caller, Depends(require_suite_curator)]


#: what a caller may do, by name, as ``GET /auth/me`` reports it (docs/plan-webapp-admin.md, A1); each is the check
#: that enforces it, so the two cannot disagree
CAPABILITIES = {
    "environments:admin": is_environment_admin,
    "suites:curate": is_suite_curator,
    "simulations:read-all": _is_admin,
}


def capabilities(caller: Caller | None) -> list[str]:
    """The names of what the caller may do beyond what anyone may (A1). The webapp only displays them; every request
    is still checked."""
    return sorted(name for name, check in CAPABILITIES.items() if check(caller))


def can_read(caller: Caller | None, simulation: SimulationAccess) -> bool:
    """The read policy: public simulations to anyone, private ones to their owner and to configured admins."""
    if simulation.visibility == Visibility.PUBLIC:
        return True
    if caller is None:
        return False
    return _is_admin(caller) or (simulation.owner_sub is not None and caller.subject == simulation.owner_sub)


def can_cancel(caller: Caller, simulation: SimulationAccess) -> bool:
    """Who may cancel a run they can read: its owner or a configured admin; anyone signed in, for a run with no owner
    (anonymous, from before owners were stamped, or started by the service) (docs/plan-favorites-and-studies.md, F4)."""
    return simulation.owner_sub is None or _is_admin(caller) or caller.subject == simulation.owner_sub


#: a submission's `visibility` parameter (docs/plan-favorites-and-studies.md, F3)
RequestedVisibility = Annotated[
    Visibility | None,
    Query(
        description="Who may read the run: `private` (the default when signed in: you, and admins) or `public`"
        " (anyone). Anonymous runs are public; asking for private needs signing in. The owner can change it later"
        " (PATCH /simulations/{id})"
    ),
]


def ownership_at_submit(caller: Caller | None, requested: Visibility | None) -> Ownership | None:
    """A new run's owner and visibility (docs/plan-favorites-and-studies.md, F1, F3): a signed-in submitter owns it,
    private unless they ask for public; an anonymous run has no owner and is public, so asking for private needs
    signing in (a run with no owner that nobody may read helps nobody)."""
    if caller is None:
        if requested is Visibility.PRIVATE:
            raise HTTPException(
                status_code=400,
                detail="A private run needs a signed-in submitter: sign in, or submit it public",
            )
        return None
    return Ownership(owner_sub=caller.subject, visibility=requested or Visibility.PRIVATE)


def can_change_visibility(caller: Caller, simulation: SimulationAccess) -> bool:
    """Who may make a run public or private: its owner or a configured admin. A run with no owner stays public: made
    private, nobody but an admin could read it."""
    return simulation.owner_sub is not None and (_is_admin(caller) or caller.subject == simulation.owner_sub)


def readable_clause(caller: Caller | None) -> ColumnElement[bool] | None:
    """:func:`can_read` as a SQL condition on ``simulation``, for listings; None when every simulation is readable."""
    if _is_admin(caller):
        return None
    public = ORMSimulation.visibility == Visibility.PUBLIC.value
    return public if caller is None else or_(public, ORMSimulation.owner_sub == caller.subject)


async def readable_simulation(caller: OptionalCaller, simulation_id: int = Query(...)) -> SimulationAccess:
    """The simulation named by the ``simulation_id`` query parameter, if the caller may read it; otherwise 404."""
    found = await get_required_database_service().get_simulator_db().get_simulations_access([simulation_id])
    if not found or not can_read(caller, found[0]):
        raise HTTPException(status_code=404, detail=f"Simulation with id {simulation_id} not found.")
    return found[0]


async def readable_simulation_ids(caller: Caller | None, simulation_ids: list[int]) -> list[int]:
    """The ids, among ``simulation_ids``, of simulations that exist and the caller may read."""
    found = await get_required_database_service().get_simulator_db().get_simulations_access(simulation_ids)
    readable = {s.simulation_id for s in found if can_read(caller, s)}
    return [i for i in simulation_ids if i in readable]


async def readable_comparison(caller: Caller | None, comparison_id: int) -> ComparisonRow | None:
    """The comparison, if it exists and the caller may read every run in it. A comparison shows its members'
    results, so one the caller may not read is reported as not found."""
    row = await get_required_database_service().get_comparisons_db().get(comparison_id)
    if row is None:
        return None
    ids = [m.simulation_id for m in row.members]
    return row if len(await readable_simulation_ids(caller, ids)) == len(ids) else None
