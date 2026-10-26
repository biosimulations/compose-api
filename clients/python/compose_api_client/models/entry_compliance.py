from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.compliance_case import ComplianceCase


T = TypeVar("T", bound="EntryCompliance")


@_attrs_define
class EntryCompliance:
    """An entry's standing in a version: `tested` when its cases all passed there, `pending` while any runs,
    `failed` when one did not pass, `untested` when it has no cases yet.

        Attributes:
            entry (str):
            level (str):
            cases (list[ComplianceCase] | Unset):
    """

    entry: str
    level: str
    cases: list[ComplianceCase] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        entry = self.entry

        level = self.level

        cases: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.cases, Unset):
            cases = []
            for cases_item_data in self.cases:
                cases_item = cases_item_data.to_dict()
                cases.append(cases_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "entry": entry,
            "level": level,
        })
        if cases is not UNSET:
            field_dict["cases"] = cases

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.compliance_case import ComplianceCase  # noqa: PLC0415

        d = dict(src_dict)
        entry = d.pop("entry")

        level = d.pop("level")

        _cases = d.pop("cases", UNSET)
        cases: list[ComplianceCase] | Unset = UNSET
        if _cases is not UNSET:
            cases = []
            for cases_item_data in _cases:
                cases_item = ComplianceCase.from_dict(cases_item_data)

                cases.append(cases_item)

        entry_compliance = cls(
            entry=entry,
            level=level,
            cases=cases,
        )

        entry_compliance.additional_properties = d
        return entry_compliance

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
