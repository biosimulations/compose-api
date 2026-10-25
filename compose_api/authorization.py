"""Who may read a simulation, and everything it produced (docs/plan-observability.md O7, O8).

Every route that reads something a simulation owns (its status, results, events, trace and datasets) resolves the
simulation through :func:`readable_simulation` or :func:`readable_simulation_ids`. That keeps the permission check in
one place, so adding auth changes only who the caller is (:func:`get_caller`), never which routes check.

- **Ownership lives on the simulation.** Runs, events and datasets inherit it through their foreign keys.
- **A simulation the caller may not read is reported as not found**, the same as one that does not exist, so its id
  reveals nothing.
- **The caller is the verified bearer-token principal** (:mod:`compose_api.authentication`, #192), or None when the
  request is anonymous. Until submissions stamp an owner (plan-observability step 5) every simulation is public, so
  what a caller can read is unchanged.
"""

from typing import Annotated, Protocol

from fastapi import Depends, HTTPException, Query
from sqlalchemy import ColumnElement, or_

from compose_api.authentication import OptionalPrincipal
from compose_api.config import get_settings
from compose_api.db.tables.simulator_tables import ORMSimulation
from compose_api.dependencies import get_required_database_service
from compose_api.simulation.models import SimulationAccess, Visibility


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


def can_read(caller: Caller | None, simulation: SimulationAccess) -> bool:
    """The read policy: public simulations to anyone, private ones to their owner and to configured admins."""
    if simulation.visibility == Visibility.PUBLIC:
        return True
    if caller is None:
        return False
    return _is_admin(caller) or (simulation.owner_sub is not None and caller.subject == simulation.owner_sub)


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
