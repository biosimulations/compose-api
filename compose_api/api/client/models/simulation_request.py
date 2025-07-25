from collections.abc import Mapping
from typing import Any, TypeVar, Optional, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
  from ..models.simulation_request_variant_config import SimulationRequestVariantConfig
  from ..models.simulator_version import SimulatorVersion





T = TypeVar("T", bound="SimulationRequest")



@_attrs_define
class SimulationRequest:
    """
        Attributes:
            simulator (SimulatorVersion):
            variant_config (SimulationRequestVariantConfig):
     """

    simulator: 'SimulatorVersion'
    variant_config: 'SimulationRequestVariantConfig'
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.simulation_request_variant_config import SimulationRequestVariantConfig
        from ..models.simulator_version import SimulatorVersion
        simulator = self.simulator.to_dict()

        variant_config = self.variant_config.to_dict()


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "simulator": simulator,
            "variant_config": variant_config,
        })

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.simulation_request_variant_config import SimulationRequestVariantConfig
        from ..models.simulator_version import SimulatorVersion
        d = dict(src_dict)
        simulator = SimulatorVersion.from_dict(d.pop("simulator"))




        variant_config = SimulationRequestVariantConfig.from_dict(d.pop("variant_config"))




        simulation_request = cls(
            simulator=simulator,
            variant_config=variant_config,
        )


        simulation_request.additional_properties = d
        return simulation_request

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
