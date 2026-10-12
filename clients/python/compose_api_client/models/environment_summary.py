from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.environment_summary_kind import EnvironmentSummaryKind
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.entry_ref import EntryRef


T = TypeVar("T", bound="EnvironmentSummary")


@_attrs_define
class EnvironmentSummary:
    """
    Attributes:
        name (str):
        kind (EnvironmentSummaryKind):
        simulator (None | str): The value of /simulation/run's `simulator` for this environment
        image (None | str): The image this deployment runs it in
        manifest_image (None | str): The image the manifest was read from
        stale (bool): The manifest was read from another image than the one deployed
        components (int):
        errors (int):
        entries (list[EntryRef]):
        process_bigraph (None | str | Unset):
    """

    name: str
    kind: EnvironmentSummaryKind
    simulator: None | str
    image: None | str
    manifest_image: None | str
    stale: bool
    components: int
    errors: int
    entries: list[EntryRef]
    process_bigraph: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        name = self.name

        kind = self.kind.value

        simulator: None | str
        simulator = self.simulator

        image: None | str
        image = self.image

        manifest_image: None | str
        manifest_image = self.manifest_image

        stale = self.stale

        components = self.components

        errors = self.errors

        entries = []
        for entries_item_data in self.entries:
            entries_item = entries_item_data.to_dict()
            entries.append(entries_item)

        process_bigraph: None | str | Unset
        if isinstance(self.process_bigraph, Unset):
            process_bigraph = UNSET
        else:
            process_bigraph = self.process_bigraph

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "name": name,
            "kind": kind,
            "simulator": simulator,
            "image": image,
            "manifest_image": manifest_image,
            "stale": stale,
            "components": components,
            "errors": errors,
            "entries": entries,
        })
        if process_bigraph is not UNSET:
            field_dict["process_bigraph"] = process_bigraph

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.entry_ref import EntryRef  # noqa: PLC0415

        d = dict(src_dict)
        name = d.pop("name")

        kind = EnvironmentSummaryKind(d.pop("kind"))

        def _parse_simulator(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        simulator = _parse_simulator(d.pop("simulator"))

        def _parse_image(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        image = _parse_image(d.pop("image"))

        def _parse_manifest_image(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        manifest_image = _parse_manifest_image(d.pop("manifest_image"))

        stale = d.pop("stale")

        components = d.pop("components")

        errors = d.pop("errors")

        entries = []
        _entries = d.pop("entries")
        for entries_item_data in _entries:
            entries_item = EntryRef.from_dict(entries_item_data)

            entries.append(entries_item)

        def _parse_process_bigraph(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        process_bigraph = _parse_process_bigraph(d.pop("process_bigraph", UNSET))

        environment_summary = cls(
            name=name,
            kind=kind,
            simulator=simulator,
            image=image,
            manifest_image=manifest_image,
            stale=stale,
            components=components,
            errors=errors,
            entries=entries,
            process_bigraph=process_bigraph,
        )

        environment_summary.additional_properties = d
        return environment_summary

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
