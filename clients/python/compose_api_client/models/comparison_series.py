from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.comparison_series_references import ComparisonSeriesReferences
    from ..models.comparison_series_solvers import ComparisonSeriesSolvers


T = TypeVar("T", bound="ComparisonSeries")


@_attrs_define
class ComparisonSeries:
    """One report's columns from each member (by solver) and each reference (by origin), for overlays.

    Attributes:
        report (str):
        labels (list[str]):
        solvers (ComparisonSeriesSolvers):
        references (ComparisonSeriesReferences):
    """

    report: str
    labels: list[str]
    solvers: ComparisonSeriesSolvers
    references: ComparisonSeriesReferences
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        report = self.report

        labels = self.labels

        solvers = self.solvers.to_dict()

        references = self.references.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "report": report,
            "labels": labels,
            "solvers": solvers,
            "references": references,
        })

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.comparison_series_references import ComparisonSeriesReferences  # noqa: PLC0415
        from ..models.comparison_series_solvers import ComparisonSeriesSolvers  # noqa: PLC0415

        d = dict(src_dict)
        report = d.pop("report")

        labels = cast(list[str], d.pop("labels"))

        solvers = ComparisonSeriesSolvers.from_dict(d.pop("solvers"))

        references = ComparisonSeriesReferences.from_dict(d.pop("references"))

        comparison_series = cls(
            report=report,
            labels=labels,
            solvers=solvers,
            references=references,
        )

        comparison_series.additional_properties = d
        return comparison_series

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
