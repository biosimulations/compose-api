"""Who may read a simulation, and everything it produced (docs/plan-observability.md O7, O8).

Every route that reads something a simulation owns (its status, results, events, trace and datasets) resolves the
simulation through :func:`readable_simulation` or :func:`readable_simulation_ids`. That keeps the permission check in
one place, so adding auth changes only who the caller is (:func:`get_caller`), never which routes check.

- **Ownership lives on the simulation.** Runs, events and datasets inherit it through their foreign keys.
- **A simulation the caller may not read is reported as not found**, the same as one that does not exist, so its id
  reveals nothing.
- **Until auth lands every caller is anonymous and every simulation is public**, so behaviour is unchanged. When #192
  merges, :func:`get_caller` returns its verified principal, which already has the ``subject`` and ``roles`` that
  :class:`Caller` asks for.
"""

from typing import Annotated, Protocol

from fastapi import Depends, HTTPException, Query

from compose_api.dependencies import get_required_database_service
from compose_api.simulation.models import SimulationAccess, Visibility

ADMIN_ROLE = "admin"  # may read every simulation


class Caller(Protocol):
    """A verified caller: the identity provider's subject and the caller's roles."""

    @property
    def subject(self) -> str: ...

    @property
    def roles(self) -> frozenset[str]: ...


async def get_caller() -> Caller | None:
    """The caller, or None if anonymous. Always anonymous until auth (#192) is wired in here."""
    return None


OptionalCaller = Annotated[Caller | None, Depends(get_caller)]


def can_read(caller: Caller | None, simulation: SimulationAccess) -> bool:
    """The read policy: public simulations to anyone, private ones to their owner and to admins."""
    if simulation.visibility == Visibility.PUBLIC:
        return True
    if caller is None:
        return False
    return ADMIN_ROLE in caller.roles or (simulation.owner_sub is not None and caller.subject == simulation.owner_sub)


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
