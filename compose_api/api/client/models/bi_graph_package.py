from collections.abc import Mapping
from typing import Any, TypeVar, Optional, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.package_type import PackageType
from typing import cast
from typing import cast, Union

if TYPE_CHECKING:
    from ..models.bi_graph_process import BiGraphProcess
    from ..models.bi_graph_step import BiGraphStep


T = TypeVar("T", bound="BiGraphPackage")


@_attrs_define
class BiGraphPackage:
    """
    Attributes:
        database_id (int):
        package_type (PackageType):
        source_uri (list[Any]):
        name (str):
        steps (list['BiGraphStep']):
        processes (list['BiGraphProcess']):
    """

    database_id: int
    package_type: PackageType
    source_uri: list[Any]
    name: str
    steps: list["BiGraphStep"]
    processes: list["BiGraphProcess"]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.bi_graph_process import BiGraphProcess
        from ..models.bi_graph_step import BiGraphStep

        database_id = self.database_id

        package_type = self.package_type.value

        source_uri = []
        for componentsschemas_parse_result_item_data in self.source_uri:
            componentsschemas_parse_result_item: Any
            componentsschemas_parse_result_item = componentsschemas_parse_result_item_data
            source_uri.append(componentsschemas_parse_result_item)

        name = self.name

        steps = []
        for steps_item_data in self.steps:
            steps_item = steps_item_data.to_dict()
            steps.append(steps_item)

        processes = []
        for processes_item_data in self.processes:
            processes_item = processes_item_data.to_dict()
            processes.append(processes_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "database_id": database_id,
            "package_type": package_type,
            "source_uri": source_uri,
            "name": name,
            "steps": steps,
            "processes": processes,
        })

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.bi_graph_process import BiGraphProcess
        from ..models.bi_graph_step import BiGraphStep

        d = dict(src_dict)
        database_id = d.pop("database_id")

        package_type = PackageType(d.pop("package_type"))

        source_uri = []
        _source_uri = d.pop("source_uri")
        for componentsschemas_parse_result_item_data in _source_uri:

            def _parse_componentsschemas_parse_result_item(data: object) -> Any:
                return cast(Any, data)

            componentsschemas_parse_result_item = _parse_componentsschemas_parse_result_item(
                componentsschemas_parse_result_item_data
            )

            source_uri.append(componentsschemas_parse_result_item)

        name = d.pop("name")

        steps = []
        _steps = d.pop("steps")
        for steps_item_data in _steps:
            steps_item = BiGraphStep.from_dict(steps_item_data)

            steps.append(steps_item)

        processes = []
        _processes = d.pop("processes")
        for processes_item_data in _processes:
            processes_item = BiGraphProcess.from_dict(processes_item_data)

            processes.append(processes_item)

        bi_graph_package = cls(
            database_id=database_id,
            package_type=package_type,
            source_uri=source_uri,
            name=name,
            steps=steps,
            processes=processes,
        )

        bi_graph_package.additional_properties = d
        return bi_graph_package

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
