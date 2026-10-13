from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="BiomodelInfo")


@_attrs_define
class BiomodelInfo:
    """
    Attributes:
        id (str):
        name (str):
        url (str):
        format_ (None | str | Unset):
        curation (None | str | Unset):
        revision (int | None | Unset):
        publication (None | str | Unset):
    """

    id: str
    name: str
    url: str
    format_: None | str | Unset = UNSET
    curation: None | str | Unset = UNSET
    revision: int | None | Unset = UNSET
    publication: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = self.id

        name = self.name

        url = self.url

        format_: None | str | Unset
        if isinstance(self.format_, Unset):
            format_ = UNSET
        else:
            format_ = self.format_

        curation: None | str | Unset
        if isinstance(self.curation, Unset):
            curation = UNSET
        else:
            curation = self.curation

        revision: int | None | Unset
        if isinstance(self.revision, Unset):
            revision = UNSET
        else:
            revision = self.revision

        publication: None | str | Unset
        if isinstance(self.publication, Unset):
            publication = UNSET
        else:
            publication = self.publication

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "id": id,
            "name": name,
            "url": url,
        })
        if format_ is not UNSET:
            field_dict["format"] = format_
        if curation is not UNSET:
            field_dict["curation"] = curation
        if revision is not UNSET:
            field_dict["revision"] = revision
        if publication is not UNSET:
            field_dict["publication"] = publication

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = d.pop("id")

        name = d.pop("name")

        url = d.pop("url")

        def _parse_format_(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        format_ = _parse_format_(d.pop("format", UNSET))

        def _parse_curation(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        curation = _parse_curation(d.pop("curation", UNSET))

        def _parse_revision(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        revision = _parse_revision(d.pop("revision", UNSET))

        def _parse_publication(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        publication = _parse_publication(d.pop("publication", UNSET))

        biomodel_info = cls(
            id=id,
            name=name,
            url=url,
            format_=format_,
            curation=curation,
            revision=revision,
            publication=publication,
        )

        biomodel_info.additional_properties = d
        return biomodel_info

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
