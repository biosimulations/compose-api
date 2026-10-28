from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.trace_document_otherdata import TraceDocumentOtherdata
    from ..models.trace_event import TraceEvent


T = TypeVar("T", bound="TraceDocument")


@_attrs_define
class TraceDocument:
    """
    Attributes:
        trace_events (list[TraceEvent]):
        display_time_unit (str):
        other_data (TraceDocumentOtherdata):
    """

    trace_events: list[TraceEvent]
    display_time_unit: str
    other_data: TraceDocumentOtherdata
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        trace_events = []
        for trace_events_item_data in self.trace_events:
            trace_events_item = trace_events_item_data.to_dict()
            trace_events.append(trace_events_item)

        display_time_unit = self.display_time_unit

        other_data = self.other_data.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "traceEvents": trace_events,
            "displayTimeUnit": display_time_unit,
            "otherData": other_data,
        })

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.trace_document_otherdata import TraceDocumentOtherdata  # noqa: PLC0415
        from ..models.trace_event import TraceEvent  # noqa: PLC0415

        d = dict(src_dict)
        trace_events = []
        _trace_events = d.pop("traceEvents")
        for trace_events_item_data in _trace_events:
            trace_events_item = TraceEvent.from_dict(trace_events_item_data)

            trace_events.append(trace_events_item)

        display_time_unit = d.pop("displayTimeUnit")

        other_data = TraceDocumentOtherdata.from_dict(d.pop("otherData"))

        trace_document = cls(
            trace_events=trace_events,
            display_time_unit=display_time_unit,
            other_data=other_data,
        )

        trace_document.additional_properties = d
        return trace_document

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
