from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.version_ref import VersionRef


T = TypeVar("T", bound="SimulatorSummary")


@_attrs_define
class SimulatorSummary:
    """A simulator (a container definition, identified by its hash) as runs used it (docs/plan-webapp-admin.md, 5c).
    One recorded before environment versions is no version's, and is reached only this way.

        Attributes:
            simulator_id (int):
            container_def_hash (str):
            created_at (datetime.datetime | None | Unset):
            versions (list[VersionRef] | Unset): The environment versions it is; none for one from before versions
            run_count (int | Unset): How many runs you can read used it Default: 0.
            first_run_at (datetime.datetime | None | Unset):
            last_run_at (datetime.datetime | None | Unset):
    """

    simulator_id: int
    container_def_hash: str
    created_at: datetime.datetime | None | Unset = UNSET
    versions: list[VersionRef] | Unset = UNSET
    run_count: int | Unset = 0
    first_run_at: datetime.datetime | None | Unset = UNSET
    last_run_at: datetime.datetime | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        simulator_id = self.simulator_id

        container_def_hash = self.container_def_hash

        created_at: None | str | Unset
        if isinstance(self.created_at, Unset):
            created_at = UNSET
        elif isinstance(self.created_at, datetime.datetime):
            created_at = self.created_at.isoformat()
        else:
            created_at = self.created_at

        versions: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.versions, Unset):
            versions = []
            for versions_item_data in self.versions:
                versions_item = versions_item_data.to_dict()
                versions.append(versions_item)

        run_count = self.run_count

        first_run_at: None | str | Unset
        if isinstance(self.first_run_at, Unset):
            first_run_at = UNSET
        elif isinstance(self.first_run_at, datetime.datetime):
            first_run_at = self.first_run_at.isoformat()
        else:
            first_run_at = self.first_run_at

        last_run_at: None | str | Unset
        if isinstance(self.last_run_at, Unset):
            last_run_at = UNSET
        elif isinstance(self.last_run_at, datetime.datetime):
            last_run_at = self.last_run_at.isoformat()
        else:
            last_run_at = self.last_run_at

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "simulator_id": simulator_id,
            "container_def_hash": container_def_hash,
        })
        if created_at is not UNSET:
            field_dict["created_at"] = created_at
        if versions is not UNSET:
            field_dict["versions"] = versions
        if run_count is not UNSET:
            field_dict["run_count"] = run_count
        if first_run_at is not UNSET:
            field_dict["first_run_at"] = first_run_at
        if last_run_at is not UNSET:
            field_dict["last_run_at"] = last_run_at

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.version_ref import VersionRef  # noqa: PLC0415

        d = dict(src_dict)
        simulator_id = d.pop("simulator_id")

        container_def_hash = d.pop("container_def_hash")

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

        _versions = d.pop("versions", UNSET)
        versions: list[VersionRef] | Unset = UNSET
        if _versions is not UNSET:
            versions = []
            for versions_item_data in _versions:
                versions_item = VersionRef.from_dict(versions_item_data)

                versions.append(versions_item)

        run_count = d.pop("run_count", UNSET)

        def _parse_first_run_at(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                first_run_at_type_0 = datetime.datetime.fromisoformat(data)

                return first_run_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        first_run_at = _parse_first_run_at(d.pop("first_run_at", UNSET))

        def _parse_last_run_at(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                last_run_at_type_0 = datetime.datetime.fromisoformat(data)

                return last_run_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        last_run_at = _parse_last_run_at(d.pop("last_run_at", UNSET))

        simulator_summary = cls(
            simulator_id=simulator_id,
            container_def_hash=container_def_hash,
            created_at=created_at,
            versions=versions,
            run_count=run_count,
            first_run_at=first_run_at,
            last_run_at=last_run_at,
        )

        simulator_summary.additional_properties = d
        return simulator_summary

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
