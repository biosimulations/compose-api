from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="Tolerances")


@_attrs_define
class Tolerances:
    """The platform's closeness score: close when `max |a-b| / (atol + rtol*|b|) < 1`, with
    `atol = max(abs_tol_min, max|a|*abs_tol_scale, max|b|*abs_tol_scale)` (docs/plan-sedml.md, D4).

        Attributes:
            rel_tol (float | Unset):  Default: 0.0001.
            abs_tol_min (float | Unset):  Default: 0.001.
            abs_tol_scale (float | Unset):  Default: 1e-05.
    """

    rel_tol: float | Unset = 0.0001
    abs_tol_min: float | Unset = 0.001
    abs_tol_scale: float | Unset = 1e-05
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        rel_tol = self.rel_tol

        abs_tol_min = self.abs_tol_min

        abs_tol_scale = self.abs_tol_scale

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if rel_tol is not UNSET:
            field_dict["rel_tol"] = rel_tol
        if abs_tol_min is not UNSET:
            field_dict["abs_tol_min"] = abs_tol_min
        if abs_tol_scale is not UNSET:
            field_dict["abs_tol_scale"] = abs_tol_scale

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        rel_tol = d.pop("rel_tol", UNSET)

        abs_tol_min = d.pop("abs_tol_min", UNSET)

        abs_tol_scale = d.pop("abs_tol_scale", UNSET)

        tolerances = cls(
            rel_tol=rel_tol,
            abs_tol_min=abs_tol_min,
            abs_tol_scale=abs_tol_scale,
        )

        tolerances.additional_properties = d
        return tolerances

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
