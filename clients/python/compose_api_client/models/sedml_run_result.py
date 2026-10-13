from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.comparison import Comparison
    from ..models.sedml_finding import SedmlFinding


T = TypeVar("T", bound="SedmlRunResult")


@_attrs_define
class SedmlRunResult:
    """
    Attributes:
        comparisons (list[Comparison]):
        findings (list[SedmlFinding]):
    """

    comparisons: list[Comparison]
    findings: list[SedmlFinding]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        comparisons = []
        for comparisons_item_data in self.comparisons:
            comparisons_item = comparisons_item_data.to_dict()
            comparisons.append(comparisons_item)

        findings = []
        for findings_item_data in self.findings:
            findings_item = findings_item_data.to_dict()
            findings.append(findings_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "comparisons": comparisons,
            "findings": findings,
        })

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.comparison import Comparison  # noqa: PLC0415
        from ..models.sedml_finding import SedmlFinding  # noqa: PLC0415

        d = dict(src_dict)
        comparisons = []
        _comparisons = d.pop("comparisons")
        for comparisons_item_data in _comparisons:
            comparisons_item = Comparison.from_dict(comparisons_item_data)

            comparisons.append(comparisons_item)

        findings = []
        _findings = d.pop("findings")
        for findings_item_data in _findings:
            findings_item = SedmlFinding.from_dict(findings_item_data)

            findings.append(findings_item)

        sedml_run_result = cls(
            comparisons=comparisons,
            findings=findings,
        )

        sedml_run_result.additional_properties = d
        return sedml_run_result

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
