from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.environment_version import EnvironmentVersion


T = TypeVar("T", bound="EnvironmentVersions")


@_attrs_define
class EnvironmentVersions:
    """An environment's versions, newest first, and which one a run that names none gets.

    Attributes:
        environment (str):
        kind (str):
        default (int | None | Unset): The default version's number
        default_source (str | Unset): deployment: the deployment's own definition is the default; api: an administrator
            chose it Default: 'deployment'.
        versions (list[EnvironmentVersion] | Unset):
    """

    environment: str
    kind: str
    default: int | None | Unset = UNSET
    default_source: str | Unset = "deployment"
    versions: list[EnvironmentVersion] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        environment = self.environment

        kind = self.kind

        default: int | None | Unset
        if isinstance(self.default, Unset):
            default = UNSET
        else:
            default = self.default

        default_source = self.default_source

        versions: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.versions, Unset):
            versions = []
            for versions_item_data in self.versions:
                versions_item = versions_item_data.to_dict()
                versions.append(versions_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "environment": environment,
            "kind": kind,
        })
        if default is not UNSET:
            field_dict["default"] = default
        if default_source is not UNSET:
            field_dict["default_source"] = default_source
        if versions is not UNSET:
            field_dict["versions"] = versions

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.environment_version import EnvironmentVersion  # noqa: PLC0415

        d = dict(src_dict)
        environment = d.pop("environment")

        kind = d.pop("kind")

        def _parse_default(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        default = _parse_default(d.pop("default", UNSET))

        default_source = d.pop("default_source", UNSET)

        _versions = d.pop("versions", UNSET)
        versions: list[EnvironmentVersion] | Unset = UNSET
        if _versions is not UNSET:
            versions = []
            for versions_item_data in _versions:
                versions_item = EnvironmentVersion.from_dict(versions_item_data)

                versions.append(versions_item)

        environment_versions = cls(
            environment=environment,
            kind=kind,
            default=default,
            default_source=default_source,
            versions=versions,
        )

        environment_versions.additional_properties = d
        return environment_versions

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
