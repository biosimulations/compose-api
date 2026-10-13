from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.expected_failure import ExpectedFailure
    from ..models.tolerances import Tolerances


T = TypeVar("T", bound="Suite")


@_attrs_define
class Suite:
    """
    Attributes:
        name (str):
        description (str):
        sources (list[str]):
        solvers (list[str] | None | Unset):
        tolerances (Tolerances | Unset): The platform's closeness score: close when `max |a-b| / (atol + rtol*|b|) < 1`,
            with
            `atol = max(abs_tol_min, max|a|*abs_tol_scale, max|b|*abs_tol_scale)` (docs/plan-sedml.md, D4).
        baseline (int | None | Unset): the accepted suite run that later runs are compared with
        expected (list[ExpectedFailure] | Unset):
    """

    name: str
    description: str
    sources: list[str]
    solvers: list[str] | None | Unset = UNSET
    tolerances: Tolerances | Unset = UNSET
    baseline: int | None | Unset = UNSET
    expected: list[ExpectedFailure] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        name = self.name

        description = self.description

        sources = self.sources

        solvers: list[str] | None | Unset
        if isinstance(self.solvers, Unset):
            solvers = UNSET
        elif isinstance(self.solvers, list):
            solvers = self.solvers

        else:
            solvers = self.solvers

        tolerances: dict[str, Any] | Unset = UNSET
        if not isinstance(self.tolerances, Unset):
            tolerances = self.tolerances.to_dict()

        baseline: int | None | Unset
        if isinstance(self.baseline, Unset):
            baseline = UNSET
        else:
            baseline = self.baseline

        expected: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.expected, Unset):
            expected = []
            for expected_item_data in self.expected:
                expected_item = expected_item_data.to_dict()
                expected.append(expected_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "name": name,
            "description": description,
            "sources": sources,
        })
        if solvers is not UNSET:
            field_dict["solvers"] = solvers
        if tolerances is not UNSET:
            field_dict["tolerances"] = tolerances
        if baseline is not UNSET:
            field_dict["baseline"] = baseline
        if expected is not UNSET:
            field_dict["expected"] = expected

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.expected_failure import ExpectedFailure  # noqa: PLC0415
        from ..models.tolerances import Tolerances  # noqa: PLC0415

        d = dict(src_dict)
        name = d.pop("name")

        description = d.pop("description")

        sources = cast(list[str], d.pop("sources"))

        def _parse_solvers(data: object) -> list[str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                solvers_type_0 = cast(list[str], data)

                return solvers_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[str] | None | Unset, data)

        solvers = _parse_solvers(d.pop("solvers", UNSET))

        _tolerances = d.pop("tolerances", UNSET)
        tolerances: Tolerances | Unset
        if isinstance(_tolerances, Unset):
            tolerances = UNSET
        else:
            tolerances = Tolerances.from_dict(_tolerances)

        def _parse_baseline(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        baseline = _parse_baseline(d.pop("baseline", UNSET))

        _expected = d.pop("expected", UNSET)
        expected: list[ExpectedFailure] | Unset = UNSET
        if _expected is not UNSET:
            expected = []
            for expected_item_data in _expected:
                expected_item = ExpectedFailure.from_dict(expected_item_data)

                expected.append(expected_item)

        suite = cls(
            name=name,
            description=description,
            sources=sources,
            solvers=solvers,
            tolerances=tolerances,
            baseline=baseline,
            expected=expected,
        )

        suite.additional_properties = d
        return suite

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
