from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.suite_run_row_drift_type_0 import SuiteRunRowDriftType0


T = TypeVar("T", bound="SuiteRunRow")


@_attrs_define
class SuiteRunRow:
    """
    Attributes:
        source (str):
        status (str):
        task (None | str | Unset):
        comparison_id (int | None | Unset):
        close (bool | None | Unset):
        close_to_references (bool | None | Unset):
        worst_label (None | str | Unset):
        worst_score (float | None | str | Unset):
        drift (None | SuiteRunRowDriftType0 | Unset):
        expected (None | str | Unset):
        failure (None | str | Unset):
        verification (None | str | Unset):
        verify_close (bool | None | Unset):
    """

    source: str
    status: str
    task: None | str | Unset = UNSET
    comparison_id: int | None | Unset = UNSET
    close: bool | None | Unset = UNSET
    close_to_references: bool | None | Unset = UNSET
    worst_label: None | str | Unset = UNSET
    worst_score: float | None | str | Unset = UNSET
    drift: None | SuiteRunRowDriftType0 | Unset = UNSET
    expected: None | str | Unset = UNSET
    failure: None | str | Unset = UNSET
    verification: None | str | Unset = UNSET
    verify_close: bool | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.suite_run_row_drift_type_0 import SuiteRunRowDriftType0  # noqa: PLC0415

        source = self.source

        status = self.status

        task: None | str | Unset
        if isinstance(self.task, Unset):
            task = UNSET
        else:
            task = self.task

        comparison_id: int | None | Unset
        if isinstance(self.comparison_id, Unset):
            comparison_id = UNSET
        else:
            comparison_id = self.comparison_id

        close: bool | None | Unset
        if isinstance(self.close, Unset):
            close = UNSET
        else:
            close = self.close

        close_to_references: bool | None | Unset
        if isinstance(self.close_to_references, Unset):
            close_to_references = UNSET
        else:
            close_to_references = self.close_to_references

        worst_label: None | str | Unset
        if isinstance(self.worst_label, Unset):
            worst_label = UNSET
        else:
            worst_label = self.worst_label

        worst_score: float | None | str | Unset
        if isinstance(self.worst_score, Unset):
            worst_score = UNSET
        else:
            worst_score = self.worst_score

        drift: dict[str, Any] | None | Unset
        if isinstance(self.drift, Unset):
            drift = UNSET
        elif isinstance(self.drift, SuiteRunRowDriftType0):
            drift = self.drift.to_dict()
        else:
            drift = self.drift

        expected: None | str | Unset
        if isinstance(self.expected, Unset):
            expected = UNSET
        else:
            expected = self.expected

        failure: None | str | Unset
        if isinstance(self.failure, Unset):
            failure = UNSET
        else:
            failure = self.failure

        verification: None | str | Unset
        if isinstance(self.verification, Unset):
            verification = UNSET
        else:
            verification = self.verification

        verify_close: bool | None | Unset
        if isinstance(self.verify_close, Unset):
            verify_close = UNSET
        else:
            verify_close = self.verify_close

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "source": source,
            "status": status,
        })
        if task is not UNSET:
            field_dict["task"] = task
        if comparison_id is not UNSET:
            field_dict["comparison_id"] = comparison_id
        if close is not UNSET:
            field_dict["close"] = close
        if close_to_references is not UNSET:
            field_dict["close_to_references"] = close_to_references
        if worst_label is not UNSET:
            field_dict["worst_label"] = worst_label
        if worst_score is not UNSET:
            field_dict["worst_score"] = worst_score
        if drift is not UNSET:
            field_dict["drift"] = drift
        if expected is not UNSET:
            field_dict["expected"] = expected
        if failure is not UNSET:
            field_dict["failure"] = failure
        if verification is not UNSET:
            field_dict["verification"] = verification
        if verify_close is not UNSET:
            field_dict["verify_close"] = verify_close

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.suite_run_row_drift_type_0 import SuiteRunRowDriftType0  # noqa: PLC0415

        d = dict(src_dict)
        source = d.pop("source")

        status = d.pop("status")

        def _parse_task(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        task = _parse_task(d.pop("task", UNSET))

        def _parse_comparison_id(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        comparison_id = _parse_comparison_id(d.pop("comparison_id", UNSET))

        def _parse_close(data: object) -> bool | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(bool | None | Unset, data)

        close = _parse_close(d.pop("close", UNSET))

        def _parse_close_to_references(data: object) -> bool | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(bool | None | Unset, data)

        close_to_references = _parse_close_to_references(d.pop("close_to_references", UNSET))

        def _parse_worst_label(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        worst_label = _parse_worst_label(d.pop("worst_label", UNSET))

        def _parse_worst_score(data: object) -> float | None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | str | Unset, data)

        worst_score = _parse_worst_score(d.pop("worst_score", UNSET))

        def _parse_drift(data: object) -> None | SuiteRunRowDriftType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                drift_type_0 = SuiteRunRowDriftType0.from_dict(data)

                return drift_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | SuiteRunRowDriftType0 | Unset, data)

        drift = _parse_drift(d.pop("drift", UNSET))

        def _parse_expected(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        expected = _parse_expected(d.pop("expected", UNSET))

        def _parse_failure(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        failure = _parse_failure(d.pop("failure", UNSET))

        def _parse_verification(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        verification = _parse_verification(d.pop("verification", UNSET))

        def _parse_verify_close(data: object) -> bool | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(bool | None | Unset, data)

        verify_close = _parse_verify_close(d.pop("verify_close", UNSET))

        suite_run_row = cls(
            source=source,
            status=status,
            task=task,
            comparison_id=comparison_id,
            close=close,
            close_to_references=close_to_references,
            worst_label=worst_label,
            worst_score=worst_score,
            drift=drift,
            expected=expected,
            failure=failure,
            verification=verification,
            verify_close=verify_close,
        )

        suite_run_row.additional_properties = d
        return suite_run_row

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
