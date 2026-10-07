from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.span_tree import SpanTree


T = TypeVar("T", bound="RunTraceTree")


@_attrs_define
class RunTraceTree:
    """A simulation's spans as a forest, each span carrying its own events.

    Attributes:
        simulation_id (int):
        trace_id (None | str):
        roots (list[SpanTree]):
    """

    simulation_id: int
    trace_id: None | str
    roots: list[SpanTree]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        simulation_id = self.simulation_id

        trace_id: None | str
        trace_id = self.trace_id

        roots = []
        for roots_item_data in self.roots:
            roots_item = roots_item_data.to_dict()
            roots.append(roots_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "simulation_id": simulation_id,
            "trace_id": trace_id,
            "roots": roots,
        })

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.span_tree import SpanTree  # noqa: PLC0415

        d = dict(src_dict)
        simulation_id = d.pop("simulation_id")

        def _parse_trace_id(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        trace_id = _parse_trace_id(d.pop("trace_id"))

        roots = []
        _roots = d.pop("roots")
        for roots_item_data in _roots:
            roots_item = SpanTree.from_dict(roots_item_data)

            roots.append(roots_item)

        run_trace_tree = cls(
            simulation_id=simulation_id,
            trace_id=trace_id,
            roots=roots,
        )

        run_trace_tree.additional_properties = d
        return run_trace_tree

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
