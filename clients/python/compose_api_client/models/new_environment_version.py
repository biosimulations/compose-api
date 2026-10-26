from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.new_environment_version_libraries_type_0_item import NewEnvironmentVersionLibrariesType0Item


T = TypeVar("T", bound="NewEnvironmentVersion")


@_attrs_define
class NewEnvironmentVersion:
    """What to make a version from. A composed environment (one that lists its registry entries): a date to resolve
    its entries at (default now); a mash-up is an environment of its own, never a version of another. A shared one
    without entries: a date, and optionally a library list other than the registry's (an unreviewed, `custom`
    version). A prebuilt one: its image by digest.

        Attributes:
            resolved_at (datetime.datetime | None | Unset):
            libraries (list[NewEnvironmentVersionLibrariesType0Item] | None | Unset):
            image (None | str | Unset):
            note (None | str | Unset):
    """

    resolved_at: datetime.datetime | None | Unset = UNSET
    libraries: list[NewEnvironmentVersionLibrariesType0Item] | None | Unset = UNSET
    image: None | str | Unset = UNSET
    note: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        resolved_at: None | str | Unset
        if isinstance(self.resolved_at, Unset):
            resolved_at = UNSET
        elif isinstance(self.resolved_at, datetime.datetime):
            resolved_at = self.resolved_at.isoformat()
        else:
            resolved_at = self.resolved_at

        libraries: list[dict[str, Any]] | None | Unset
        if isinstance(self.libraries, Unset):
            libraries = UNSET
        elif isinstance(self.libraries, list):
            libraries = []
            for libraries_type_0_item_data in self.libraries:
                libraries_type_0_item = libraries_type_0_item_data.to_dict()
                libraries.append(libraries_type_0_item)

        else:
            libraries = self.libraries

        image: None | str | Unset
        if isinstance(self.image, Unset):
            image = UNSET
        else:
            image = self.image

        note: None | str | Unset
        if isinstance(self.note, Unset):
            note = UNSET
        else:
            note = self.note

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if resolved_at is not UNSET:
            field_dict["resolved_at"] = resolved_at
        if libraries is not UNSET:
            field_dict["libraries"] = libraries
        if image is not UNSET:
            field_dict["image"] = image
        if note is not UNSET:
            field_dict["note"] = note

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.new_environment_version_libraries_type_0_item import (
            NewEnvironmentVersionLibrariesType0Item,  # noqa: PLC0415
        )

        d = dict(src_dict)

        def _parse_resolved_at(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                resolved_at_type_0 = datetime.datetime.fromisoformat(data)

                return resolved_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        resolved_at = _parse_resolved_at(d.pop("resolved_at", UNSET))

        def _parse_libraries(data: object) -> list[NewEnvironmentVersionLibrariesType0Item] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                libraries_type_0 = []
                _libraries_type_0 = data
                for libraries_type_0_item_data in _libraries_type_0:
                    libraries_type_0_item = NewEnvironmentVersionLibrariesType0Item.from_dict(
                        libraries_type_0_item_data
                    )

                    libraries_type_0.append(libraries_type_0_item)

                return libraries_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[NewEnvironmentVersionLibrariesType0Item] | None | Unset, data)

        libraries = _parse_libraries(d.pop("libraries", UNSET))

        def _parse_image(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        image = _parse_image(d.pop("image", UNSET))

        def _parse_note(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        note = _parse_note(d.pop("note", UNSET))

        new_environment_version = cls(
            resolved_at=resolved_at,
            libraries=libraries,
            image=image,
            note=note,
        )

        new_environment_version.additional_properties = d
        return new_environment_version

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
