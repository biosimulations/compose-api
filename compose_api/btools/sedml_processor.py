from pathlib import Path

from biosimulators_utils.sedml.data_model import (  # type: ignore[import-untyped]
    DataSet,
    Report,
    SedDocument,
    UniformTimeCourseSimulation, Task, AbstractTask, DataGenerator, Output, ModelChange, ModelAttributeChange,
)
from biosimulators_utils.sedml.io import SedmlSimulationReader  # type: ignore[import-untyped]
from pydantic import BaseModel


class SimpleSedmlRepresentation(BaseModel):
    solver_kisao: str  # Should be particular KAISO
    sbml_path: Path  # Aka model

    # Model
    changes: list[tuple[str, str]]

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


        if 1 != len(sed_doc.tasks):
            raise NotImplementedError("We can only handle one task at a time right now.")
        task = sed_doc.tasks[0]
        if not isinstance(task, AbstractTask):
            raise RuntimeError("Non-AbstractTask detected in list of (abstract) tasks!")
        if not isinstance(task, Task):
            raise NotImplementedError(f"Can only perform Tasks at this time, not {task.__class__.__name__}s")

        if not isinstance(task.simulation, UniformTimeCourseSimulation):
            raise TypeError("Can only accept 'UniformTimeCourseSimulation' for simulation.")
        # Get outputs from task
        data_gen_ids: set[str] = set()
        for data_generator in sed_doc.data_generators:
            if not isinstance(data_generator, DataGenerator):
                raise RuntimeError("Non-'DataGenerator' found in list of DataGenerators!")
            if 1 != len(data_generator.variables):
                raise NotImplementedError("Can only handle one variable in a data generator at a time right now.")
            variable = data_generator.variables[0]
            if task != variable.task:
                continue
            data_gen_ids.add(data_generator.id)

        reports = [output for output in sed_doc.outputs if isinstance(output, Report)]
        if 1 != len(reports):
            raise NotImplementedError("We expect only one report-type output at this time!")
        report: Report = reports[0]
        for data_set in report.data_sets:
            if not isinstance(data_set, DataSet):
                raise RuntimeError("Non-'DataSet' found in list of DataSets!")
            if data_set.data_generator.id not in data_gen_ids:
                raise RuntimeError(f"Data generator {data_set.data_generator.id} not found.")

        changes = SimpleSedmlRepresentation.parse_model_changes(task.model.changes)
        time_course = task.simulation

        species = []
        parameters = []
        compartments = []
        reactions = []
        datasets: list[DataSet] = report.data_sets
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
            changes=changes,
            start_time=time_course.output_start_time,
            end_time=time_course.output_end_time,
            num_points=time_course.number_of_points,
            species_ids=species,
            parameter_ids=parameters,
            compartments_ids=compartments,
            reactions_ids=reactions,
        )

    @staticmethod
    def parse_model_changes(changes: list[ModelChange]) -> list[tuple[str, str]]:
        if changes is None:
            return []
        valid_changes: list[ModelAttributeChange] = [ elem for elem in changes if isinstance(elem, ModelAttributeChange)]
        if len(valid_changes) != len(changes):
            raise NotImplementedError("Only AttributeChanges are supported at this time.")
        return [(elem.target, elem.new_value) for elem in valid_changes]
