from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.interface_component import InterfaceComponent
    from ..models.interface_manifest_environment_type_0 import InterfaceManifestEnvironmentType0
    from ..models.interface_manifest_errors_item import InterfaceManifestErrorsItem


T = TypeVar("T", bound="InterfaceManifest")


@_attrs_define
class InterfaceManifest:
    """An environment's interface manifest (`pbg-interfaces/1`), with each component's registry entry added.

    Attributes:
        schema_version (str):
        components (list[InterfaceComponent]):
        schema (None | str | Unset):
        environment (InterfaceManifestEnvironmentType0 | None | Unset):
        errors (list[InterfaceManifestErrorsItem] | Unset):
    """

    schema_version: str
    components: list[InterfaceComponent]
    schema: None | str | Unset = UNSET
    environment: InterfaceManifestEnvironmentType0 | None | Unset = UNSET
    errors: list[InterfaceManifestErrorsItem] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.interface_manifest_environment_type_0 import InterfaceManifestEnvironmentType0  # noqa: PLC0415

        schema_version = self.schema_version

        components = []
        for components_item_data in self.components:
            components_item = components_item_data.to_dict()
            components.append(components_item)

        schema: None | str | Unset
        if isinstance(self.schema, Unset):
            schema = UNSET
        else:
            schema = self.schema

        environment: dict[str, Any] | None | Unset
        if isinstance(self.environment, Unset):
            environment = UNSET
        elif isinstance(self.environment, InterfaceManifestEnvironmentType0):
            environment = self.environment.to_dict()
        else:
            environment = self.environment

        errors: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.errors, Unset):
            errors = []
            for errors_item_data in self.errors:
                errors_item = errors_item_data.to_dict()
                errors.append(errors_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "schema_version": schema_version,
            "components": components,
        })
        if schema is not UNSET:
            field_dict["$schema"] = schema
        if environment is not UNSET:
            field_dict["environment"] = environment
        if errors is not UNSET:
            field_dict["errors"] = errors

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.interface_component import InterfaceComponent  # noqa: PLC0415
        from ..models.interface_manifest_environment_type_0 import InterfaceManifestEnvironmentType0  # noqa: PLC0415
        from ..models.interface_manifest_errors_item import InterfaceManifestErrorsItem  # noqa: PLC0415

        d = dict(src_dict)
        schema_version = d.pop("schema_version")

        components = []
        _components = d.pop("components")
        for components_item_data in _components:
            components_item = InterfaceComponent.from_dict(components_item_data)

            components.append(components_item)

        def _parse_schema(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        schema = _parse_schema(d.pop("$schema", UNSET))

        def _parse_environment(data: object) -> InterfaceManifestEnvironmentType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                environment_type_0 = InterfaceManifestEnvironmentType0.from_dict(data)

                return environment_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(InterfaceManifestEnvironmentType0 | None | Unset, data)

        environment = _parse_environment(d.pop("environment", UNSET))

        _errors = d.pop("errors", UNSET)
        errors: list[InterfaceManifestErrorsItem] | Unset = UNSET
        if _errors is not UNSET:
            errors = []
            for errors_item_data in _errors:
                errors_item = InterfaceManifestErrorsItem.from_dict(errors_item_data)

                errors.append(errors_item)

        interface_manifest = cls(
            schema_version=schema_version,
            components=components,
            schema=schema,
            environment=environment,
            errors=errors,
        )

        interface_manifest.additional_properties = d
        return interface_manifest

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
