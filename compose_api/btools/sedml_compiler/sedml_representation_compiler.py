import os
from enum import Enum

from jinja2 import Template

from compose_api.btools.sedml_processor import SimpleSedmlRepresentation


class ToolSuites(Enum):
    BASICO = 1
    TELLURIUM = 2


class SimpleSedmlCompiler:
    @staticmethod
    def compile(sedml_repr: SimpleSedmlRepresentation, tool_suite: ToolSuites) -> str:
        pass
        # load template
        # get list of steps based on tool-suite
        # substitute identifier patters with address in tool-suite list.
        duration = sedml_repr.end_time - sedml_repr.start_time
        simulator_address: str
        if tool_suite == ToolSuites.BASICO:
            simulator_address = "python:pypi<git+https://github.com/biosimulators/bspil-basico.git@initial_work>@bspil_basico.legacy.run_basic_simulation.Legacy_RunBasicSBMLTimeCourseSimulation"
        else:
            raise NotImplementedError()
        with open(os.path.dirname(__file__) + "/templates/SimpleSedmlPbifTemplate.jinja") as f:
            template = Template(f.read())
            return template.render(
                start_time=sedml_repr.start_time,
                duration=duration,
                num_data_points=sedml_repr.num_points,
                simulator_address=simulator_address,
                sbml_file_path=sedml_repr.sbml_path,
                output_dir="output",
            )

        # done!
