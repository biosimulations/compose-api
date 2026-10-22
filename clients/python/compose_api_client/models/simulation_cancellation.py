from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="SimulationCancellation")


@_attrs_define
class SimulationCancellation:
    """A cancellation accepted. ``withdrawn``: the run was taken off the queue before SLURM had it, and is cancelled
    now. Otherwise SLURM was asked to cancel ``slurm_job_id``, and the run's status reads ``cancelled`` once the job
    monitor sees SLURM report it.

        Attributes:
            simulation_id (int):
            withdrawn (bool):
            slurm_job_id (int | None | Unset):
    """

    simulation_id: int
    withdrawn: bool
    slurm_job_id: int | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        simulation_id = self.simulation_id

        withdrawn = self.withdrawn

        slurm_job_id: int | None | Unset
        if isinstance(self.slurm_job_id, Unset):
            slurm_job_id = UNSET
        else:
            slurm_job_id = self.slurm_job_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "simulation_id": simulation_id,
            "withdrawn": withdrawn,
        })
        if slurm_job_id is not UNSET:
            field_dict["slurm_job_id"] = slurm_job_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        simulation_id = d.pop("simulation_id")

        withdrawn = d.pop("withdrawn")

        def _parse_slurm_job_id(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        slurm_job_id = _parse_slurm_job_id(d.pop("slurm_job_id", UNSET))

        simulation_cancellation = cls(
            simulation_id=simulation_id,
            withdrawn=withdrawn,
            slurm_job_id=slurm_job_id,
        )

        simulation_cancellation.additional_properties = d
        return simulation_cancellation

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
