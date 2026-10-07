from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.run_event import RunEvent
    from ..models.run_span import RunSpan


T = TypeVar("T", bound="SpanTree")


@_attrs_define
class SpanTree:
    """A span with its own events (those whose ``span_id`` is the span's) and its children, by start time.

    Attributes:
        span (RunSpan): A node of a run's trace tree, folded from ``span.start`` / ``span.end`` events. ``end_ts`` is
            None while open.
        events (list[RunEvent] | Unset):
        children (list[SpanTree] | Unset):
    """

    span: RunSpan
    events: list[RunEvent] | Unset = UNSET
    children: list[SpanTree] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        span = self.span.to_dict()

        events: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.events, Unset):
            events = []
            for events_item_data in self.events:
                events_item = events_item_data.to_dict()
                events.append(events_item)

        children: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.children, Unset):
            children = []
            for children_item_data in self.children:
                children_item = children_item_data.to_dict()
                children.append(children_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "span": span,
        })
        if events is not UNSET:
            field_dict["events"] = events
        if children is not UNSET:
            field_dict["children"] = children

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.run_event import RunEvent  # noqa: PLC0415
        from ..models.run_span import RunSpan  # noqa: PLC0415

        d = dict(src_dict)
        span = RunSpan.from_dict(d.pop("span"))

        _events = d.pop("events", UNSET)
        events: list[RunEvent] | Unset = UNSET
        if _events is not UNSET:
            events = []
            for events_item_data in _events:
                events_item = RunEvent.from_dict(events_item_data)

                events.append(events_item)

        _children = d.pop("children", UNSET)
        children: list[SpanTree] | Unset = UNSET
        if _children is not UNSET:
            children = []
            for children_item_data in _children:
                children_item = SpanTree.from_dict(children_item_data)

                children.append(children_item)

        span_tree = cls(
            span=span,
            events=events,
            children=children,
        )

        span_tree.additional_properties = d
        return span_tree

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
