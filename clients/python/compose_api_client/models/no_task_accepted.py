from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.sedml_finding import SedmlFinding


T = TypeVar("T", bound="NoTaskAccepted")


@_attrs_define
class NoTaskAccepted:
    """A SED-ML archive none of whose tasks any solver accepted, with the translation's findings.

    Attributes:
        message (str):
        findings (list[SedmlFinding]):
    """

    message: str
    findings: list[SedmlFinding]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        message = self.message

        findings = []
        for findings_item_data in self.findings:
            findings_item = findings_item_data.to_dict()
            findings.append(findings_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "message": message,
            "findings": findings,
        })

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.sedml_finding import SedmlFinding  # noqa: PLC0415

        d = dict(src_dict)
        message = d.pop("message")

        findings = []
        _findings = d.pop("findings")
        for findings_item_data in _findings:
            findings_item = SedmlFinding.from_dict(findings_item_data)

            findings.append(findings_item)

        no_task_accepted = cls(
            message=message,
            findings=findings,
        )

        no_task_accepted.additional_properties = d
        return no_task_accepted

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
