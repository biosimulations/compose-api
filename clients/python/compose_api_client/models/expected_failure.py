from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="ExpectedFailure")


@_attrs_define
class ExpectedFailure:
    """
    Attributes:
        source (str):
        reason (str):
        solver (None | str | Unset):
    """

    source: str
    reason: str
    solver: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        source = self.source

        reason = self.reason

        solver: None | str | Unset
        if isinstance(self.solver, Unset):
            solver = UNSET
        else:
            solver = self.solver

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "source": source,
            "reason": reason,
        })
        if solver is not UNSET:
            field_dict["solver"] = solver

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        source = d.pop("source")

        reason = d.pop("reason")

        def _parse_solver(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        solver = _parse_solver(d.pop("solver", UNSET))

        expected_failure = cls(
            source=source,
            reason=reason,
            solver=solver,
        )

        expected_failure.additional_properties = d
        return expected_failure

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
