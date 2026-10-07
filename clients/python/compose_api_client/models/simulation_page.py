from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.simulation_summary import SimulationSummary


T = TypeVar("T", bound="SimulationPage")


@_attrs_define
class SimulationPage:
    """
    Attributes:
        simulations (list[SimulationSummary]):
        total (int):
        next_offset (int | None | Unset):
    """

    simulations: list[SimulationSummary]
    total: int
    next_offset: int | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        simulations = []
        for simulations_item_data in self.simulations:
            simulations_item = simulations_item_data.to_dict()
            simulations.append(simulations_item)

        total = self.total

        next_offset: int | None | Unset
        if isinstance(self.next_offset, Unset):
            next_offset = UNSET
        else:
            next_offset = self.next_offset

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "simulations": simulations,
            "total": total,
        })
        if next_offset is not UNSET:
            field_dict["next_offset"] = next_offset

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.simulation_summary import SimulationSummary  # noqa: PLC0415

        d = dict(src_dict)
        simulations = []
        _simulations = d.pop("simulations")
        for simulations_item_data in _simulations:
            simulations_item = SimulationSummary.from_dict(simulations_item_data)

            simulations.append(simulations_item)

        total = d.pop("total")

        def _parse_next_offset(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        next_offset = _parse_next_offset(d.pop("next_offset", UNSET))

        simulation_page = cls(
            simulations=simulations,
            total=total,
            next_offset=next_offset,
        )

        simulation_page.additional_properties = d
        return simulation_page

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
