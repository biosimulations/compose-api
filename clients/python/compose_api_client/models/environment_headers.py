from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.environment_headers_components import EnvironmentHeadersComponents
    from ..models.header_module import HeaderModule


T = TypeVar("T", bound="EnvironmentHeaders")


@_attrs_define
class EnvironmentHeaders:
    """
    Attributes:
        environment (str):
        modules (list[HeaderModule]):
        components (EnvironmentHeadersComponents): Each class's declaration, by address
    """

    environment: str
    modules: list[HeaderModule]
    components: EnvironmentHeadersComponents
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        environment = self.environment

        modules = []
        for modules_item_data in self.modules:
            modules_item = modules_item_data.to_dict()
            modules.append(modules_item)

        components = self.components.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "environment": environment,
            "modules": modules,
            "components": components,
        })

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.environment_headers_components import EnvironmentHeadersComponents  # noqa: PLC0415
        from ..models.header_module import HeaderModule  # noqa: PLC0415

        d = dict(src_dict)
        environment = d.pop("environment")

        modules = []
        _modules = d.pop("modules")
        for modules_item_data in _modules:
            modules_item = HeaderModule.from_dict(modules_item_data)

            modules.append(modules_item)

        components = EnvironmentHeadersComponents.from_dict(d.pop("components"))

        environment_headers = cls(
            environment=environment,
            modules=modules,
            components=components,
        )

        environment_headers.additional_properties = d
        return environment_headers

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
