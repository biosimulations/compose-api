from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.environment_export_files import EnvironmentExportFiles


T = TypeVar("T", bound="EnvironmentExport")


@_attrs_define
class EnvironmentExport:
    """A version's environment as files to recreate it with locally (docs/plan-environment-composition.md, C2a):
    `pixi` (pixi.toml and pixi.lock, `pixi install --frozen`) for a composed version, `requirements` (the uv lock,
    `uv pip install -r`) for a shared one.

        Attributes:
            environment (str):
            number (int):
            format_ (str):
            files (EnvironmentExportFiles): File name -> contents
    """

    environment: str
    number: int
    format_: str
    files: EnvironmentExportFiles
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        environment = self.environment

        number = self.number

        format_ = self.format_

        files = self.files.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "environment": environment,
            "number": number,
            "format": format_,
            "files": files,
        })

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.environment_export_files import EnvironmentExportFiles  # noqa: PLC0415

        d = dict(src_dict)
        environment = d.pop("environment")

        number = d.pop("number")

        format_ = d.pop("format")

        files = EnvironmentExportFiles.from_dict(d.pop("files"))

        environment_export = cls(
            environment=environment,
            number=number,
            format_=format_,
            files=files,
        )

        environment_export.additional_properties = d
        return environment_export

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
