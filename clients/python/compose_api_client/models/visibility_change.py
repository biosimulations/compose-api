from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.visibility import Visibility

T = TypeVar("T", bound="VisibilityChange")


@_attrs_define
class VisibilityChange:
    """``PATCH /simulations/{id}``'s body: who may read the run.

    Attributes:
        visibility (Visibility): Who may read a simulation and everything it produced (plan-observability O7).
    """

    visibility: Visibility
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        visibility = self.visibility.value

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "visibility": visibility,
        })

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        visibility = Visibility(d.pop("visibility"))

        visibility_change = cls(
            visibility=visibility,
        )

        visibility_change.additional_properties = d
        return visibility_change

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
