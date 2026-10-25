from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.suite_run_info_environment_versions import SuiteRunInfoEnvironmentVersions


T = TypeVar("T", bound="SuiteRunInfo")


@_attrs_define
class SuiteRunInfo:
    """
    Attributes:
        number (int):
        created_at (None | str):
        status (str):
        environment_versions (SuiteRunInfoEnvironmentVersions | Unset): The environment versions its runs use,
            {environment: number}; empty for runs started before suites named them (theirs got the default)
    """

    number: int
    created_at: None | str
    status: str
    environment_versions: SuiteRunInfoEnvironmentVersions | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        number = self.number

        created_at: None | str
        created_at = self.created_at

        status = self.status

        environment_versions: dict[str, Any] | Unset = UNSET
        if not isinstance(self.environment_versions, Unset):
            environment_versions = self.environment_versions.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "number": number,
            "created_at": created_at,
            "status": status,
        })
        if environment_versions is not UNSET:
            field_dict["environment_versions"] = environment_versions

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.suite_run_info_environment_versions import SuiteRunInfoEnvironmentVersions  # noqa: PLC0415

        d = dict(src_dict)
        number = d.pop("number")

        def _parse_created_at(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        created_at = _parse_created_at(d.pop("created_at"))

        status = d.pop("status")

        _environment_versions = d.pop("environment_versions", UNSET)
        environment_versions: SuiteRunInfoEnvironmentVersions | Unset
        if isinstance(_environment_versions, Unset):
            environment_versions = UNSET
        else:
            environment_versions = SuiteRunInfoEnvironmentVersions.from_dict(_environment_versions)

        suite_run_info = cls(
            number=number,
            created_at=created_at,
            status=status,
            environment_versions=environment_versions,
        )

        suite_run_info.additional_properties = d
        return suite_run_info

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
