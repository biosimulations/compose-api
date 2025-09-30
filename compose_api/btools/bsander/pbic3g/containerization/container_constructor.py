import re
from typing import Optional

from compose_api.btools.bsander.bsandr_utils.input_types import (
    ContainerizationFileRepr,
    ExperimentPrimaryDependencies,
    ProgramArguments,
)
from compose_api.btools.bsander.pbic3g.containerization.container_file import (
    get_generic_dockerfile_template,
    pull_substitution_keys_from_document,
)


def formulate_dockerfile_for_necessary_env(
    program_arguments: ProgramArguments,
) -> tuple[ContainerizationFileRepr, ExperimentPrimaryDependencies]:
    pb_document_str: str
    with open(program_arguments.input_file_path) as pb_document_file:
        pb_document_str = pb_document_file.read()
    experiment_deps, updated_document_str = determine_dependencies(pb_document_str, program_arguments.passlist_entries)
    if updated_document_str != pb_document_str:  # we need to update file
        with open(program_arguments.input_file_path, "w") as pb_document_file:
            pb_document_file.write(updated_document_str)
    docker_template = generate_dockerfile(experiment_deps)

    return ContainerizationFileRepr(representation=docker_template), experiment_deps


def generate_dockerfile(experiment_deps: ExperimentPrimaryDependencies) -> str:
    docker_template: str = get_generic_dockerfile_template()
    for desired_field in generate_necessary_values():
        match_target: str = "$${#" + desired_field + "}"
        if desired_field == "PYPI_DEPENDENCIES":
            if len(experiment_deps.get_pypi_dependencies()) == 0:
                docker_template = docker_template.replace(match_target, "# No PyPI dependencies!")
                continue
            pypi_section = "RUN python3 -m pip install $${#DEPENDENCIES}"
            dependency_str = convert_dependencies_to_installation_string_representation(
                experiment_deps.get_pypi_dependencies()
            )
            filled_section = pypi_section.replace("$${#DEPENDENCIES}", dependency_str)
            docker_template = docker_template.replace(match_target, filled_section)
        elif desired_field == "CONDA_FORGE_DEPENDENCIES":
            if len(experiment_deps.get_conda_dependencies()) == 0:
                docker_template = docker_template.replace(match_target, "# No conda dependencies!")
                continue
            git_dependencies: list[str] = []
            conda_forge_dependencies: list[str] = []
            for dep in experiment_deps.get_conda_dependencies():
                (git_dependencies if dep.startswith("git+") else conda_forge_dependencies).append(dep)

            micromamba_setup = """
WORKDIR /usr/local/bin
RUN curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xvj bin/micromamba --strip-components=1
WORKDIR /
RUN micromamba create -n runtime_env python=3.12
RUN eval "$(micromamba shell hook --shell posix)" && micromamba activate runtime_env
RUN mkdir -p /code
WORKDIR /code
            """.strip()  # Micromamba is an alternative to conda/miniconda; 100% statically linked, and written in C++
            micromamba_git_setup = """
RUN git clone $${#DEPENDENCY}
RUN micromamba update -n runtime_env -f /code/$${#BASE_PATH}/env.yml
RUN pip install /code/$${#BASE_PATH}
                """.strip()  # We need to insert this section for *every* git+conda dependency
            micromamba_conda_forge_setup = """
RUN micromamba update -c conda-forge -n runtime_env $${#DEPENDENCIES}
                """.strip()  # We need to insert this only once, but with all the conda-forge dependencies

            git_dependency_str: str = ""
            conda_forge_dependency_str: str = ""
            if len(git_dependencies) > 0:
                subsections: list[str] = []
                for dep in git_dependencies:
                    dependency_str = dep[4:]
                    base_str = dep.split("/")[-1][:-4]  # get the base name, and remove the ".git" at the end
                    filled_subsection = micromamba_git_setup.replace("$${#DEPENDENCY}", dependency_str)
                    filled_subsection = filled_subsection.replace("$${#BASE_PATH}", base_str)
                    subsections.append(filled_subsection)
                git_dependency_str += "\n\n".join(subsections)

            if len(conda_forge_dependencies) > 0:
                conda_forge_update_statement = " ".join(conda_forge_dependencies)
                conda_forge_dependency_str += micromamba_conda_forge_setup.replace(
                    "$${#DEPENDENCIES}", conda_forge_update_statement
                )

            dependency_str = "\n".join([git_dependency_str, conda_forge_dependency_str])
            filled_section = micromamba_setup.replace("$${#DEPENDENCIES}", dependency_str)
            docker_template = docker_template.replace(
                match_target, filled_section
            )  # insert the full complete conda section
        else:
            raise ValueError(f"unknown field in template dockerfile: {desired_field}")

    return docker_template


