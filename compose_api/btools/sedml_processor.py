from pathlib import Path

from biosimulators_utils.sedml.data_model import (  # type: ignore[import-untyped]
    DataSet,
    Report,
    SedDocument,
    UniformTimeCourseSimulation,
)
from biosimulators_utils.sedml.io import SedmlSimulationReader  # type: ignore[import-untyped]
from pydantic import BaseModel


class SimpleSedmlRepresentation(BaseModel):
    solver_kisao: str  # Should be particular KAISO
    sbml_path: Path  # Aka model

    # Task
    start_time: float
    end_time: float
    num_points: int

    # Output
    species_ids: list[str]
    parameter_ids: list[str]
    compartments_ids: list[str]
    reactions_ids: list[str]

    @staticmethod
    def sed_processor(sedml_path: Path) -> "SimpleSedmlRepresentation":
        """
        SedML Path should be absolute path to this file.
        Args:
            sedml_path:

        Returns:

        """
        reader = SedmlSimulationReader()
        sed_doc: SedDocument = reader.run(filename=str(sedml_path))

        if not isinstance(sed_doc.simulations[0], UniformTimeCourseSimulation):
            raise TypeError("Can only accept 'UniformTimeCourseSimulation' for simulation.")
        if not isinstance(sed_doc.outputs[0], Report):
            raise TypeError("Can only accept 'Report' for output.")

        time_course = sed_doc.simulations[0]

        species = []
        parameters = []
        compartments = []
        reactions = []
        datasets: list[DataSet] = sed_doc.outputs[0].data_sets
        for ds in datasets:
            # Ignore for now
            if ds.data_generator.variables[0].symbol == "urn:sedml:symbol:time":
                pass
            else:
                tar: str = ds.data_generator.variables[0].target
                id_value = tar.split("'")[1]
                if "species" in tar:
                    species.append(id_value)
                elif "parameter" in tar:
                    parameters.append(id_value)
                elif "compartment" in tar:
                    compartments.append(id_value)
                elif "reaction" in tar:
                    reactions.append(id_value)
                else:
                    raise ValueError("Unknown target type")
        rel_path = str(sedml_path.absolute()).rsplit("/", 1)[0]
        return SimpleSedmlRepresentation(
            solver_kisao=time_course.algorithm.kisao_id,
            sbml_path=Path(f"{rel_path}/{sed_doc.models[0].source}"),
            start_time=time_course.output_start_time,
            end_time=time_course.output_end_time,
            num_points=time_course.number_of_points,
            species_ids=species,
            parameter_ids=parameters,
            compartments_ids=compartments,
            reactions_ids=reactions,
        )
