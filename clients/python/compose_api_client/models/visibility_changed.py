from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.visibility import Visibility

T = TypeVar("T", bound="VisibilityChanged")


@_attrs_define
class VisibilityChanged:
    """What a visibility change changed: the run, and the other runs of every comparison it belongs to, which change
    with it so a comparison is never half private.

        Attributes:
            visibility (Visibility): Who may read a simulation and everything it produced (plan-observability O7).
            simulation_ids (list[int]):
    """

    visibility: Visibility
    simulation_ids: list[int]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        visibility = self.visibility.value

        simulation_ids = self.simulation_ids

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "visibility": visibility,
            "simulation_ids": simulation_ids,
        })

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        visibility = Visibility(d.pop("visibility"))

        simulation_ids = cast(list[int], d.pop("simulation_ids"))

        visibility_changed = cls(
            visibility=visibility,
            simulation_ids=simulation_ids,
        )

        visibility_changed.additional_properties = d
        return visibility_changed

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
