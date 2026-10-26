from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="ComplianceCase")


@_attrs_define
class ComplianceCase:
    """One compliance case of an entry, run in a version: `pending` until its run finishes, then `passed`, `failed`
    (an expectation not met) or `error` (the run did not finish).

        Attributes:
            case (str):
            state (str):
            simulation_id (int | None | Unset):
            failures (list[str] | Unset):
    """

    case: str
    state: str
    simulation_id: int | None | Unset = UNSET
    failures: list[str] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        case = self.case

        state = self.state

        simulation_id: int | None | Unset
        if isinstance(self.simulation_id, Unset):
            simulation_id = UNSET
        else:
            simulation_id = self.simulation_id

        failures: list[str] | Unset = UNSET
        if not isinstance(self.failures, Unset):
            failures = self.failures

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "case": case,
            "state": state,
        })
        if simulation_id is not UNSET:
            field_dict["simulation_id"] = simulation_id
        if failures is not UNSET:
            field_dict["failures"] = failures

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        case = d.pop("case")

        state = d.pop("state")

        def _parse_simulation_id(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        simulation_id = _parse_simulation_id(d.pop("simulation_id", UNSET))

        failures = cast(list[str], d.pop("failures", UNSET))

        compliance_case = cls(
            case=case,
            state=state,
            simulation_id=simulation_id,
            failures=failures,
        )

        compliance_case.additional_properties = d
        return compliance_case

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
