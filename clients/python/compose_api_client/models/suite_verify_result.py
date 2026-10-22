from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="SuiteVerifyResult")


@_attrs_define
class SuiteVerifyResult:
    """Verifications queued for a suite run's comparisons.

    Attributes:
        queued (list[int]): comparisons a verification was queued for
        already (list[int]): comparisons with a verification already queued or running
        running (int): comparisons still running, not yet looked at
    """

    queued: list[int]
    already: list[int]
    running: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        queued = self.queued

        already = self.already

        running = self.running

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "queued": queued,
            "already": already,
            "running": running,
        })

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        queued = cast(list[int], d.pop("queued"))

        already = cast(list[int], d.pop("already"))

        running = d.pop("running")

        suite_verify_result = cls(
            queued=queued,
            already=already,
            running=running,
        )

        suite_verify_result.additional_properties = d
        return suite_verify_result

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
