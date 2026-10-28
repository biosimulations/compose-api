from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.no_task_accepted import NoTaskAccepted
    from ..models.rejection import Rejection


T = TypeVar("T", bound="SedmlRunError")


@_attrs_define
class SedmlRunError:
    """A SED-ML run refused: a message, the refused addresses, or the findings when no task was accepted.

    Attributes:
        detail (NoTaskAccepted | Rejection | str):
    """

    detail: NoTaskAccepted | Rejection | str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.no_task_accepted import NoTaskAccepted  # noqa: PLC0415
        from ..models.rejection import Rejection  # noqa: PLC0415

        detail: dict[str, Any] | str
        if isinstance(self.detail, Rejection):
            detail = self.detail.to_dict()
        elif isinstance(self.detail, NoTaskAccepted):
            detail = self.detail.to_dict()
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
        from ..models.no_task_accepted import NoTaskAccepted  # noqa: PLC0415
        from ..models.rejection import Rejection  # noqa: PLC0415

        d = dict(src_dict)

        def _parse_detail(data: object) -> NoTaskAccepted | Rejection | str:
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                detail_type_1 = Rejection.from_dict(data)

                return detail_type_1
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                detail_type_2 = NoTaskAccepted.from_dict(data)

                return detail_type_2
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(NoTaskAccepted | Rejection | str, data)

        detail = _parse_detail(d.pop("detail"))

        sedml_run_error = cls(
            detail=detail,
        )

        sedml_run_error.additional_properties = d
        return sedml_run_error

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
