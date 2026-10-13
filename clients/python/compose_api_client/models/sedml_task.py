from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="SedmlTask")


@_attrs_define
class SedmlTask:
    """One SED-ML task: its translation's template text, the solvers that accept it, and its reports and plots.

    Attributes:
        sedml (str):
        task (str):
        name (str):
        template (str):
        solvers (list[str]): the solvers whose instance compiled
        refused (list[str] | Unset): the solvers refused by an error finding
        reports (list[str] | Unset):
        plots (list[str] | Unset):
    """

    sedml: str
    task: str
    name: str
    template: str
    solvers: list[str]
    refused: list[str] | Unset = UNSET
    reports: list[str] | Unset = UNSET
    plots: list[str] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        sedml = self.sedml

        task = self.task

        name = self.name

        template = self.template

        solvers = self.solvers

        refused: list[str] | Unset = UNSET
        if not isinstance(self.refused, Unset):
            refused = self.refused

        reports: list[str] | Unset = UNSET
        if not isinstance(self.reports, Unset):
            reports = self.reports

        plots: list[str] | Unset = UNSET
        if not isinstance(self.plots, Unset):
            plots = self.plots

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "sedml": sedml,
            "task": task,
            "name": name,
            "template": template,
            "solvers": solvers,
        })
        if refused is not UNSET:
            field_dict["refused"] = refused
        if reports is not UNSET:
            field_dict["reports"] = reports
        if plots is not UNSET:
            field_dict["plots"] = plots

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        sedml = d.pop("sedml")

        task = d.pop("task")

        name = d.pop("name")

        template = d.pop("template")

        solvers = cast(list[str], d.pop("solvers"))

        refused = cast(list[str], d.pop("refused", UNSET))

        reports = cast(list[str], d.pop("reports", UNSET))

        plots = cast(list[str], d.pop("plots", UNSET))

        sedml_task = cls(
            sedml=sedml,
            task=task,
            name=name,
            template=template,
            solvers=solvers,
            refused=refused,
            reports=reports,
            plots=plots,
        )

        sedml_task.additional_properties = d
        return sedml_task

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
