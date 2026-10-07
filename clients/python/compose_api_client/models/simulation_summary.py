from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.visibility import Visibility
from ..types import UNSET, Unset

T = TypeVar("T", bound="SimulationSummary")


@_attrs_define
class SimulationSummary:
    """One simulation as a listing shows it: what ran, where, and how it went (its latest SLURM job).

    Attributes:
        simulation_id (int):
        experiment_id (str):
        simulator_id (int):
        container_def_hash (str):
        status (str):
        created_at (None | str | Unset):
        simulator (None | str | Unset):
        visibility (Visibility | Unset): Who may read a simulation and everything it produced (plan-observability O7).
        slurm_job_id (int | None | Unset):
        start_time (None | str | Unset):
        end_time (None | str | Unset):
        exit_code (int | None | Unset):
        error_message (None | str | Unset):
        trace_id (None | str | Unset):
    """

    simulation_id: int
    experiment_id: str
    simulator_id: int
    container_def_hash: str
    status: str
    created_at: None | str | Unset = UNSET
    simulator: None | str | Unset = UNSET
    visibility: Visibility | Unset = UNSET
    slurm_job_id: int | None | Unset = UNSET
    start_time: None | str | Unset = UNSET
    end_time: None | str | Unset = UNSET
    exit_code: int | None | Unset = UNSET
    error_message: None | str | Unset = UNSET
    trace_id: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        simulation_id = self.simulation_id

        experiment_id = self.experiment_id

        simulator_id = self.simulator_id

        container_def_hash = self.container_def_hash

        status = self.status

        created_at: None | str | Unset
        if isinstance(self.created_at, Unset):
            created_at = UNSET
        else:
            created_at = self.created_at

        simulator: None | str | Unset
        if isinstance(self.simulator, Unset):
            simulator = UNSET
        else:
            simulator = self.simulator

        visibility: str | Unset = UNSET
        if not isinstance(self.visibility, Unset):
            visibility = self.visibility.value

        slurm_job_id: int | None | Unset
        if isinstance(self.slurm_job_id, Unset):
            slurm_job_id = UNSET
        else:
            slurm_job_id = self.slurm_job_id

        start_time: None | str | Unset
        if isinstance(self.start_time, Unset):
            start_time = UNSET
        else:
            start_time = self.start_time

        end_time: None | str | Unset
        if isinstance(self.end_time, Unset):
            end_time = UNSET
        else:
            end_time = self.end_time

        exit_code: int | None | Unset
        if isinstance(self.exit_code, Unset):
            exit_code = UNSET
        else:
            exit_code = self.exit_code

        error_message: None | str | Unset
        if isinstance(self.error_message, Unset):
            error_message = UNSET
        else:
            error_message = self.error_message

        trace_id: None | str | Unset
        if isinstance(self.trace_id, Unset):
            trace_id = UNSET
        else:
            trace_id = self.trace_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "simulation_id": simulation_id,
            "experiment_id": experiment_id,
            "simulator_id": simulator_id,
            "container_def_hash": container_def_hash,
            "status": status,
        })
        if created_at is not UNSET:
            field_dict["created_at"] = created_at
        if simulator is not UNSET:
            field_dict["simulator"] = simulator
        if visibility is not UNSET:
            field_dict["visibility"] = visibility
        if slurm_job_id is not UNSET:
            field_dict["slurm_job_id"] = slurm_job_id
        if start_time is not UNSET:
            field_dict["start_time"] = start_time
        if end_time is not UNSET:
            field_dict["end_time"] = end_time
        if exit_code is not UNSET:
            field_dict["exit_code"] = exit_code
        if error_message is not UNSET:
            field_dict["error_message"] = error_message
        if trace_id is not UNSET:
            field_dict["trace_id"] = trace_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        simulation_id = d.pop("simulation_id")

        experiment_id = d.pop("experiment_id")

        simulator_id = d.pop("simulator_id")

        container_def_hash = d.pop("container_def_hash")

        status = d.pop("status")

        def _parse_created_at(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        created_at = _parse_created_at(d.pop("created_at", UNSET))

        def _parse_simulator(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        simulator = _parse_simulator(d.pop("simulator", UNSET))

        _visibility = d.pop("visibility", UNSET)
        visibility: Visibility | Unset
        if isinstance(_visibility, Unset):
            visibility = UNSET
        else:
            visibility = Visibility(_visibility)

        def _parse_slurm_job_id(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        slurm_job_id = _parse_slurm_job_id(d.pop("slurm_job_id", UNSET))

        def _parse_start_time(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        start_time = _parse_start_time(d.pop("start_time", UNSET))

        def _parse_end_time(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        end_time = _parse_end_time(d.pop("end_time", UNSET))

        def _parse_exit_code(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        exit_code = _parse_exit_code(d.pop("exit_code", UNSET))

        def _parse_error_message(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        error_message = _parse_error_message(d.pop("error_message", UNSET))

        def _parse_trace_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        trace_id = _parse_trace_id(d.pop("trace_id", UNSET))

        simulation_summary = cls(
            simulation_id=simulation_id,
            experiment_id=experiment_id,
            simulator_id=simulator_id,
            container_def_hash=container_def_hash,
            status=status,
            created_at=created_at,
            simulator=simulator,
            visibility=visibility,
            slurm_job_id=slurm_job_id,
            start_time=start_time,
            end_time=end_time,
            exit_code=exit_code,
            error_message=error_message,
            trace_id=trace_id,
        )

        simulation_summary.additional_properties = d
        return simulation_summary

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
