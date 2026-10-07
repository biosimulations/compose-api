from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.dataset import Dataset


T = TypeVar("T", bound="DatasetPage")


@_attrs_define
class DatasetPage:
    """
    Attributes:
        datasets (list[Dataset]):
        total (int):
        next_offset (int | None | Unset):
    """

    datasets: list[Dataset]
    total: int
    next_offset: int | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        datasets = []
        for datasets_item_data in self.datasets:
            datasets_item = datasets_item_data.to_dict()
            datasets.append(datasets_item)

        total = self.total

        next_offset: int | None | Unset
        if isinstance(self.next_offset, Unset):
            next_offset = UNSET
        else:
            next_offset = self.next_offset

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "datasets": datasets,
            "total": total,
        })
        if next_offset is not UNSET:
            field_dict["next_offset"] = next_offset

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.dataset import Dataset  # noqa: PLC0415

        d = dict(src_dict)
        datasets = []
        _datasets = d.pop("datasets")
        for datasets_item_data in _datasets:
            datasets_item = Dataset.from_dict(datasets_item_data)

            datasets.append(datasets_item)

        total = d.pop("total")

        def _parse_next_offset(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        next_offset = _parse_next_offset(d.pop("next_offset", UNSET))

        dataset_page = cls(
            datasets=datasets,
            total=total,
            next_offset=next_offset,
        )

        dataset_page.additional_properties = d
        return dataset_page

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
