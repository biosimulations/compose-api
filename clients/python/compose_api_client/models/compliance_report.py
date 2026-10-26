from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.compliance_report_findings_item import ComplianceReportFindingsItem
    from ..models.entry_compliance import EntryCompliance


T = TypeVar("T", bound="ComplianceReport")


@_attrs_define
class ComplianceReport:
    """What certifies a version's entries (docs/plan-environment-composition.md, step 5): their cases' runs there,
    and the generic checks over its components. A component that fails a check is refused in this version (`refused`),
    whatever its entry's level.

        Attributes:
            environment (str):
            number (int):
            entries (list[EntryCompliance] | Unset):
            findings (list[ComplianceReportFindingsItem] | Unset):
            refused (list[str] | Unset): Components a generic check failed
    """

    environment: str
    number: int
    entries: list[EntryCompliance] | Unset = UNSET
    findings: list[ComplianceReportFindingsItem] | Unset = UNSET
    refused: list[str] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        environment = self.environment

        number = self.number

        entries: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.entries, Unset):
            entries = []
            for entries_item_data in self.entries:
                entries_item = entries_item_data.to_dict()
                entries.append(entries_item)

        findings: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.findings, Unset):
            findings = []
            for findings_item_data in self.findings:
                findings_item = findings_item_data.to_dict()
                findings.append(findings_item)

        refused: list[str] | Unset = UNSET
        if not isinstance(self.refused, Unset):
            refused = self.refused

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "environment": environment,
            "number": number,
        })
        if entries is not UNSET:
            field_dict["entries"] = entries
        if findings is not UNSET:
            field_dict["findings"] = findings
        if refused is not UNSET:
            field_dict["refused"] = refused

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.compliance_report_findings_item import ComplianceReportFindingsItem  # noqa: PLC0415
        from ..models.entry_compliance import EntryCompliance  # noqa: PLC0415

        d = dict(src_dict)
        environment = d.pop("environment")

        number = d.pop("number")

        _entries = d.pop("entries", UNSET)
        entries: list[EntryCompliance] | Unset = UNSET
        if _entries is not UNSET:
            entries = []
            for entries_item_data in _entries:
                entries_item = EntryCompliance.from_dict(entries_item_data)

                entries.append(entries_item)

        _findings = d.pop("findings", UNSET)
        findings: list[ComplianceReportFindingsItem] | Unset = UNSET
        if _findings is not UNSET:
            findings = []
            for findings_item_data in _findings:
                findings_item = ComplianceReportFindingsItem.from_dict(findings_item_data)

                findings.append(findings_item)

        refused = cast(list[str], d.pop("refused", UNSET))

        compliance_report = cls(
            environment=environment,
            number=number,
            entries=entries,
            findings=findings,
            refused=refused,
        )

        compliance_report.additional_properties = d
        return compliance_report

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
