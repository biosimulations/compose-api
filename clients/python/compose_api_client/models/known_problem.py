from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="KnownProblem")


@_attrs_define
class KnownProblem:
    """A known problem of one solver on one source of a suite (docs/plan-known-problems.md): excused in the suite's
    runs numbered below `cleared_run` (every run while it is open). No solver: the whole source is excused.

        Attributes:
            problem_id (int):
            suite (str):
            source (str):
            category (str): what kind of problem, e.g. VCell's fault names (NONINTEGER_STOICH, DELAY)
            reason (str):
            marked_by (str):
            solver (None | str | Unset):
            seen_run (int | None | Unset): the suite run it was first seen in
            marked_at (None | str | Unset):
            cleared_run (int | None | Unset): the suite run that showed it fixed
            cleared_by (None | str | Unset):
            cleared_at (None | str | Unset):
    """

    problem_id: int
    suite: str
    source: str
    category: str
    reason: str
    marked_by: str
    solver: None | str | Unset = UNSET
    seen_run: int | None | Unset = UNSET
    marked_at: None | str | Unset = UNSET
    cleared_run: int | None | Unset = UNSET
    cleared_by: None | str | Unset = UNSET
    cleared_at: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        problem_id = self.problem_id

        suite = self.suite

        source = self.source

        category = self.category

        reason = self.reason

        marked_by = self.marked_by

        solver: None | str | Unset
        if isinstance(self.solver, Unset):
            solver = UNSET
        else:
            solver = self.solver

        seen_run: int | None | Unset
        if isinstance(self.seen_run, Unset):
            seen_run = UNSET
        else:
            seen_run = self.seen_run

        marked_at: None | str | Unset
        if isinstance(self.marked_at, Unset):
            marked_at = UNSET
        else:
            marked_at = self.marked_at

        cleared_run: int | None | Unset
        if isinstance(self.cleared_run, Unset):
            cleared_run = UNSET
        else:
            cleared_run = self.cleared_run

        cleared_by: None | str | Unset
        if isinstance(self.cleared_by, Unset):
            cleared_by = UNSET
        else:
            cleared_by = self.cleared_by

        cleared_at: None | str | Unset
        if isinstance(self.cleared_at, Unset):
            cleared_at = UNSET
        else:
            cleared_at = self.cleared_at

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "problem_id": problem_id,
            "suite": suite,
            "source": source,
            "category": category,
            "reason": reason,
            "marked_by": marked_by,
        })
        if solver is not UNSET:
            field_dict["solver"] = solver
        if seen_run is not UNSET:
            field_dict["seen_run"] = seen_run
        if marked_at is not UNSET:
            field_dict["marked_at"] = marked_at
        if cleared_run is not UNSET:
            field_dict["cleared_run"] = cleared_run
        if cleared_by is not UNSET:
            field_dict["cleared_by"] = cleared_by
        if cleared_at is not UNSET:
            field_dict["cleared_at"] = cleared_at

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        problem_id = d.pop("problem_id")

        suite = d.pop("suite")

        source = d.pop("source")

        category = d.pop("category")

        reason = d.pop("reason")

        marked_by = d.pop("marked_by")

        def _parse_solver(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        solver = _parse_solver(d.pop("solver", UNSET))

        def _parse_seen_run(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        seen_run = _parse_seen_run(d.pop("seen_run", UNSET))

        def _parse_marked_at(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        marked_at = _parse_marked_at(d.pop("marked_at", UNSET))

        def _parse_cleared_run(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        cleared_run = _parse_cleared_run(d.pop("cleared_run", UNSET))

        def _parse_cleared_by(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        cleared_by = _parse_cleared_by(d.pop("cleared_by", UNSET))

        def _parse_cleared_at(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        cleared_at = _parse_cleared_at(d.pop("cleared_at", UNSET))

        known_problem = cls(
            problem_id=problem_id,
            suite=suite,
            source=source,
            category=category,
            reason=reason,
            marked_by=marked_by,
            solver=solver,
            seen_run=seen_run,
            marked_at=marked_at,
            cleared_run=cleared_run,
            cleared_by=cleared_by,
            cleared_at=cleared_at,
        )

        known_problem.additional_properties = d
        return known_problem

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
