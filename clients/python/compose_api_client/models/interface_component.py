from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.entry_ref import EntryRef
    from ..models.interface_component_config_schema import InterfaceComponentConfigSchema
    from ..models.interface_component_inputs_type_0 import InterfaceComponentInputsType0
    from ..models.interface_component_outputs_type_0 import InterfaceComponentOutputsType0


T = TypeVar("T", bound="InterfaceComponent")


@_attrs_define
class InterfaceComponent:
    """One step or process class, as `pbg-interfaces/1` describes it; unknown keys pass through.

    Attributes:
        name (str):
        kind (str):
        address (str):
        module (None | str | Unset):
        description (None | str | Unset):
        config_schema (InterfaceComponentConfigSchema | Unset):
        inputs (InterfaceComponentInputsType0 | None | Unset):
        outputs (InterfaceComponentOutputsType0 | None | Unset):
        dynamic_ports (bool | Unset):  Default: False.
        registry_entry (EntryRef | None | Unset):
    """

    name: str
    kind: str
    address: str
    module: None | str | Unset = UNSET
    description: None | str | Unset = UNSET
    config_schema: InterfaceComponentConfigSchema | Unset = UNSET
    inputs: InterfaceComponentInputsType0 | None | Unset = UNSET
    outputs: InterfaceComponentOutputsType0 | None | Unset = UNSET
    dynamic_ports: bool | Unset = False
    registry_entry: EntryRef | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.entry_ref import EntryRef  # noqa: PLC0415
        from ..models.interface_component_inputs_type_0 import InterfaceComponentInputsType0  # noqa: PLC0415
        from ..models.interface_component_outputs_type_0 import InterfaceComponentOutputsType0  # noqa: PLC0415

        name = self.name

        kind = self.kind

        address = self.address

        module: None | str | Unset
        if isinstance(self.module, Unset):
            module = UNSET
        else:
            module = self.module

        description: None | str | Unset
        if isinstance(self.description, Unset):
            description = UNSET
        else:
            description = self.description

        config_schema: dict[str, Any] | Unset = UNSET
        if not isinstance(self.config_schema, Unset):
            config_schema = self.config_schema.to_dict()

        inputs: dict[str, Any] | None | Unset
        if isinstance(self.inputs, Unset):
            inputs = UNSET
        elif isinstance(self.inputs, InterfaceComponentInputsType0):
            inputs = self.inputs.to_dict()
        else:
            inputs = self.inputs

        outputs: dict[str, Any] | None | Unset
        if isinstance(self.outputs, Unset):
            outputs = UNSET
        elif isinstance(self.outputs, InterfaceComponentOutputsType0):
            outputs = self.outputs.to_dict()
        else:
            outputs = self.outputs

        dynamic_ports = self.dynamic_ports

        registry_entry: dict[str, Any] | None | Unset
        if isinstance(self.registry_entry, Unset):
            registry_entry = UNSET
        elif isinstance(self.registry_entry, EntryRef):
            registry_entry = self.registry_entry.to_dict()
        else:
            registry_entry = self.registry_entry

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "name": name,
            "kind": kind,
            "address": address,
        })
        if module is not UNSET:
            field_dict["module"] = module
        if description is not UNSET:
            field_dict["description"] = description
        if config_schema is not UNSET:
            field_dict["config_schema"] = config_schema
        if inputs is not UNSET:
            field_dict["inputs"] = inputs
        if outputs is not UNSET:
            field_dict["outputs"] = outputs
        if dynamic_ports is not UNSET:
            field_dict["dynamic_ports"] = dynamic_ports
        if registry_entry is not UNSET:
            field_dict["registry_entry"] = registry_entry

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.entry_ref import EntryRef  # noqa: PLC0415
        from ..models.interface_component_config_schema import InterfaceComponentConfigSchema  # noqa: PLC0415
        from ..models.interface_component_inputs_type_0 import InterfaceComponentInputsType0  # noqa: PLC0415
        from ..models.interface_component_outputs_type_0 import InterfaceComponentOutputsType0  # noqa: PLC0415

        d = dict(src_dict)
        name = d.pop("name")

        kind = d.pop("kind")

        address = d.pop("address")

        def _parse_module(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        module = _parse_module(d.pop("module", UNSET))

        def _parse_description(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        description = _parse_description(d.pop("description", UNSET))

        _config_schema = d.pop("config_schema", UNSET)
        config_schema: InterfaceComponentConfigSchema | Unset
        if isinstance(_config_schema, Unset):
            config_schema = UNSET
        else:
            config_schema = InterfaceComponentConfigSchema.from_dict(_config_schema)

        def _parse_inputs(data: object) -> InterfaceComponentInputsType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                inputs_type_0 = InterfaceComponentInputsType0.from_dict(data)

                return inputs_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(InterfaceComponentInputsType0 | None | Unset, data)

        inputs = _parse_inputs(d.pop("inputs", UNSET))

        def _parse_outputs(data: object) -> InterfaceComponentOutputsType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                outputs_type_0 = InterfaceComponentOutputsType0.from_dict(data)

                return outputs_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(InterfaceComponentOutputsType0 | None | Unset, data)

        outputs = _parse_outputs(d.pop("outputs", UNSET))

        dynamic_ports = d.pop("dynamic_ports", UNSET)

        def _parse_registry_entry(data: object) -> EntryRef | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                registry_entry_type_0 = EntryRef.from_dict(data)

                return registry_entry_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(EntryRef | None | Unset, data)

        registry_entry = _parse_registry_entry(d.pop("registry_entry", UNSET))

        interface_component = cls(
            name=name,
            kind=kind,
            address=address,
            module=module,
            description=description,
            config_schema=config_schema,
            inputs=inputs,
            outputs=outputs,
            dynamic_ports=dynamic_ports,
            registry_entry=registry_entry,
        )

        interface_component.additional_properties = d
        return interface_component

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
