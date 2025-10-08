from collections.abc import Mapping
from typing import Any, TypeVar, Optional, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.bi_graph_compute_type import BiGraphComputeType


T = TypeVar("T", bound="BiGraphStep")


@_attrs_define
class BiGraphStep:
    """
    Attributes:
        database_id (int):
        module (str):
        name (str):
        compute_type (BiGraphComputeType):
        inputs (str):
        outputs (str):
    """

    database_id: int
    module: str
    name: str
    compute_type: BiGraphComputeType
    inputs: str
    outputs: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        database_id = self.database_id

        module = self.module

        name = self.name

        compute_type = self.compute_type.value

        inputs = self.inputs

        outputs = self.outputs

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "database_id": database_id,
            "module": module,
            "name": name,
            "compute_type": compute_type,
            "inputs": inputs,
            "outputs": outputs,
        })

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        database_id = d.pop("database_id")

        module = d.pop("module")

        name = d.pop("name")

        compute_type = BiGraphComputeType(d.pop("compute_type"))

        inputs = d.pop("inputs")

        outputs = d.pop("outputs")

        bi_graph_step = cls(
            database_id=database_id,
            module=module,
            name=name,
            compute_type=compute_type,
            inputs=inputs,
            outputs=outputs,
        )

        bi_graph_step.additional_properties = d
        return bi_graph_step

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
