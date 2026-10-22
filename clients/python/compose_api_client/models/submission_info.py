from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.submission_state import SubmissionState
from ..types import UNSET, Unset

T = TypeVar("T", bound="SubmissionInfo")


@_attrs_define
class SubmissionInfo:
    """Where a run is on its way to SLURM (docs/plan-durable-submission.md): the detail behind `submitting`.

    Attributes:
        state (SubmissionState): Where a run is on its way to SLURM (docs/plan-durable-submission.md, Q1). The public
            status stays
            ``submitting`` until the run has a SLURM job; this is the detail behind it.
        queue (str):
        position (int | None | Unset):
        attempts (int | Unset):  Default: 0.
        last_error (None | str | Unset):
    """

    state: SubmissionState
    queue: str
    position: int | None | Unset = UNSET
    attempts: int | Unset = 0
    last_error: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        state = self.state.value

        queue = self.queue

        position: int | None | Unset
        if isinstance(self.position, Unset):
            position = UNSET
        else:
            position = self.position

        attempts = self.attempts

        last_error: None | str | Unset
        if isinstance(self.last_error, Unset):
            last_error = UNSET
        else:
            last_error = self.last_error

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "state": state,
            "queue": queue,
        })
        if position is not UNSET:
            field_dict["position"] = position
        if attempts is not UNSET:
            field_dict["attempts"] = attempts
        if last_error is not UNSET:
            field_dict["last_error"] = last_error

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        state = SubmissionState(d.pop("state"))

        queue = d.pop("queue")

        def _parse_position(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        position = _parse_position(d.pop("position", UNSET))

        attempts = d.pop("attempts", UNSET)

        def _parse_last_error(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        last_error = _parse_last_error(d.pop("last_error", UNSET))

        submission_info = cls(
            state=state,
            queue=queue,
            position=position,
            attempts=attempts,
            last_error=last_error,
        )

        submission_info.additional_properties = d
        return submission_info

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
