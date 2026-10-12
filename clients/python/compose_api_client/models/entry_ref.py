from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.curation_level import CurationLevel

T = TypeVar("T", bound="EntryRef")


@_attrs_define
class EntryRef:
    """The registry entry a component belongs to (by module root), and its curation level.

    Attributes:
        id (str):
        level (CurationLevel): The curation ladder, lowest first. Order matters: comparisons use the declaration order.
    """

    id: str
    level: CurationLevel
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = self.id

        level = self.level.value

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "id": id,
            "level": level,
        })

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = d.pop("id")

        level = CurationLevel(d.pop("level"))

        entry_ref = cls(
            id=id,
            level=level,
        )

        entry_ref.additional_properties = d
        return entry_ref

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
