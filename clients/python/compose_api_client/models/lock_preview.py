from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.package_change import PackageChange


T = TypeVar("T", bound="LockPreview")


@_attrs_define
class LockPreview:
    """What a shared version would be: its lock, and how it differs from the default version's.

    Attributes:
        environment (str):
        resolved_at (datetime.datetime):
        origin (str):
        lock_sha256 (str):
        lock (str):
        existing (int | None | Unset): The number of a version with this very lock, if any
        against (int | None | Unset): The default version compared with, if it has a lock
        changes (list[PackageChange] | Unset):
    """

    environment: str
    resolved_at: datetime.datetime
    origin: str
    lock_sha256: str
    lock: str
    existing: int | None | Unset = UNSET
    against: int | None | Unset = UNSET
    changes: list[PackageChange] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        environment = self.environment

        resolved_at = self.resolved_at.isoformat()

        origin = self.origin

        lock_sha256 = self.lock_sha256

        lock = self.lock

        existing: int | None | Unset
        if isinstance(self.existing, Unset):
            existing = UNSET
        else:
            existing = self.existing

        against: int | None | Unset
        if isinstance(self.against, Unset):
            against = UNSET
        else:
            against = self.against

        changes: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.changes, Unset):
            changes = []
            for changes_item_data in self.changes:
                changes_item = changes_item_data.to_dict()
                changes.append(changes_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "environment": environment,
            "resolved_at": resolved_at,
            "origin": origin,
            "lock_sha256": lock_sha256,
            "lock": lock,
        })
        if existing is not UNSET:
            field_dict["existing"] = existing
        if against is not UNSET:
            field_dict["against"] = against
        if changes is not UNSET:
            field_dict["changes"] = changes

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.package_change import PackageChange  # noqa: PLC0415

        d = dict(src_dict)
        environment = d.pop("environment")

        resolved_at = datetime.datetime.fromisoformat(d.pop("resolved_at"))

        origin = d.pop("origin")

        lock_sha256 = d.pop("lock_sha256")

        lock = d.pop("lock")

        def _parse_existing(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        existing = _parse_existing(d.pop("existing", UNSET))

        def _parse_against(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        against = _parse_against(d.pop("against", UNSET))

        _changes = d.pop("changes", UNSET)
        changes: list[PackageChange] | Unset = UNSET
        if _changes is not UNSET:
            changes = []
            for changes_item_data in _changes:
                changes_item = PackageChange.from_dict(changes_item_data)

                changes.append(changes_item)

        lock_preview = cls(
            environment=environment,
            resolved_at=resolved_at,
            origin=origin,
            lock_sha256=lock_sha256,
            lock=lock,
            existing=existing,
            against=against,
            changes=changes,
        )

        lock_preview.additional_properties = d
        return lock_preview

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
