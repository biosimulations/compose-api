"""Favorites: a signed-in user's private stars on simulations, comparisons and suite runs
(docs/plan-favorites-and-studies.md, F5, step 2).

A favorite names what it marks by kind and reference: a simulation or a comparison by its id, a suite run as
``<suite>@<number>``. Starring needs read access; a star on something that later becomes unreadable is kept but not
listed. Favorites are not tags: tags are given at submission, are public, and never change.
"""

import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class FavoriteKind(StrEnum):
    SIMULATION = "simulation"
    COMPARISON = "comparison"
    SUITE_RUN = "suite_run"


class Favorite(BaseModel):
    """One of the caller's stars."""

    kind: FavoriteKind
    ref: str = Field(description="A simulation's or a comparison's id; a suite run as `<suite>@<number>`")
    created_at: str | None = None  # ISO 8601 UTC


class FavoriteRemoval(BaseModel):
    """What unstarring did."""

    kind: FavoriteKind
    ref: str
    removed: bool = Field(description="It was starred, and is not now")


class FavoriteRefError(ValueError):
    """A reference that cannot name anything of its kind."""


def normalize_ref(kind: FavoriteKind, ref: str) -> str:
    """``ref`` in its one stored form (``"0012"`` is ``"12"``), so a star is found however it was written."""
    if kind is FavoriteKind.SUITE_RUN:
        name, at, number = ref.strip().rpartition("@")
        if not at or not name or not number.isdigit():
            raise FavoriteRefError(f"{ref!r}: a suite run is <suite>@<number>, e.g. smoke@22")
        return f"{name}@{int(number)}"
    if not ref.strip().isdigit():
        raise FavoriteRefError(f"{ref!r}: a {kind.value} is named by its id, a number")
    return str(int(ref))


def suite_run_ref(ref: str) -> tuple[str, int]:
    """A normalized suite run reference as its suite and number."""
    name, _, number = ref.rpartition("@")
    return name, int(number)


def iso(value: datetime.datetime) -> str:
    aware = value if value.tzinfo else value.replace(tzinfo=datetime.UTC)
    return aware.astimezone(datetime.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
