from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

T = TypeVar("T", bound="NewEnvironmentVersion")


@_attrs_define
class NewEnvironmentVersion:
    """What to make a version from. A composed environment (one that lists its registry entries): a date to resolve
    its entries at (default now); a mash-up is an environment of its own, never a version of another. A prebuilt one:
    its image by digest. (Library lists, the shared uv path's `custom` versions, are retired:
    docs/plan-environment-composition.md, D8.5; versions made that way stay readable.)

        Attributes:
            resolved_at (datetime.datetime | None | Unset):
            image (None | str | Unset):
            note (None | str | Unset):
    """

    resolved_at: datetime.datetime | None | Unset = UNSET
    image: None | str | Unset = UNSET
    note: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        resolved_at: None | str | Unset
        if isinstance(self.resolved_at, Unset):
            resolved_at = UNSET
        elif isinstance(self.resolved_at, datetime.datetime):
            resolved_at = self.resolved_at.isoformat()
        else:
            resolved_at = self.resolved_at

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

        field_dict.update({})
        if resolved_at is not UNSET:
            field_dict["resolved_at"] = resolved_at
        if image is not UNSET:
            field_dict["image"] = image
        if note is not UNSET:
            field_dict["note"] = note

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
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
            image=image,
            note=note,
        )

        return new_environment_version
