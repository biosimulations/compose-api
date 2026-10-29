"""Favorites: the signed-in caller's private stars on simulations, comparisons and suite runs
(docs/plan-favorites-and-studies.md, F5, step 2). ``GET /simulations?favorite=true`` and
``GET /comparisons?favorite=true`` list what is starred; each simulation and comparison says whether it is the caller's
favorite."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from compose_api.api.errors import error
from compose_api.authentication import get_optional_principal
from compose_api.authorization import Caller, OptionalCaller, readable_comparison, readable_simulation_ids
from compose_api.common.gateway.models import RouterConfig
from compose_api.dependencies import get_required_database_service
from compose_api.favorites import (
    Favorite,
    FavoriteKind,
    FavoriteRefError,
    FavoriteRemoval,
    normalize_ref,
    suite_run_ref,
)
from compose_api.sedml.suites import suite

config = RouterConfig(router=APIRouter(), prefix="/favorites", dependencies=[Depends(get_optional_principal)])

SIGN_IN = error("Favorites need a signed-in caller")
BAD_REF = error("The reference cannot name anything of its kind")


def signed_in(caller: Caller | None) -> Caller:
    """The caller, or a 401: favorites are a signed-in user's own."""
    if caller is None:
        raise HTTPException(
            status_code=401, detail="Favorites need a signed-in caller", headers={"WWW-Authenticate": "Bearer"}
        )
    return caller


async def starred_refs(caller: Caller | None, kind: FavoriteKind) -> set[str]:
    """The references of the caller's stars of one kind (none when anonymous), for the flags on listings."""
    if caller is None:
        return set()
    return await get_required_database_service().get_favorites_db().refs(caller.subject, kind)


def _ref(kind: FavoriteKind, ref: str) -> str:
    try:
        return normalize_ref(kind, ref)
    except FavoriteRefError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


async def _suite_run_numbers(name: str) -> set[int]:
    if suite(name) is None:
        return set()
    return {r.number for r in await get_required_database_service().get_comparisons_db().suite_runs(name)}


async def _readable(caller: Caller, kind: FavoriteKind, refs: list[str]) -> set[str]:
    """Those of ``refs`` (normalized, of one kind) that exist and the caller may read."""
    if kind is FavoriteKind.SIMULATION:
        return {str(i) for i in await readable_simulation_ids(caller, [int(r) for r in refs])}
    if kind is FavoriteKind.COMPARISON:
        return {r for r in refs if await readable_comparison(caller, int(r)) is not None}
    numbers: dict[str, set[int]] = {}
    found = set()
    for r in refs:
        name, number = suite_run_ref(r)
        if name not in numbers:
            numbers[name] = await _suite_run_numbers(name)
        if number in numbers[name]:
            found.add(r)
    return found


@config.router.put(
    path="/{kind}/{ref}",
    response_model=Favorite,
    operation_id="add-favorite",
    responses={400: BAD_REF, 401: SIGN_IN, 404: error("It does not exist, or the caller may not read it")},
    tags=["Favorites"],
    summary="Star a simulation, a comparison or a suite run (`<suite>@<number>`); starring it again changes nothing",
)
async def add_favorite(kind: FavoriteKind, ref: str, caller: OptionalCaller) -> Favorite:
    user = signed_in(caller)
    normalized = _ref(kind, ref)
    if not await _readable(user, kind, [normalized]):
        raise HTTPException(status_code=404, detail=f"No {kind.value} {ref} found.")
    return await get_required_database_service().get_favorites_db().add(user.subject, kind, normalized)


@config.router.delete(
    path="/{kind}/{ref}",
    response_model=FavoriteRemoval,
    operation_id="remove-favorite",
    responses={400: BAD_REF, 401: SIGN_IN},
    tags=["Favorites"],
    summary="Unstar it; unstarring what is not starred changes nothing",
)
async def remove_favorite(kind: FavoriteKind, ref: str, caller: OptionalCaller) -> FavoriteRemoval:
    user = signed_in(caller)
    normalized = _ref(kind, ref)
    removed = await get_required_database_service().get_favorites_db().remove(user.subject, kind, normalized)
    return FavoriteRemoval(kind=kind, ref=normalized, removed=removed)


@config.router.get(
    path="",
    response_model=list[Favorite],
    operation_id="list-favorites",
    responses={401: SIGN_IN},
    tags=["Favorites"],
    summary="The caller's stars, newest first; a star on something the caller can no longer read is not listed",
)
async def list_favorites(
    caller: OptionalCaller,
    kind: Annotated[FavoriteKind | None, Query(description="Only stars of this kind")] = None,
) -> list[Favorite]:
    user = signed_in(caller)
    stars = await get_required_database_service().get_favorites_db().list_favorites(user.subject, kind)
    readable: set[tuple[FavoriteKind, str]] = set()
    for each in FavoriteKind:
        refs = [f.ref for f in stars if f.kind is each]
        if refs:
            readable |= {(each, r) for r in await _readable(user, each, refs)}
    return [f for f in stars if (f.kind, f.ref) in readable]
