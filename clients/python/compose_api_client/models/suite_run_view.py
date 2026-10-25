from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.suite_run_row import SuiteRunRow
    from ..models.suite_run_view_environment_versions import SuiteRunViewEnvironmentVersions
    from ..models.suite_run_view_summary import SuiteRunViewSummary


T = TypeVar("T", bound="SuiteRunView")


@_attrs_define
class SuiteRunView:
    """
    Attributes:
        suite (str):
        number (int):
        created_at (None | str):
        status (str):
        baseline (int | None):
        rows (list[SuiteRunRow]):
        summary (SuiteRunViewSummary):
        environment_versions (SuiteRunViewEnvironmentVersions | Unset): The environment versions its runs use,
            {environment: number}
    """

    suite: str
    number: int
    created_at: None | str
    status: str
    baseline: int | None
    rows: list[SuiteRunRow]
    summary: SuiteRunViewSummary
    environment_versions: SuiteRunViewEnvironmentVersions | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        suite = self.suite

        number = self.number

        created_at: None | str
        created_at = self.created_at

        status = self.status

        baseline: int | None
        baseline = self.baseline

        rows = []
        for rows_item_data in self.rows:
            rows_item = rows_item_data.to_dict()
            rows.append(rows_item)

        summary = self.summary.to_dict()

        environment_versions: dict[str, Any] | Unset = UNSET
        if not isinstance(self.environment_versions, Unset):
            environment_versions = self.environment_versions.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "suite": suite,
            "number": number,
            "created_at": created_at,
            "status": status,
            "baseline": baseline,
            "rows": rows,
            "summary": summary,
        })
        if environment_versions is not UNSET:
            field_dict["environment_versions"] = environment_versions

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.suite_run_row import SuiteRunRow  # noqa: PLC0415
        from ..models.suite_run_view_environment_versions import SuiteRunViewEnvironmentVersions  # noqa: PLC0415
        from ..models.suite_run_view_summary import SuiteRunViewSummary  # noqa: PLC0415

        d = dict(src_dict)
        suite = d.pop("suite")

        number = d.pop("number")

        def _parse_created_at(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        created_at = _parse_created_at(d.pop("created_at"))

        status = d.pop("status")

        def _parse_baseline(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        baseline = _parse_baseline(d.pop("baseline"))

        rows = []
        _rows = d.pop("rows")
        for rows_item_data in _rows:
            rows_item = SuiteRunRow.from_dict(rows_item_data)

            rows.append(rows_item)

        summary = SuiteRunViewSummary.from_dict(d.pop("summary"))

        _environment_versions = d.pop("environment_versions", UNSET)
        environment_versions: SuiteRunViewEnvironmentVersions | Unset
        if isinstance(_environment_versions, Unset):
            environment_versions = UNSET
        else:
            environment_versions = SuiteRunViewEnvironmentVersions.from_dict(_environment_versions)

        suite_run_view = cls(
            suite=suite,
            number=number,
            created_at=created_at,
            status=status,
            baseline=baseline,
            rows=rows,
            summary=summary,
            environment_versions=environment_versions,
        )

        suite_run_view.additional_properties = d
        return suite_run_view

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
