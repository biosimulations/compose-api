from collections.abc import Mapping
from typing import Any, TypeVar, Optional, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast
from typing import cast, Union
from typing import Union

if TYPE_CHECKING:
  from ..models.simulation_request import SimulationRequest





T = TypeVar("T", bound="Simulation")



@_attrs_define
class Simulation:
    """
        Attributes:
            database_id (int):
            sim_request (SimulationRequest):
            slurmjob_id (Union[None, Unset, int]):
     """

    database_id: int
    sim_request: 'SimulationRequest'
    slurmjob_id: Union[None, Unset, int] = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)





    def to_dict(self) -> dict[str, Any]:
        from ..models.simulation_request import SimulationRequest
        database_id = self.database_id

        sim_request = self.sim_request.to_dict()

        slurmjob_id: Union[None, Unset, int]
        if isinstance(self.slurmjob_id, Unset):
            slurmjob_id = UNSET
        else:
            slurmjob_id = self.slurmjob_id


        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "database_id": database_id,
            "sim_request": sim_request,
        })
        if slurmjob_id is not UNSET:
            field_dict["slurmjob_id"] = slurmjob_id

        return field_dict



    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.simulation_request import SimulationRequest
        d = dict(src_dict)
        database_id = d.pop("database_id")

        sim_request = SimulationRequest.from_dict(d.pop("sim_request"))




        def _parse_slurmjob_id(data: object) -> Union[None, Unset, int]:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(Union[None, Unset, int], data)

        slurmjob_id = _parse_slurmjob_id(d.pop("slurmjob_id", UNSET))


        simulation = cls(
            database_id=database_id,
            sim_request=sim_request,
            slurmjob_id=slurmjob_id,
        )


        simulation.additional_properties = d
        return simulation

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
