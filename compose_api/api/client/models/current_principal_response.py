from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="CurrentPrincipalResponse")


@_attrs_define
class CurrentPrincipalResponse:
    """
    Attributes:
        issuer (str):
        subject (str):
        audience (list[str]):
        roles (list[str]):
        scopes (list[str]):
        permissions (list[str]):
    """

    issuer: str
    subject: str
    audience: list[str]
    roles: list[str]
    scopes: list[str]
    permissions: list[str]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        issuer = self.issuer

        subject = self.subject

        audience = self.audience

        roles = self.roles

        scopes = self.scopes

        permissions = self.permissions

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "issuer": issuer,
            "subject": subject,
            "audience": audience,
            "roles": roles,
            "scopes": scopes,
            "permissions": permissions,
        })

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        issuer = d.pop("issuer")

        subject = d.pop("subject")

        audience = cast(list[str], d.pop("audience"))

        roles = cast(list[str], d.pop("roles"))

        scopes = cast(list[str], d.pop("scopes"))

        permissions = cast(list[str], d.pop("permissions"))

        current_principal_response = cls(
            issuer=issuer,
            subject=subject,
            audience=audience,
            roles=roles,
            scopes=scopes,
            permissions=permissions,
        )

        current_principal_response.additional_properties = d
        return current_principal_response

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
