from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="ProjectInfo")


@_attrs_define
class ProjectInfo:
    """
    Attributes:
        id (str):
        run (str):
        url (str):
        created (None | str | Unset):
        updated (None | str | Unset):
        simulator (None | str | Unset):
        simulator_version (None | str | Unset):
    """

    id: str
    run: str
    url: str
    created: None | str | Unset = UNSET
    updated: None | str | Unset = UNSET
    simulator: None | str | Unset = UNSET
    simulator_version: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = self.id

        run = self.run

        url = self.url

        created: None | str | Unset
        if isinstance(self.created, Unset):
            created = UNSET
        else:
            created = self.created

        updated: None | str | Unset
        if isinstance(self.updated, Unset):
            updated = UNSET
        else:
            updated = self.updated

        simulator: None | str | Unset
        if isinstance(self.simulator, Unset):
            simulator = UNSET
        else:
            simulator = self.simulator

        simulator_version: None | str | Unset
        if isinstance(self.simulator_version, Unset):
            simulator_version = UNSET
        else:
            simulator_version = self.simulator_version

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "id": id,
            "run": run,
            "url": url,
        })
        if created is not UNSET:
            field_dict["created"] = created
        if updated is not UNSET:
            field_dict["updated"] = updated
        if simulator is not UNSET:
            field_dict["simulator"] = simulator
        if simulator_version is not UNSET:
            field_dict["simulator_version"] = simulator_version

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = d.pop("id")

        run = d.pop("run")

        url = d.pop("url")

        def _parse_created(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        created = _parse_created(d.pop("created", UNSET))

        def _parse_updated(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        updated = _parse_updated(d.pop("updated", UNSET))

        def _parse_simulator(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        simulator = _parse_simulator(d.pop("simulator", UNSET))

        def _parse_simulator_version(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        simulator_version = _parse_simulator_version(d.pop("simulator_version", UNSET))

        project_info = cls(
            id=id,
            run=run,
            url=url,
            created=created,
            updated=updated,
            simulator=simulator,
            simulator_version=simulator_version,
        )

        project_info.additional_properties = d
        return project_info

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
