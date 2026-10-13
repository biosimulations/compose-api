from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.image_state import ImageState
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.environment_image import EnvironmentImage
    from ..models.hpc_run import HpcRun


T = TypeVar("T", bound="ImageStatus")


@_attrs_define
class ImageStatus:
    """Whether a simulator's image is there to run from, and the records behind that answer.

    Attributes:
        simulator_id (int):
        container_def_hash (str):
        state (ImageState):
        environment (None | str | Unset): The environment whose current definition this is
        image (EnvironmentImage | None | Unset): The available image runs use
        build (HpcRun | None | Unset): The newest build run of the definition
        images (list[EnvironmentImage] | Unset): Every image recorded, newest first
    """

    simulator_id: int
    container_def_hash: str
    state: ImageState
    environment: None | str | Unset = UNSET
    image: EnvironmentImage | None | Unset = UNSET
    build: HpcRun | None | Unset = UNSET
    images: list[EnvironmentImage] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.environment_image import EnvironmentImage  # noqa: PLC0415
        from ..models.hpc_run import HpcRun  # noqa: PLC0415

        simulator_id = self.simulator_id

        container_def_hash = self.container_def_hash

        state = self.state.value

        environment: None | str | Unset
        if isinstance(self.environment, Unset):
            environment = UNSET
        else:
            environment = self.environment

        image: dict[str, Any] | None | Unset
        if isinstance(self.image, Unset):
            image = UNSET
        elif isinstance(self.image, EnvironmentImage):
            image = self.image.to_dict()
        else:
            image = self.image

        build: dict[str, Any] | None | Unset
        if isinstance(self.build, Unset):
            build = UNSET
        elif isinstance(self.build, HpcRun):
            build = self.build.to_dict()
        else:
            build = self.build

        images: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.images, Unset):
            images = []
            for images_item_data in self.images:
                images_item = images_item_data.to_dict()
                images.append(images_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "simulator_id": simulator_id,
            "container_def_hash": container_def_hash,
            "state": state,
        })
        if environment is not UNSET:
            field_dict["environment"] = environment
        if image is not UNSET:
            field_dict["image"] = image
        if build is not UNSET:
            field_dict["build"] = build
        if images is not UNSET:
            field_dict["images"] = images

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.environment_image import EnvironmentImage  # noqa: PLC0415
        from ..models.hpc_run import HpcRun  # noqa: PLC0415

        d = dict(src_dict)
        simulator_id = d.pop("simulator_id")

        container_def_hash = d.pop("container_def_hash")

        state = ImageState(d.pop("state"))

        def _parse_environment(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        environment = _parse_environment(d.pop("environment", UNSET))

        def _parse_image(data: object) -> EnvironmentImage | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                image_type_0 = EnvironmentImage.from_dict(data)

                return image_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(EnvironmentImage | None | Unset, data)

        image = _parse_image(d.pop("image", UNSET))

        def _parse_build(data: object) -> HpcRun | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                build_type_0 = HpcRun.from_dict(data)

                return build_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(HpcRun | None | Unset, data)

        build = _parse_build(d.pop("build", UNSET))

        _images = d.pop("images", UNSET)
        images: list[EnvironmentImage] | Unset = UNSET
        if _images is not UNSET:
            images = []
            for images_item_data in _images:
                images_item = EnvironmentImage.from_dict(images_item_data)

                images.append(images_item)

        image_status = cls(
            simulator_id=simulator_id,
            container_def_hash=container_def_hash,
            state=state,
            environment=environment,
            image=image,
            build=build,
            images=images,
        )

        image_status.additional_properties = d
        return image_status

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
