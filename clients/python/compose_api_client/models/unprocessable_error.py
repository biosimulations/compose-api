from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.validation_issue import ValidationIssue


T = TypeVar("T", bound="UnprocessableError")


@_attrs_define
class UnprocessableError:
    """A 422 a route raises itself (a message), or FastAPI's validation of the request (a list of issues).

    Attributes:
        detail (list[ValidationIssue] | str):
    """

    detail: list[ValidationIssue] | str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        detail: list[dict[str, Any]] | str
        if isinstance(self.detail, list):
            detail = []
            for detail_type_1_item_data in self.detail:
                detail_type_1_item = detail_type_1_item_data.to_dict()
                detail.append(detail_type_1_item)

        else:
            detail = self.detail

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "detail": detail,
        })

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.validation_issue import ValidationIssue  # noqa: PLC0415

        d = dict(src_dict)

        def _parse_detail(data: object) -> list[ValidationIssue] | str:
            try:
                if not isinstance(data, list):
                    raise TypeError()
                detail_type_1 = []
                _detail_type_1 = data
                for detail_type_1_item_data in _detail_type_1:
                    detail_type_1_item = ValidationIssue.from_dict(detail_type_1_item_data)

                    detail_type_1.append(detail_type_1_item)

                return detail_type_1
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[ValidationIssue] | str, data)

        detail = _parse_detail(d.pop("detail"))

        unprocessable_error = cls(
            detail=detail,
        )

        unprocessable_error.additional_properties = d
        return unprocessable_error

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
