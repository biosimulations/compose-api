import os
import shutil

from compose_api.btools.bsander.bsandr_utils.experiment_archive import extract_archive_returning_pbif_path
from compose_api.btools.bsander.bsandr_utils.input_types import ProgramArguments, ContainerizationTypes, ContainerizationEngine
from compose_api.btools.bsander.pbic3g.containerization.container_constructor import formulate_dockerfile_for_necessary_env
from compose_api.btools.bsander.pbic3g.local_registry import load_local_modules
from spython.main.parse.parsers import DockerParser
from spython.main.parse.writers import SingularityWriter



def execute_bsander(original_program_arguments: ProgramArguments):
    new_input_file_path: None | str = None
    input_is_archive = original_program_arguments.input_file_path.endswith(
        ".zip") or original_program_arguments.input_file_path.endswith(".omex")
    required_program_arguments: ProgramArguments
    if input_is_archive:
        new_input_file_path = extract_archive_returning_pbif_path(original_program_arguments.input_file_path, original_program_arguments.output_dir)
    else:
        new_input_file_path = os.path.join(original_program_arguments.output_dir, os.path.basename(original_program_arguments.input_file_path))

        print("file copied to `{}`".format(shutil.copy(original_program_arguments.input_file_path, new_input_file_path)))
    required_program_arguments = ProgramArguments(new_input_file_path, original_program_arguments.output_dir,
                                                  original_program_arguments.whitelist_entries,
                                                  original_program_arguments.containerization_type,
                                                  original_program_arguments.containerization_engine)

    load_local_modules()  # Collect Abstracts
    # TODO: Add feature - resolve abstracts

    if required_program_arguments.containerization_type != ContainerizationTypes.NONE:
        if required_program_arguments.containerization_type != ContainerizationTypes.SINGLE:
            raise NotImplementedError("Only single containerization is currently supported")
        docker_template: str = formulate_dockerfile_for_necessary_env(required_program_arguments)
        container_file_path: str
        container_file_path = os.path.join(required_program_arguments.output_dir, "Dockerfile")
        with open(container_file_path, "w") as docker_file:
            docker_file.write(docker_template)
        if required_program_arguments.containerization_engine == ContainerizationEngine.APPTAINER \
                or required_program_arguments.containerization_engine == ContainerizationEngine.BOTH:
            dockerfile_path = container_file_path
            container_file_path = os.path.join(required_program_arguments.output_dir, "singularity.def")
            dockerfile_parser = DockerParser(dockerfile_path)
            singularity_writer = SingularityWriter(dockerfile_parser.recipe)
            results = singularity_writer.convert()
            with open(container_file_path, "w") as container_file:
                container_file.write(results)
            if required_program_arguments.containerization_engine != ContainerizationEngine.BOTH:
                os.remove(dockerfile_path)
        print(f"Container build file located at '{container_file_path}'")

    # Reconstitute if archive
    if input_is_archive:
        base_name = os.path.basename(original_program_arguments.input_file_path)
        new_archive_path = os.path.join(original_program_arguments.output_dir, base_name)
        target_dir = os.path.join(original_program_arguments.output_dir, base_name.split(".")[0])
        shutil.make_archive(new_archive_path, 'zip', target_dir)
        shutil.move(new_archive_path + ".zip", new_archive_path) # get rid of extra suffix
