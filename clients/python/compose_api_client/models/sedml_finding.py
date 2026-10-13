from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.sedml_finding_severity import SedmlFindingSeverity
from ..types import UNSET, Unset

T = TypeVar("T", bound="SedmlFinding")


@_attrs_define
class SedmlFinding:
    """A finding of the translation (process-bigraph-lang's `X4xx`) or of the checker on a solver's instance.

    Attributes:
        severity (SedmlFindingSeverity):
        code (str):
        message (str):
        solver (None | str | Unset):
        task (None | str | Unset):
        path (None | str | Unset):
    """

    severity: SedmlFindingSeverity
    code: str
    message: str
    solver: None | str | Unset = UNSET
    task: None | str | Unset = UNSET
    path: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        severity = self.severity.value

        code = self.code

        message = self.message

        solver: None | str | Unset
        if isinstance(self.solver, Unset):
            solver = UNSET
        else:
            solver = self.solver

        task: None | str | Unset
        if isinstance(self.task, Unset):
            task = UNSET
        else:
            task = self.task

        path: None | str | Unset
        if isinstance(self.path, Unset):
            path = UNSET
        else:
            path = self.path

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "severity": severity,
            "code": code,
            "message": message,
        })
        if solver is not UNSET:
            field_dict["solver"] = solver
        if task is not UNSET:
            field_dict["task"] = task
        if path is not UNSET:
            field_dict["path"] = path

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        severity = SedmlFindingSeverity(d.pop("severity"))

        code = d.pop("code")

        message = d.pop("message")

        def _parse_solver(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        solver = _parse_solver(d.pop("solver", UNSET))

        def _parse_task(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        task = _parse_task(d.pop("task", UNSET))

        def _parse_path(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        path = _parse_path(d.pop("path", UNSET))

        sedml_finding = cls(
            severity=severity,
            code=code,
            message=message,
            solver=solver,
            task=task,
            path=path,
        )

        sedml_finding.additional_properties = d
        return sedml_finding

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
