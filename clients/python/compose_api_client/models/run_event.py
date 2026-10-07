from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.run_event_baggage_type_0 import RunEventBaggageType0
    from ..models.run_event_payload_type_0 import RunEventPayloadType0
    from ..models.run_event_tags_type_0 import RunEventTagsType0


T = TypeVar("T", bound="RunEvent")


@_attrs_define
class RunEvent:
    """One structured event of a run, from the API, the job script or the simulator's engine.

    Attributes:
        seq (int):
        source (str):
        ts (str):
        component (str):
        event (str):
        cursor (int | None | Unset):
        level (str | Unset):  Default: 'info'.
        baggage (None | RunEventBaggageType0 | Unset):
        global_time (float | None | Unset):
        wall_time (float | None | Unset):
        span_id (None | str | Unset):
        parent_span_id (None | str | Unset):
        payload (None | RunEventPayloadType0 | Unset):
        tags (None | RunEventTagsType0 | Unset):
    """

    seq: int
    source: str
    ts: str
    component: str
    event: str
    cursor: int | None | Unset = UNSET
    level: str | Unset = "info"
    baggage: None | RunEventBaggageType0 | Unset = UNSET
    global_time: float | None | Unset = UNSET
    wall_time: float | None | Unset = UNSET
    span_id: None | str | Unset = UNSET
    parent_span_id: None | str | Unset = UNSET
    payload: None | RunEventPayloadType0 | Unset = UNSET
    tags: None | RunEventTagsType0 | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.run_event_baggage_type_0 import RunEventBaggageType0  # noqa: PLC0415
        from ..models.run_event_payload_type_0 import RunEventPayloadType0  # noqa: PLC0415
        from ..models.run_event_tags_type_0 import RunEventTagsType0  # noqa: PLC0415

        seq = self.seq

        source = self.source

        ts = self.ts

        component = self.component

        event = self.event

        cursor: int | None | Unset
        if isinstance(self.cursor, Unset):
            cursor = UNSET
        else:
            cursor = self.cursor

        level = self.level

        baggage: dict[str, Any] | None | Unset
        if isinstance(self.baggage, Unset):
            baggage = UNSET
        elif isinstance(self.baggage, RunEventBaggageType0):
            baggage = self.baggage.to_dict()
        else:
            baggage = self.baggage

        global_time: float | None | Unset
        if isinstance(self.global_time, Unset):
            global_time = UNSET
        else:
            global_time = self.global_time

        wall_time: float | None | Unset
        if isinstance(self.wall_time, Unset):
            wall_time = UNSET
        else:
            wall_time = self.wall_time

        span_id: None | str | Unset
        if isinstance(self.span_id, Unset):
            span_id = UNSET
        else:
            span_id = self.span_id

        parent_span_id: None | str | Unset
        if isinstance(self.parent_span_id, Unset):
            parent_span_id = UNSET
        else:
            parent_span_id = self.parent_span_id

        payload: dict[str, Any] | None | Unset
        if isinstance(self.payload, Unset):
            payload = UNSET
        elif isinstance(self.payload, RunEventPayloadType0):
            payload = self.payload.to_dict()
        else:
            payload = self.payload

        tags: dict[str, Any] | None | Unset
        if isinstance(self.tags, Unset):
            tags = UNSET
        elif isinstance(self.tags, RunEventTagsType0):
            tags = self.tags.to_dict()
        else:
            tags = self.tags

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "seq": seq,
            "source": source,
            "ts": ts,
            "component": component,
            "event": event,
        })
        if cursor is not UNSET:
            field_dict["cursor"] = cursor
        if level is not UNSET:
            field_dict["level"] = level
        if baggage is not UNSET:
            field_dict["baggage"] = baggage
        if global_time is not UNSET:
            field_dict["global_time"] = global_time
        if wall_time is not UNSET:
            field_dict["wall_time"] = wall_time
        if span_id is not UNSET:
            field_dict["span_id"] = span_id
        if parent_span_id is not UNSET:
            field_dict["parent_span_id"] = parent_span_id
        if payload is not UNSET:
            field_dict["payload"] = payload
        if tags is not UNSET:
            field_dict["tags"] = tags

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.run_event_baggage_type_0 import RunEventBaggageType0  # noqa: PLC0415
        from ..models.run_event_payload_type_0 import RunEventPayloadType0  # noqa: PLC0415
        from ..models.run_event_tags_type_0 import RunEventTagsType0  # noqa: PLC0415

        d = dict(src_dict)
        seq = d.pop("seq")

        source = d.pop("source")

        ts = d.pop("ts")

        component = d.pop("component")

        event = d.pop("event")

        def _parse_cursor(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        cursor = _parse_cursor(d.pop("cursor", UNSET))

        level = d.pop("level", UNSET)

        def _parse_baggage(data: object) -> None | RunEventBaggageType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                baggage_type_0 = RunEventBaggageType0.from_dict(data)

                return baggage_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | RunEventBaggageType0 | Unset, data)

        baggage = _parse_baggage(d.pop("baggage", UNSET))

        def _parse_global_time(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        global_time = _parse_global_time(d.pop("global_time", UNSET))

        def _parse_wall_time(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        wall_time = _parse_wall_time(d.pop("wall_time", UNSET))

        def _parse_span_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        span_id = _parse_span_id(d.pop("span_id", UNSET))

        def _parse_parent_span_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        parent_span_id = _parse_parent_span_id(d.pop("parent_span_id", UNSET))

        def _parse_payload(data: object) -> None | RunEventPayloadType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                payload_type_0 = RunEventPayloadType0.from_dict(data)

                return payload_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | RunEventPayloadType0 | Unset, data)

        payload = _parse_payload(d.pop("payload", UNSET))

        def _parse_tags(data: object) -> None | RunEventTagsType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                tags_type_0 = RunEventTagsType0.from_dict(data)

                return tags_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | RunEventTagsType0 | Unset, data)

        tags = _parse_tags(d.pop("tags", UNSET))

        run_event = cls(
            seq=seq,
            source=source,
            ts=ts,
            component=component,
            event=event,
            cursor=cursor,
            level=level,
            baggage=baggage,
            global_time=global_time,
            wall_time=wall_time,
            span_id=span_id,
            parent_span_id=parent_span_id,
            payload=payload,
            tags=tags,
        )

        run_event.additional_properties = d
        return run_event

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
