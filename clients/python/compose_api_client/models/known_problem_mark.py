from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="KnownProblemMark")


@_attrs_define
class KnownProblemMark:
    """A known problem to record: the source and solver (none for the whole source), and why.

    Attributes:
        source (str):
        category (str):
        reason (str):
        solver (None | str | Unset):
        seen_run (int | None | Unset): the suite run it was first seen in
    """

    source: str
    category: str
    reason: str
    solver: None | str | Unset = UNSET
    seen_run: int | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        source = self.source

        category = self.category

        reason = self.reason

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

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "source": source,
            "category": category,
            "reason": reason,
        })
        if solver is not UNSET:
            field_dict["solver"] = solver
        if seen_run is not UNSET:
            field_dict["seen_run"] = seen_run

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        source = d.pop("source")

        category = d.pop("category")

        reason = d.pop("reason")

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

        known_problem_mark = cls(
            source=source,
            category=category,
            reason=reason,
            solver=solver,
            seen_run=seen_run,
        )

        known_problem_mark.additional_properties = d
        return known_problem_mark

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
