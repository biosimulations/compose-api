from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.address_violation import AddressViolation


T = TypeVar("T", bound="Rejection")


@_attrs_define
class Rejection:
    """A document refused at submission: the addresses it may not use, and why (`registry.validation`).

    Attributes:
        message (str):
        violations (list[AddressViolation]):
    """

    message: str
    violations: list[AddressViolation]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        message = self.message

        violations = []
        for violations_item_data in self.violations:
            violations_item = violations_item_data.to_dict()
            violations.append(violations_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "message": message,
            "violations": violations,
        })

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.address_violation import AddressViolation  # noqa: PLC0415

        d = dict(src_dict)
        message = d.pop("message")

        violations = []
        _violations = d.pop("violations")
        for violations_item_data in _violations:
            violations_item = AddressViolation.from_dict(violations_item_data)

            violations.append(violations_item)

        rejection = cls(
            message=message,
            violations=violations,
        )

        rejection.additional_properties = d
        return rejection

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
