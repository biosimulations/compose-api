from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="AddressViolation")


@_attrs_define
class AddressViolation:
    """
    Attributes:
        document (str):
        address (str):
        reason (str):
        always_rejected (bool | Unset):  Default: False.
    """

    document: str
    address: str
    reason: str
    always_rejected: bool | Unset = False
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        document = self.document

        address = self.address

        reason = self.reason

        always_rejected = self.always_rejected

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "document": document,
            "address": address,
            "reason": reason,
        })
        if always_rejected is not UNSET:
            field_dict["always_rejected"] = always_rejected

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        document = d.pop("document")

        address = d.pop("address")

        reason = d.pop("reason")

        always_rejected = d.pop("always_rejected", UNSET)

        address_violation = cls(
            document=document,
            address=address,
            reason=reason,
            always_rejected=always_rejected,
        )

        address_violation.additional_properties = d
        return address_violation

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
