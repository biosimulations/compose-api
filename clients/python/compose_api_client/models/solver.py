from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="Solver")


@_attrs_define
class Solver:
    """
    Attributes:
        id (str):
        name (str):
        role (Literal['TimeCourseSolver']):
        environment (str):
        address (str):
        algorithms (list[str]): KiSAO terms it implements, its default first
        provides (list[str] | Unset):
    """

    id: str
    name: str
    role: Literal["TimeCourseSolver"]
    environment: str
    address: str
    algorithms: list[str]
    provides: list[str] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = self.id

        name = self.name

        role = self.role

        environment = self.environment

        address = self.address

        algorithms = self.algorithms

        provides: list[str] | Unset = UNSET
        if not isinstance(self.provides, Unset):
            provides = self.provides

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "id": id,
            "name": name,
            "role": role,
            "environment": environment,
            "address": address,
            "algorithms": algorithms,
        })
        if provides is not UNSET:
            field_dict["provides"] = provides

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = d.pop("id")

        name = d.pop("name")

        role = cast(Literal["TimeCourseSolver"], d.pop("role"))
        if role != "TimeCourseSolver":
            raise ValueError(f"role must match const 'TimeCourseSolver', got '{role}'")

        environment = d.pop("environment")

        address = d.pop("address")

        algorithms = cast(list[str], d.pop("algorithms"))

        provides = cast(list[str], d.pop("provides", UNSET))

        solver = cls(
            id=id,
            name=name,
            role=role,
            environment=environment,
            address=address,
            algorithms=algorithms,
            provides=provides,
        )

        solver.additional_properties = d
        return solver

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