def generate_necessary_values() -> list[str]:
    return pull_substitution_keys_from_document()


# Due to an assumption that we can not have all dependencies included
# in the same python environment, we need a solid address protocol to assume.
# going with: "python:pypi<`package_name`[`version_statement`]>@`python_module_path_to_class_def`"
#         ex: "python:pypi<copasi-basico[~0.8]>@basico.model_io.load_model" (if this was a class, and not a function)
def determine_dependencies(
    string_to_search: str, whitelist_entries: Optional[list[str]] = None
) -> tuple[ExperimentPrimaryDependencies, str]:
    whitelist_mapping: dict[str, set[str]] | None
    if whitelist_entries is not None:
        whitelist_mapping = {}
        for whitelist_entry in whitelist_entries:
            entry = whitelist_entry.split("::")
            if len(entry) != 2:
                raise ValueError(f"invalid whitelist entry: {whitelist_entry}")
            source, package = (entry[0], entry[1])
            if source not in whitelist_mapping:
                whitelist_mapping[source] = set()
            whitelist_mapping[source].add(package)
    else:
        whitelist_mapping = None
    source_name_legal_syntax = r"[\w\-]+"
    package_name_legal_syntax = r"[\w\-._~:/?#[\]@!$&'()*+,;=%]+"  # package or git-http repo name
    version_string_legal_syntax = (
        r"\[([\w><=~!*\-.]+)]"  # hard brackets around alphanumeric plus standard python version constraint characters
    )
    # stricter pattern of only legal python module names
    # (letters and underscore first character, alphanumeric and underscore for remainder); must be at least 1 char long
    import_name_legal_syntax = r"[A-Za-z_]\w*(\.[A-Za-z_]\w*)*"
    known_sources = ["pypi", "conda"]
    approved_dependencies: dict[str, list[str]] = {source: [] for source in known_sources}
    regex_pattern = f"python:({source_name_legal_syntax})<({package_name_legal_syntax})({version_string_legal_syntax})?>@({import_name_legal_syntax})"  #  noqa: E501
    adjusted_search_string = str(string_to_search)
    matches = re.findall(regex_pattern, string_to_search)
    if len(matches) == 0:
        local_protocol_matches = re.findall(f"local:{import_name_legal_syntax}", string_to_search)
        if len(local_protocol_matches) == 0:
            raise ValueError("No dependencies found in document; unable to generate environment.")
        match_str_list: str = ",".join([str(match) for match in matches])
        if len(match_str_list) != 0:  # For some reason, we can get a single "match" that's empty...
            raise ValueError(
                f"Document is using the following local protocols: `{match_str_list}`; unable to determine needed environment."  # noqa: E501
            )
    for match in matches:
        adjusted_search_string = process_match(
            match, adjusted_search_string, known_sources, approved_dependencies, whitelist_mapping
        )
    return ExperimentPrimaryDependencies(
        approved_dependencies["pypi"], approved_dependencies["conda"]
    ), adjusted_search_string.strip()


def process_match(
    match: list[str],
    adjusted_search_string: str,
    known_sources: list[str],
    approved_dependencies: dict[str, list[str]],
    whitelist_mapping: dict[str, set[str]] | None,
) -> str:
    source_name = match[0]
    package_name = match[1]
    package_version = match[3]
    if source_name not in known_sources:
        raise ValueError(f"Unknown source `{source_name}` used; can not determine dependencies")
    dependency_str = f"{package_name}{package_version}".strip()
    if dependency_str in approved_dependencies[source_name]:
        return adjusted_search_string  # We've already accounted for this dependency
    if whitelist_mapping is not None:
        # We need to validate against whitelist!
        if source_name not in whitelist_mapping:
            raise ValueError(f"Unapproved source `{source_name}` used; can not trust document")
        if package_name not in whitelist_mapping[source_name]:
            raise ValueError(f"`{package_name}` from `{source_name}` is not a trusted package; can not trust document")
    approved_dependencies[source_name].append(dependency_str)
    version_str = match[2] if package_version != "" else ""
    complete_match = f"python:{source_name}<{package_name}{version_str}>@{match[4]}"
    return adjusted_search_string.replace(complete_match, f"local:{match[4]}")


def convert_dependencies_to_installation_string_representation(dependencies: list[str]) -> str:
    return "'" + "' '".join(dependencies) + "'"
