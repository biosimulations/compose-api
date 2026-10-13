from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="Drift")


@_attrs_define
class Drift:
    """One solver's result against its own result in the suite's baseline run.

    Attributes:
        close (bool | None):
        worst_label (None | str | Unset):
        worst_score (float | None | str | Unset):
    """

    close: bool | None
    worst_label: None | str | Unset = UNSET
    worst_score: float | None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        close: bool | None
        close = self.close

        worst_label: None | str | Unset
        if isinstance(self.worst_label, Unset):
            worst_label = UNSET
        else:
            worst_label = self.worst_label

        worst_score: float | None | str | Unset
        if isinstance(self.worst_score, Unset):
            worst_score = UNSET
        else:
            worst_score = self.worst_score

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "close": close,
        })
        if worst_label is not UNSET:
            field_dict["worst_label"] = worst_label
        if worst_score is not UNSET:
            field_dict["worst_score"] = worst_score

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_close(data: object) -> bool | None:
            if data is None:
                return data
            return cast(bool | None, data)

        close = _parse_close(d.pop("close"))

        def _parse_worst_label(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        worst_label = _parse_worst_label(d.pop("worst_label", UNSET))

        def _parse_worst_score(data: object) -> float | None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | str | Unset, data)

        worst_score = _parse_worst_score(d.pop("worst_score", UNSET))

        drift = cls(
            close=close,
            worst_label=worst_label,
            worst_score=worst_score,
        )

        drift.additional_properties = d
        return drift

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
