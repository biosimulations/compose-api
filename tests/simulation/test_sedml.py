from pathlib import Path

from biosimulators_utils.sedml.data_model import (  # type: ignore[import-untyped]
    Plot2D,
    Report,
    SedDocument,
    UniformTimeCourseSimulation,
)
from biosimulators_utils.sedml.io import SedmlSimulationReader  # type: ignore[import-untyped]

from compose_api.btools.sedml_compiler.sedml_representation_compiler import SimpleSedmlCompiler, ToolSuites
from compose_api.btools.sedml_processor import SimpleSedmlRepresentation
from tests.simulators.utils import test_dir


def test_simple_parsing() -> None:
    sedml_path = f"{test_dir}/resources/BIOMD0000000012_url.sedml"
    reader = SedmlSimulationReader()
    sed_doc: SedDocument = reader.run(filename=sedml_path)

    # SedML #
    assert len(sed_doc.models) == 1
    assert sed_doc.models[0].language == "urn:sedml:language:sbml"
    assert sed_doc.models[0].source == "BIOMD0000000012_url.xml"

    assert len(sed_doc.simulations) == 1
    assert isinstance(sed_doc.simulations[0], UniformTimeCourseSimulation)
    assert sed_doc.simulations[0].algorithm.kisao_id == "KISAO_0000694"  # Mapping between math and actual bio concept
    assert sed_doc.simulations[0].number_of_points == 1000
    assert sed_doc.simulations[0].output_end_time == 10.0
    assert sed_doc.simulations[0].output_start_time == 0

    assert len(sed_doc.tasks) == 1
    assert sed_doc.tasks[0].model == sed_doc.models[0]
    assert sed_doc.tasks[0].simulation == sed_doc.simulations[0]

    assert len(sed_doc.outputs) == 2
    assert isinstance(sed_doc.outputs[0], Report)
    assert sed_doc.outputs[0].id == "autogen_report_for_task1"
    assert isinstance(sed_doc.outputs[1], Plot2D)

    assert len(sed_doc.outputs[0].data_sets) == 36
    assert sed_doc.outputs[0].data_sets[0].data_generator.math == "auto_time_for_task1_var"

    assert len(sed_doc.outputs[0].data_sets[0].data_generator.variables) == 1
    assert (
        sed_doc.outputs[0].data_sets[1].data_generator.variables[0].target
        == "/sbml:sbml/sbml:model/sbml:listOfSpecies/sbml:species[@id='PX']"
    )

    targets = []
    for i in range(1, len(sed_doc.outputs[0].data_sets)):
        gen = sed_doc.outputs[0].data_sets[i]
        assert len(gen.data_generator.variables) == 1
        targets.append(gen.data_generator.variables[0].target)

    assert len(targets) == 35


def test_simple_sedml_rep() -> None:
    sedml_path = f"{test_dir}/resources/BIOMD0000000012_url.sedml"
    simple_sed = SimpleSedmlRepresentation.sed_processor(sedml_path=Path(sedml_path))
    print(simple_sed)


def test_sedml_compilation() -> None:
    sedml_path = f"{test_dir}/resources/BIOMD0000000012_url.sedml"
    simple_sed = SimpleSedmlRepresentation.sed_processor(sedml_path=Path(sedml_path))
    pbif = SimpleSedmlCompiler.compile(simple_sed, ToolSuites.BASICO)
    expected = """
{
    "composition": {
        "sim_start_time": "float",
        "sim_duration": "float",
        "sim_num_data_points": "integer",
        "sim_end_time": "float",
        "time_course": {
            "_type": "process",
            "address": {"_type": "quote", "_default": "local:time_course"},
            "_config": {
                "sbml_file_path": "string",
                "output_dir": "string"
            },
            "_inputs": {
                "starting_time": "float",
                "duration": "float",
                "num_data_points": "integer"
            },
            "_outputs": {}
        }
    },
    "state": {
        "sim_start_time": 0.0,
        "sim_duration": 10.0,
        "sim_end_time": 10.0,
        "sim_num_data_points": 1000,
        "time_course": {
            "_type" : "process",
            "address": "python:pypi<git+https://github.com/biosimulators/bspil-basico.git@initial_work>@bspil_basico.legacy.run_basic_simulation.Legacy_RunBasicSBMLTimeCourseSimulation",
            "config": {
                "sbml_file_path": "BIOMD0000000012_url.xml",
                "output_dir": "output"
            },
            "interval": 1.0,
            "inputs": {
                "starting_time": ["sim_start_time"],
                "duration": ["sim_duration"],
                "end_time": ["sim_end_time"],
                "num_data_points": ["sim_num_data_points"]
            },
            "outputs": {}
        }
    }
}
    """.strip()
    assert expected == pbif
