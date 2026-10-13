from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.image_kind import ImageKind
from ..types import UNSET, Unset

T = TypeVar("T", bound="EnvironmentImage")


@_attrs_define
class EnvironmentImage:
    """A built or pulled image of a simulator's definition (docs/plan-environment-builds.md, E3).

    Images are write-once (E4): one that turns out missing is marked unavailable, never replaced in place.

        Attributes:
            database_id (int):
            simulator_id (int):
            kind (ImageKind):
            location (str):
            digest (None | str | Unset):
            size_bytes (int | None | Unset):
            hpcrun_id (int | None | Unset):
            available (bool | Unset):  Default: True.
            created_at (datetime.datetime | None | Unset):
            verified_at (datetime.datetime | None | Unset):
    """

    database_id: int
    simulator_id: int
    kind: ImageKind
    location: str
    digest: None | str | Unset = UNSET
    size_bytes: int | None | Unset = UNSET
    hpcrun_id: int | None | Unset = UNSET
    available: bool | Unset = True
    created_at: datetime.datetime | None | Unset = UNSET
    verified_at: datetime.datetime | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        database_id = self.database_id

        simulator_id = self.simulator_id

        kind = self.kind.value

        location = self.location

        digest: None | str | Unset
        if isinstance(self.digest, Unset):
            digest = UNSET
        else:
            digest = self.digest

        size_bytes: int | None | Unset
        if isinstance(self.size_bytes, Unset):
            size_bytes = UNSET
        else:
            size_bytes = self.size_bytes

        hpcrun_id: int | None | Unset
        if isinstance(self.hpcrun_id, Unset):
            hpcrun_id = UNSET
        else:
            hpcrun_id = self.hpcrun_id

        available = self.available

        created_at: None | str | Unset
        if isinstance(self.created_at, Unset):
            created_at = UNSET
        elif isinstance(self.created_at, datetime.datetime):
            created_at = self.created_at.isoformat()
        else:
            created_at = self.created_at

        verified_at: None | str | Unset
        if isinstance(self.verified_at, Unset):
            verified_at = UNSET
        elif isinstance(self.verified_at, datetime.datetime):
            verified_at = self.verified_at.isoformat()
        else:
            verified_at = self.verified_at

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "database_id": database_id,
            "simulator_id": simulator_id,
            "kind": kind,
            "location": location,
        })
        if digest is not UNSET:
            field_dict["digest"] = digest
        if size_bytes is not UNSET:
            field_dict["size_bytes"] = size_bytes
        if hpcrun_id is not UNSET:
            field_dict["hpcrun_id"] = hpcrun_id
        if available is not UNSET:
            field_dict["available"] = available
        if created_at is not UNSET:
            field_dict["created_at"] = created_at
        if verified_at is not UNSET:
            field_dict["verified_at"] = verified_at

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        database_id = d.pop("database_id")

        simulator_id = d.pop("simulator_id")

        kind = ImageKind(d.pop("kind"))

        location = d.pop("location")

        def _parse_digest(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        digest = _parse_digest(d.pop("digest", UNSET))

        def _parse_size_bytes(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        size_bytes = _parse_size_bytes(d.pop("size_bytes", UNSET))

        def _parse_hpcrun_id(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        hpcrun_id = _parse_hpcrun_id(d.pop("hpcrun_id", UNSET))

        available = d.pop("available", UNSET)

        def _parse_created_at(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                created_at_type_0 = datetime.datetime.fromisoformat(data)

                return created_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        created_at = _parse_created_at(d.pop("created_at", UNSET))

        def _parse_verified_at(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                verified_at_type_0 = datetime.datetime.fromisoformat(data)

                return verified_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        verified_at = _parse_verified_at(d.pop("verified_at", UNSET))

        environment_image = cls(
            database_id=database_id,
            simulator_id=simulator_id,
            kind=kind,
            location=location,
            digest=digest,
            size_bytes=size_bytes,
            hpcrun_id=hpcrun_id,
            available=available,
            created_at=created_at,
            verified_at=verified_at,
        )

        environment_image.additional_properties = d
        return environment_image

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
