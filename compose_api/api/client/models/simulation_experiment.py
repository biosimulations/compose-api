from collections.abc import Mapping
from typing import Any, TypeVar, Optional, BinaryIO, TextIO, TYPE_CHECKING, Generator

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..types import UNSET, Unset
from typing import cast
from typing import Union

if TYPE_CHECKING:
    from ..models.simulation_experiment_metadata import SimulationExperimentMetadata


T = TypeVar("T", bound="SimulationExperiment")


@_attrs_define
class SimulationExperiment:
    """
    Attributes:
        experiment_id (str):
        simulation_database_id (int):
        simulator_database_id (int):
        last_updated (Union[Unset, str]):
        metadata (Union[Unset, SimulationExperimentMetadata]):
    """

    experiment_id: str
    simulation_database_id: int
    simulator_database_id: int
    last_updated: Union[Unset, str] = UNSET
    metadata: Union[Unset, "SimulationExperimentMetadata"] = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.simulation_experiment_metadata import SimulationExperimentMetadata

        experiment_id = self.experiment_id

        simulation_database_id = self.simulation_database_id

        simulator_database_id = self.simulator_database_id

        last_updated = self.last_updated

        metadata: Union[Unset, dict[str, Any]] = UNSET
        if not isinstance(self.metadata, Unset):
            metadata = self.metadata.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "experiment_id": experiment_id,
            "simulation_database_id": simulation_database_id,
            "simulator_database_id": simulator_database_id,
        })
        if last_updated is not UNSET:
            field_dict["last_updated"] = last_updated
        if metadata is not UNSET:
            field_dict["metadata"] = metadata

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.simulation_experiment_metadata import SimulationExperimentMetadata

        d = dict(src_dict)
        experiment_id = d.pop("experiment_id")

        simulation_database_id = d.pop("simulation_database_id")

        simulator_database_id = d.pop("simulator_database_id")

        last_updated = d.pop("last_updated", UNSET)

        _metadata = d.pop("metadata", UNSET)
        metadata: Union[Unset, SimulationExperimentMetadata]
        if isinstance(_metadata, Unset):
            metadata = UNSET
        else:
            metadata = SimulationExperimentMetadata.from_dict(_metadata)

        simulation_experiment = cls(
            experiment_id=experiment_id,
            simulation_database_id=simulation_database_id,
            simulator_database_id=simulator_database_id,
            last_updated=last_updated,
            metadata=metadata,
        )

        simulation_experiment.additional_properties = d
        return simulation_experiment

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
