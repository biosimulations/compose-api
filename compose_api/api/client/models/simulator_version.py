from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast
import datetime

if TYPE_CHECKING:
    from ..models.containerization_file_repr import ContainerizationFileRepr
    from ..models.registered_package import RegisteredPackage


T = TypeVar("T", bound="SimulatorVersion")


@_attrs_define
class SimulatorVersion:
    """
    Attributes:
        container_def (ContainerizationFileRepr):
        container_def_hash (str):
        packages (list[RegisteredPackage] | None):
        database_id (int):
        created_at (datetime.datetime | None | Unset):
    """

    container_def: ContainerizationFileRepr
    container_def_hash: str
    packages: list[RegisteredPackage] | None
    database_id: int
    created_at: datetime.datetime | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.containerization_file_repr import ContainerizationFileRepr  # noqa: PLC0415
        from ..models.registered_package import RegisteredPackage  # noqa: PLC0415

        container_def = self.container_def.to_dict()

        container_def_hash = self.container_def_hash

        packages: list[dict[str, Any]] | None
        if isinstance(self.packages, list):
            packages = []
            for packages_type_0_item_data in self.packages:
                packages_type_0_item = packages_type_0_item_data.to_dict()
                packages.append(packages_type_0_item)

        else:
            packages = self.packages

        database_id = self.database_id

        created_at: None | str | Unset
        if isinstance(self.created_at, Unset):
            created_at = UNSET
        elif isinstance(self.created_at, datetime.datetime):
            created_at = self.created_at.isoformat()
        else:
            created_at = self.created_at

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "container_def": container_def,
            "container_def_hash": container_def_hash,
            "packages": packages,
            "database_id": database_id,
        })
        if created_at is not UNSET:
            field_dict["created_at"] = created_at

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.containerization_file_repr import ContainerizationFileRepr  # noqa: PLC0415
        from ..models.registered_package import RegisteredPackage  # noqa: PLC0415

        d = dict(src_dict)
        container_def = ContainerizationFileRepr.from_dict(d.pop("container_def"))

        container_def_hash = d.pop("container_def_hash")

        def _parse_packages(data: object) -> list[RegisteredPackage] | None:
            if data is None:
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                packages_type_0 = []
                _packages_type_0 = data
                for packages_type_0_item_data in _packages_type_0:
                    packages_type_0_item = RegisteredPackage.from_dict(packages_type_0_item_data)

                    packages_type_0.append(packages_type_0_item)

                return packages_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[RegisteredPackage] | None, data)

        packages = _parse_packages(d.pop("packages"))

        database_id = d.pop("database_id")

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

        simulator_version = cls(
            container_def=container_def,
            container_def_hash=container_def_hash,
            packages=packages,
            database_id=database_id,
            created_at=created_at,
        )

        simulator_version.additional_properties = d
        return simulator_version

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
