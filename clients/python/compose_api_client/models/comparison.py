from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.comparison_status import ComparisonStatus
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.comparison_member import ComparisonMember
    from ..models.comparison_result_type_0 import ComparisonResultType0
    from ..models.comparison_settings import ComparisonSettings


T = TypeVar("T", bound="Comparison")


@_attrs_define
class Comparison:
    """One SED-ML task run on several solvers. `result` is filled once every member has finished: per report and
    data set label, each solver pair's score and whether it is close.

        Attributes:
            comparison_id (int):
            name (str):
            source (str):
            sedml (str):
            task (str):
            status (ComparisonStatus):
            settings (ComparisonSettings):
            members (list[ComparisonMember]):
            created_at (None | str | Unset):
            result (ComparisonResultType0 | None | Unset):
            close (bool | None | Unset): every compared data set close, every member completed
            favorite (bool | Unset): The signed-in caller starred it (`PUT /favorites/comparison/{id}`) Default: False.
    """

    comparison_id: int
    name: str
    source: str
    sedml: str
    task: str
    status: ComparisonStatus
    settings: ComparisonSettings
    members: list[ComparisonMember]
    created_at: None | str | Unset = UNSET
    result: ComparisonResultType0 | None | Unset = UNSET
    close: bool | None | Unset = UNSET
    favorite: bool | Unset = False
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.comparison_result_type_0 import ComparisonResultType0  # noqa: PLC0415

        comparison_id = self.comparison_id

        name = self.name

        source = self.source

        sedml = self.sedml

        task = self.task

        status = self.status.value

        settings = self.settings.to_dict()

        members = []
        for members_item_data in self.members:
            members_item = members_item_data.to_dict()
            members.append(members_item)

        created_at: None | str | Unset
        if isinstance(self.created_at, Unset):
            created_at = UNSET
        else:
            created_at = self.created_at

        result: dict[str, Any] | None | Unset
        if isinstance(self.result, Unset):
            result = UNSET
        elif isinstance(self.result, ComparisonResultType0):
            result = self.result.to_dict()
        else:
            result = self.result

        close: bool | None | Unset
        if isinstance(self.close, Unset):
            close = UNSET
        else:
            close = self.close

        favorite = self.favorite

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "comparison_id": comparison_id,
            "name": name,
            "source": source,
            "sedml": sedml,
            "task": task,
            "status": status,
            "settings": settings,
            "members": members,
        })
        if created_at is not UNSET:
            field_dict["created_at"] = created_at
        if result is not UNSET:
            field_dict["result"] = result
        if close is not UNSET:
            field_dict["close"] = close
        if favorite is not UNSET:
            field_dict["favorite"] = favorite

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.comparison_member import ComparisonMember  # noqa: PLC0415
        from ..models.comparison_result_type_0 import ComparisonResultType0  # noqa: PLC0415
        from ..models.comparison_settings import ComparisonSettings  # noqa: PLC0415

        d = dict(src_dict)
        comparison_id = d.pop("comparison_id")

        name = d.pop("name")

        source = d.pop("source")

        sedml = d.pop("sedml")

        task = d.pop("task")

        status = ComparisonStatus(d.pop("status"))

        settings = ComparisonSettings.from_dict(d.pop("settings"))

        members = []
        _members = d.pop("members")
        for members_item_data in _members:
            members_item = ComparisonMember.from_dict(members_item_data)

            members.append(members_item)

        def _parse_created_at(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        created_at = _parse_created_at(d.pop("created_at", UNSET))

        def _parse_result(data: object) -> ComparisonResultType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                result_type_0 = ComparisonResultType0.from_dict(data)

                return result_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ComparisonResultType0 | None | Unset, data)

        result = _parse_result(d.pop("result", UNSET))

        def _parse_close(data: object) -> bool | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(bool | None | Unset, data)

        close = _parse_close(d.pop("close", UNSET))

        favorite = d.pop("favorite", UNSET)

        comparison = cls(
            comparison_id=comparison_id,
            name=name,
            source=source,
            sedml=sedml,
            task=task,
            status=status,
            settings=settings,
            members=members,
            created_at=created_at,
            result=result,
            close=close,
            favorite=favorite,
        )

        comparison.additional_properties = d
        return comparison

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
