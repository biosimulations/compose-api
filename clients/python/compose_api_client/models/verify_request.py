from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="VerifyRequest")


@_attrs_define
class VerifyRequest:
    """Which BioSimulators simulators to verify a comparison with (docs/plan-verify-oracle.md, V4).

    Attributes:
        simulators (list[str] | None | Unset): `name` or `name:version`; by default the service's (amici, copasi,
            pysces, tellurium, vcell)
    """

    simulators: list[str] | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        simulators: list[str] | None | Unset
        if isinstance(self.simulators, Unset):
            simulators = UNSET
        elif isinstance(self.simulators, list):
            simulators = self.simulators

        else:
            simulators = self.simulators

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if simulators is not UNSET:
            field_dict["simulators"] = simulators

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_simulators(data: object) -> list[str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                simulators_type_0 = cast(list[str], data)

                return simulators_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[str] | None | Unset, data)

        simulators = _parse_simulators(d.pop("simulators", UNSET))

        verify_request = cls(
            simulators=simulators,
        )

        verify_request.additional_properties = d
        return verify_request

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
