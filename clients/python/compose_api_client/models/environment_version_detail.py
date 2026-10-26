from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.version_state import VersionState
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.environment_version_detail_interfaces_type_0 import EnvironmentVersionDetailInterfacesType0
    from ..models.environment_version_detail_spec_type_0 import EnvironmentVersionDetailSpecType0


T = TypeVar("T", bound="EnvironmentVersionDetail")


@_attrs_define
class EnvironmentVersionDetail:
    """A version with what it was resolved to and, once built, what it installed and provides.

    Attributes:
        database_id (int):
        environment_id (int): Its environment's identity; the name below may change
        environment (str): Its environment's current name
        number (int):
        state (VersionState): An environment version's state (docs/plan-environment-versions.md).
        simulator_id (int | None): Its simulator: none while a composed version is resolving
        image (None | str | Unset): A prebuilt version's image, by digest
        spec (EnvironmentVersionDetailSpecType0 | None | Unset): What a shared version was made from
        origin (None | str | Unset): registry, or custom for libraries no review has seen
        resolved_at (datetime.datetime | None | Unset):
        lock_sha256 (None | str | Unset):
        runtime_contract (int | Unset):  Default: 1.
        created_by (None | str | Unset):
        created_at (datetime.datetime | None | Unset):
        note (None | str | Unset):
        failure (None | str | Unset): Why it failed: for a composed version, its lock's conflict
        lock (None | str | Unset): A shared version's lock: every PyPI package, pinned
        installed (None | str | Unset): What its image installed, read from the image
        interfaces (EnvironmentVersionDetailInterfacesType0 | None | Unset): Its process interfaces (pbg-interfaces/1)
    """

    database_id: int
    environment_id: int
    environment: str
    number: int
    state: VersionState
    simulator_id: int | None
    image: None | str | Unset = UNSET
    spec: EnvironmentVersionDetailSpecType0 | None | Unset = UNSET
    origin: None | str | Unset = UNSET
    resolved_at: datetime.datetime | None | Unset = UNSET
    lock_sha256: None | str | Unset = UNSET
    runtime_contract: int | Unset = 1
    created_by: None | str | Unset = UNSET
    created_at: datetime.datetime | None | Unset = UNSET
    note: None | str | Unset = UNSET
    failure: None | str | Unset = UNSET
    lock: None | str | Unset = UNSET
    installed: None | str | Unset = UNSET
    interfaces: EnvironmentVersionDetailInterfacesType0 | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.environment_version_detail_interfaces_type_0 import (
            EnvironmentVersionDetailInterfacesType0,  # noqa: PLC0415
        )
        from ..models.environment_version_detail_spec_type_0 import EnvironmentVersionDetailSpecType0  # noqa: PLC0415

        database_id = self.database_id

        environment_id = self.environment_id

        environment = self.environment

        number = self.number

        state = self.state.value

        simulator_id: int | None
        simulator_id = self.simulator_id

        image: None | str | Unset
        if isinstance(self.image, Unset):
            image = UNSET
        else:
            image = self.image

        spec: dict[str, Any] | None | Unset
        if isinstance(self.spec, Unset):
            spec = UNSET
        elif isinstance(self.spec, EnvironmentVersionDetailSpecType0):
            spec = self.spec.to_dict()
        else:
            spec = self.spec

        origin: None | str | Unset
        if isinstance(self.origin, Unset):
            origin = UNSET
        else:
            origin = self.origin

        resolved_at: None | str | Unset
        if isinstance(self.resolved_at, Unset):
            resolved_at = UNSET
        elif isinstance(self.resolved_at, datetime.datetime):
            resolved_at = self.resolved_at.isoformat()
        else:
            resolved_at = self.resolved_at

        lock_sha256: None | str | Unset
        if isinstance(self.lock_sha256, Unset):
            lock_sha256 = UNSET
        else:
            lock_sha256 = self.lock_sha256

        runtime_contract = self.runtime_contract

        created_by: None | str | Unset
        if isinstance(self.created_by, Unset):
            created_by = UNSET
        else:
            created_by = self.created_by

        created_at: None | str | Unset
        if isinstance(self.created_at, Unset):
            created_at = UNSET
        elif isinstance(self.created_at, datetime.datetime):
            created_at = self.created_at.isoformat()
        else:
            created_at = self.created_at

        note: None | str | Unset
        if isinstance(self.note, Unset):
            note = UNSET
        else:
            note = self.note

        failure: None | str | Unset
        if isinstance(self.failure, Unset):
            failure = UNSET
        else:
            failure = self.failure

        lock: None | str | Unset
        if isinstance(self.lock, Unset):
            lock = UNSET
        else:
            lock = self.lock

        installed: None | str | Unset
        if isinstance(self.installed, Unset):
            installed = UNSET
        else:
            installed = self.installed

        interfaces: dict[str, Any] | None | Unset
        if isinstance(self.interfaces, Unset):
            interfaces = UNSET
        elif isinstance(self.interfaces, EnvironmentVersionDetailInterfacesType0):
            interfaces = self.interfaces.to_dict()
        else:
            interfaces = self.interfaces

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "database_id": database_id,
            "environment_id": environment_id,
            "environment": environment,
            "number": number,
            "state": state,
            "simulator_id": simulator_id,
        })
        if image is not UNSET:
            field_dict["image"] = image
        if spec is not UNSET:
            field_dict["spec"] = spec
        if origin is not UNSET:
            field_dict["origin"] = origin
        if resolved_at is not UNSET:
            field_dict["resolved_at"] = resolved_at
        if lock_sha256 is not UNSET:
            field_dict["lock_sha256"] = lock_sha256
        if runtime_contract is not UNSET:
            field_dict["runtime_contract"] = runtime_contract
        if created_by is not UNSET:
            field_dict["created_by"] = created_by
        if created_at is not UNSET:
            field_dict["created_at"] = created_at
        if note is not UNSET:
            field_dict["note"] = note
        if failure is not UNSET:
            field_dict["failure"] = failure
        if lock is not UNSET:
            field_dict["lock"] = lock
        if installed is not UNSET:
            field_dict["installed"] = installed
        if interfaces is not UNSET:
            field_dict["interfaces"] = interfaces

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.environment_version_detail_interfaces_type_0 import (
            EnvironmentVersionDetailInterfacesType0,  # noqa: PLC0415
        )
        from ..models.environment_version_detail_spec_type_0 import EnvironmentVersionDetailSpecType0  # noqa: PLC0415

        d = dict(src_dict)
        database_id = d.pop("database_id")

        environment_id = d.pop("environment_id")

        environment = d.pop("environment")

        number = d.pop("number")

        state = VersionState(d.pop("state"))

        def _parse_simulator_id(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        simulator_id = _parse_simulator_id(d.pop("simulator_id"))

        def _parse_image(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        image = _parse_image(d.pop("image", UNSET))

        def _parse_spec(data: object) -> EnvironmentVersionDetailSpecType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                spec_type_0 = EnvironmentVersionDetailSpecType0.from_dict(data)

                return spec_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(EnvironmentVersionDetailSpecType0 | None | Unset, data)

        spec = _parse_spec(d.pop("spec", UNSET))

        def _parse_origin(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        origin = _parse_origin(d.pop("origin", UNSET))

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

        def _parse_lock_sha256(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        lock_sha256 = _parse_lock_sha256(d.pop("lock_sha256", UNSET))

        runtime_contract = d.pop("runtime_contract", UNSET)

        def _parse_created_by(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        created_by = _parse_created_by(d.pop("created_by", UNSET))

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

        def _parse_note(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        note = _parse_note(d.pop("note", UNSET))

        def _parse_failure(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        failure = _parse_failure(d.pop("failure", UNSET))

        def _parse_lock(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        lock = _parse_lock(d.pop("lock", UNSET))

        def _parse_installed(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        installed = _parse_installed(d.pop("installed", UNSET))

        def _parse_interfaces(data: object) -> EnvironmentVersionDetailInterfacesType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                interfaces_type_0 = EnvironmentVersionDetailInterfacesType0.from_dict(data)

                return interfaces_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(EnvironmentVersionDetailInterfacesType0 | None | Unset, data)

        interfaces = _parse_interfaces(d.pop("interfaces", UNSET))

        environment_version_detail = cls(
            database_id=database_id,
            environment_id=environment_id,
            environment=environment,
            number=number,
            state=state,
            simulator_id=simulator_id,
            image=image,
            spec=spec,
            origin=origin,
            resolved_at=resolved_at,
            lock_sha256=lock_sha256,
            runtime_contract=runtime_contract,
            created_by=created_by,
            created_at=created_at,
            note=note,
            failure=failure,
            lock=lock,
            installed=installed,
            interfaces=interfaces,
        )

        environment_version_detail.additional_properties = d
        return environment_version_detail

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
