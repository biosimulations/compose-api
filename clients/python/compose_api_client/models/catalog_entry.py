from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.curation_level import CurationLevel
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.entry_environment import EntryEnvironment


T = TypeVar("T", bound="CatalogEntry")


@_attrs_define
class CatalogEntry:
    """A registry entry as the catalog shows it (docs/plan-sedml.md, "Concepts"): what it is, how far it is trusted,
    and which of this deployment's environments provide its classes. Most `listed` entries are in none.

        Attributes:
            id (str):
            package (str):
            source (str):
            level (CurationLevel): The curation ladder, lowest first. Order matters: comparisons use the declaration order.
            module_roots (list[str]):
            version (None | str | Unset):
            commit (None | str | Unset):
            bundles (list[str] | Unset):
            evidence (list[str] | Unset):
            reviewer (None | str | Unset):
            environments (list[EntryEnvironment] | Unset):
    """

    id: str
    package: str
    source: str
    level: CurationLevel
    module_roots: list[str]
    version: None | str | Unset = UNSET
    commit: None | str | Unset = UNSET
    bundles: list[str] | Unset = UNSET
    evidence: list[str] | Unset = UNSET
    reviewer: None | str | Unset = UNSET
    environments: list[EntryEnvironment] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = self.id

        package = self.package

        source = self.source

        level = self.level.value

        module_roots = self.module_roots

        version: None | str | Unset
        if isinstance(self.version, Unset):
            version = UNSET
        else:
            version = self.version

        commit: None | str | Unset
        if isinstance(self.commit, Unset):
            commit = UNSET
        else:
            commit = self.commit

        bundles: list[str] | Unset = UNSET
        if not isinstance(self.bundles, Unset):
            bundles = self.bundles

        evidence: list[str] | Unset = UNSET
        if not isinstance(self.evidence, Unset):
            evidence = self.evidence

        reviewer: None | str | Unset
        if isinstance(self.reviewer, Unset):
            reviewer = UNSET
        else:
            reviewer = self.reviewer

        environments: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.environments, Unset):
            environments = []
            for environments_item_data in self.environments:
                environments_item = environments_item_data.to_dict()
                environments.append(environments_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "id": id,
            "package": package,
            "source": source,
            "level": level,
            "module_roots": module_roots,
        })
        if version is not UNSET:
            field_dict["version"] = version
        if commit is not UNSET:
            field_dict["commit"] = commit
        if bundles is not UNSET:
            field_dict["bundles"] = bundles
        if evidence is not UNSET:
            field_dict["evidence"] = evidence
        if reviewer is not UNSET:
            field_dict["reviewer"] = reviewer
        if environments is not UNSET:
            field_dict["environments"] = environments

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.entry_environment import EntryEnvironment  # noqa: PLC0415

        d = dict(src_dict)
        id = d.pop("id")

        package = d.pop("package")

        source = d.pop("source")

        level = CurationLevel(d.pop("level"))

        module_roots = cast(list[str], d.pop("module_roots"))

        def _parse_version(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        version = _parse_version(d.pop("version", UNSET))

        def _parse_commit(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        commit = _parse_commit(d.pop("commit", UNSET))

        bundles = cast(list[str], d.pop("bundles", UNSET))

        evidence = cast(list[str], d.pop("evidence", UNSET))

        def _parse_reviewer(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        reviewer = _parse_reviewer(d.pop("reviewer", UNSET))

        _environments = d.pop("environments", UNSET)
        environments: list[EntryEnvironment] | Unset = UNSET
        if _environments is not UNSET:
            environments = []
            for environments_item_data in _environments:
                environments_item = EntryEnvironment.from_dict(environments_item_data)

                environments.append(environments_item)

        catalog_entry = cls(
            id=id,
            package=package,
            source=source,
            level=level,
            module_roots=module_roots,
            version=version,
            commit=commit,
            bundles=bundles,
            evidence=evidence,
            reviewer=reviewer,
            environments=environments,
        )

        catalog_entry.additional_properties = d
        return catalog_entry

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
