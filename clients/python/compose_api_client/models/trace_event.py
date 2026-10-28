from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.trace_event_args import TraceEventArgs


T = TypeVar("T", bound="TraceEvent")


@_attrs_define
class TraceEvent:
    """
    Attributes:
        ph (str):
        pid (int):
        tid (int):
        name (str | Unset):
        cat (str | Unset):
        ts (int | Unset):
        dur (int | Unset):
        s (str | Unset):
        args (TraceEventArgs | Unset):
    """

    ph: str
    pid: int
    tid: int
    name: str | Unset = UNSET
    cat: str | Unset = UNSET
    ts: int | Unset = UNSET
    dur: int | Unset = UNSET
    s: str | Unset = UNSET
    args: TraceEventArgs | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        ph = self.ph

        pid = self.pid

        tid = self.tid

        name = self.name

        cat = self.cat

        ts = self.ts

        dur = self.dur

        s = self.s

        args: dict[str, Any] | Unset = UNSET
        if not isinstance(self.args, Unset):
            args = self.args.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "ph": ph,
            "pid": pid,
            "tid": tid,
        })
        if name is not UNSET:
            field_dict["name"] = name
        if cat is not UNSET:
            field_dict["cat"] = cat
        if ts is not UNSET:
            field_dict["ts"] = ts
        if dur is not UNSET:
            field_dict["dur"] = dur
        if s is not UNSET:
            field_dict["s"] = s
        if args is not UNSET:
            field_dict["args"] = args

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.trace_event_args import TraceEventArgs  # noqa: PLC0415

        d = dict(src_dict)
        ph = d.pop("ph")

        pid = d.pop("pid")

        tid = d.pop("tid")

        name = d.pop("name", UNSET)

        cat = d.pop("cat", UNSET)

        ts = d.pop("ts", UNSET)

        dur = d.pop("dur", UNSET)

        s = d.pop("s", UNSET)

        _args = d.pop("args", UNSET)
        args: TraceEventArgs | Unset
        if isinstance(_args, Unset):
            args = UNSET
        else:
            args = TraceEventArgs.from_dict(_args)

        trace_event = cls(
            ph=ph,
            pid=pid,
            tid=tid,
            name=name,
            cat=cat,
            ts=ts,
            dur=dur,
            s=s,
            args=args,
        )

        trace_event.additional_properties = d
        return trace_event

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
