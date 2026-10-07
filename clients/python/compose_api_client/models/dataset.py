from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.dataset_attributes import DatasetAttributes


T = TypeVar("T", bound="Dataset")


@_attrs_define
class Dataset:
    """A file a run produced, readable by anyone who may read its simulation (O7).

    Attributes:
        id (str):
        simulation_id (int):
        path (str):
        kind (str):
        media_type (str):
        display_name (str):
        origin (str):
        size_bytes (int | None | Unset):
        sha256 (None | str | Unset):
        attributes (DatasetAttributes | Unset):
        span_id (None | str | Unset):
        available (bool | Unset):  Default: True.
        created_at (None | str | Unset):
        updated_at (None | str | Unset):
    """

    id: str
    simulation_id: int
    path: str
    kind: str
    media_type: str
    display_name: str
    origin: str
    size_bytes: int | None | Unset = UNSET
    sha256: None | str | Unset = UNSET
    attributes: DatasetAttributes | Unset = UNSET
    span_id: None | str | Unset = UNSET
    available: bool | Unset = True
    created_at: None | str | Unset = UNSET
    updated_at: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = self.id

        simulation_id = self.simulation_id

        path = self.path

        kind = self.kind

        media_type = self.media_type

        display_name = self.display_name

        origin = self.origin

        size_bytes: int | None | Unset
        if isinstance(self.size_bytes, Unset):
            size_bytes = UNSET
        else:
            size_bytes = self.size_bytes

        sha256: None | str | Unset
        if isinstance(self.sha256, Unset):
            sha256 = UNSET
        else:
            sha256 = self.sha256

        attributes: dict[str, Any] | Unset = UNSET
        if not isinstance(self.attributes, Unset):
            attributes = self.attributes.to_dict()

        span_id: None | str | Unset
        if isinstance(self.span_id, Unset):
            span_id = UNSET
        else:
            span_id = self.span_id

        available = self.available

        created_at: None | str | Unset
        if isinstance(self.created_at, Unset):
            created_at = UNSET
        else:
            created_at = self.created_at

        updated_at: None | str | Unset
        if isinstance(self.updated_at, Unset):
            updated_at = UNSET
        else:
            updated_at = self.updated_at

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "id": id,
            "simulation_id": simulation_id,
            "path": path,
            "kind": kind,
            "media_type": media_type,
            "display_name": display_name,
            "origin": origin,
        })
        if size_bytes is not UNSET:
            field_dict["size_bytes"] = size_bytes
        if sha256 is not UNSET:
            field_dict["sha256"] = sha256
        if attributes is not UNSET:
            field_dict["attributes"] = attributes
        if span_id is not UNSET:
            field_dict["span_id"] = span_id
        if available is not UNSET:
            field_dict["available"] = available
        if created_at is not UNSET:
            field_dict["created_at"] = created_at
        if updated_at is not UNSET:
            field_dict["updated_at"] = updated_at

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.dataset_attributes import DatasetAttributes  # noqa: PLC0415

        d = dict(src_dict)
        id = d.pop("id")

        simulation_id = d.pop("simulation_id")

        path = d.pop("path")

        kind = d.pop("kind")

        media_type = d.pop("media_type")

        display_name = d.pop("display_name")

        origin = d.pop("origin")

        def _parse_size_bytes(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        size_bytes = _parse_size_bytes(d.pop("size_bytes", UNSET))

        def _parse_sha256(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        sha256 = _parse_sha256(d.pop("sha256", UNSET))

        _attributes = d.pop("attributes", UNSET)
        attributes: DatasetAttributes | Unset
        if isinstance(_attributes, Unset):
            attributes = UNSET
        else:
            attributes = DatasetAttributes.from_dict(_attributes)

        def _parse_span_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        span_id = _parse_span_id(d.pop("span_id", UNSET))

        available = d.pop("available", UNSET)

        def _parse_created_at(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        created_at = _parse_created_at(d.pop("created_at", UNSET))

        def _parse_updated_at(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        updated_at = _parse_updated_at(d.pop("updated_at", UNSET))

        dataset = cls(
            id=id,
            simulation_id=simulation_id,
            path=path,
            kind=kind,
            media_type=media_type,
            display_name=display_name,
            origin=origin,
            size_bytes=size_bytes,
            sha256=sha256,
            attributes=attributes,
            span_id=span_id,
            available=available,
            created_at=created_at,
            updated_at=updated_at,
        )

        dataset.additional_properties = d
        return dataset

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
