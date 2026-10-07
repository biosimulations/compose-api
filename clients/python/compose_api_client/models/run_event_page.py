from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.run_event import RunEvent


T = TypeVar("T", bound="RunEventPage")


@_attrs_define
class RunEventPage:
    """A page of a simulation's events, in the order they were recorded.

    ``next_cursor`` is the ``after`` for the next page, None at the end.

        Attributes:
            simulation_id (int):
            trace_id (None | str):
            events (list[RunEvent]):
            next_cursor (int | None | Unset):
    """

    simulation_id: int
    trace_id: None | str
    events: list[RunEvent]
    next_cursor: int | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        simulation_id = self.simulation_id

        trace_id: None | str
        trace_id = self.trace_id

        events = []
        for events_item_data in self.events:
            events_item = events_item_data.to_dict()
            events.append(events_item)

        next_cursor: int | None | Unset
        if isinstance(self.next_cursor, Unset):
            next_cursor = UNSET
        else:
            next_cursor = self.next_cursor

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "simulation_id": simulation_id,
            "trace_id": trace_id,
            "events": events,
        })
        if next_cursor is not UNSET:
            field_dict["next_cursor"] = next_cursor

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.run_event import RunEvent  # noqa: PLC0415

        d = dict(src_dict)
        simulation_id = d.pop("simulation_id")

        def _parse_trace_id(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        trace_id = _parse_trace_id(d.pop("trace_id"))

        events = []
        _events = d.pop("events")
        for events_item_data in _events:
            events_item = RunEvent.from_dict(events_item_data)

            events.append(events_item)

        def _parse_next_cursor(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        next_cursor = _parse_next_cursor(d.pop("next_cursor", UNSET))

        run_event_page = cls(
            simulation_id=simulation_id,
            trace_id=trace_id,
            events=events,
            next_cursor=next_cursor,
        )

        run_event_page.additional_properties = d
        return run_event_page

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
