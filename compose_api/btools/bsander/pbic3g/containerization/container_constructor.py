import os.path
import re

from compose_api.btools.bsander.bsandr_utils.input_types import ProgramArguments
from compose_api.btools.bsander.pbic3g.containerization.container_file import get_generic_dockerfile_template, pull_substitution_keys_from_document

def formulate_dockerfile_for_necessary_env(program_arguments: ProgramArguments) -> str:
    docker_template: str = get_generic_dockerfile_template()
    pb_document_str: str
    with open(program_arguments.input_file_path, "r") as pb_document_file:
        pb_document_str = pb_document_file.read()
    pypi_deps, conda_deps, updated_document_str = determine_dependencies(pb_document_str, program_arguments.whitelist_entries)
    if updated_document_str != pb_document_str: # we need to update file
        with open(program_arguments.input_file_path, "w") as pb_document_file:
            pb_document_file.write(updated_document_str)
    for desired_field in generate_necessary_values():
        match_target: str = "$${#" + desired_field + "}"
        if "PYPI_DEPENDENCIES" == desired_field:
            if len(pypi_deps) == 0:
                docker_template = docker_template.replace(match_target, "# No PyPI dependencies!")
                continue
            pypi_section = \
"""
RUN python3 -m pip install $${#DEPENDENCIES}
""".strip()
            dependency_str = convert_dependencies_to_installation_string_representation(pypi_deps)
            filled_section = pypi_section.replace("$${#DEPENDENCIES}", dependency_str)
            docker_template = docker_template.replace(match_target, filled_section)
        elif "CONDA_FORGE_DEPENDENCIES" == desired_field:
            if len(conda_deps) == 0:
                docker_template = docker_template.replace(match_target, "# No conda dependencies!")
                continue
            conda_section = \
"""
RUN mkdir /micromamba
RUN curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xvj bin/micromamba
RUN mv bin/micromamba /usr/local/bin/
RUN micromamba create -y -p /opt/conda -c conda-forge $${#DEPENDENCIES} python=3.12
ENV PATH=/opt/conda/bin:$PATH
""".strip()
            dependency_str = " ".join(conda_deps)
            filled_section = conda_section.replace("$${#DEPENDENCIES}", dependency_str)
            docker_template = docker_template.replace(match_target, filled_section)
        else:
            raise ValueError(f"unknown field in template dockerfile: {desired_field}")

    return docker_template


def generate_necessary_values() -> list[str]:
    return pull_substitution_keys_from_document()

# Due to an assumption that we can not have all dependencies included
# in the same python environment, we need a solid address protocol to assume.
# going with: `pypi:<package_name>[<version_statement>]@<python_module_path_to_class_def>`
#         ex: "pypi:copasi-basico[~0.8]@basico.model_io.load_model" (if this was a class, and not a function)
def determine_dependencies(string_to_search: str, whitelist_entries: list[str] = None) -> tuple[list[str],list[str], str]:
    whitelist_mapping: dict[str, set[str]] | None
    if whitelist_entries is not None:
        whitelist_mapping = {}
        for whitelist_entry in whitelist_entries:
            entry = whitelist_entry.split(":")
            if len(entry) != 2:
                raise ValueError(f"invalid whitelist entry: {whitelist_entry}")
            source, package = (entry[0],entry[1])
            if source not in whitelist_mapping:
                whitelist_mapping[source] = set()
            whitelist_mapping[source].add(package)
    else:
        whitelist_mapping = None
    source_name_legal_syntax = r"[\w\-]+"
    package_name_legal_syntax = r"[\w\-._~:/?#[\]@!$&'()*+,;=%]+" # package or git-http repo name
    version_string_legal_syntax = r"\[([\w><=~!*\-.]+)]" # hard brackets around alphanumeric plus standard python version constraint characters
    import_name_legal_syntax = r"[A-Za-z_]\w*(\.[A-Za-z_]\w*)*" # stricter pattern of only legal python module names (letters and underscore first character, alphanumeric and underscore for remainder); must be at least 1 char long
    known_sources = ["pypi", "conda"]
    approved_dependencies: dict[str, list[str]] = { source : [] for source in known_sources }
    regex_pattern = f"({source_name_legal_syntax}):({package_name_legal_syntax})({version_string_legal_syntax})?@({import_name_legal_syntax})"
    adjusted_search_string = str(string_to_search)
    matches = re.findall(regex_pattern, string_to_search)
    if len(matches) == 0:
        local_protocol_matches = re.findall(f"local:{import_name_legal_syntax}", string_to_search)
        if len(local_protocol_matches) == 0:
            raise ValueError(f"No dependencies found in document; unable to generate environment.")
        raise ValueError("Document is using local protocols; unable to determine needed environment.")
    for match in matches:
        source_name = match[0]
        package_name = match[1]
        package_version = match[3]
        if source_name not in known_sources:
            raise ValueError(f"Unknown source `{source_name}` used; can not determine dependencies")
        dependency_str = f"{package_name}{package_version}".strip()
        if dependency_str in approved_dependencies[source_name]:
            continue # We've already accounted for this dependency
        if whitelist_mapping is not None:
            # We need to validate against whitelist!
            if source_name not in whitelist_mapping:
                raise ValueError(f"Unapproved source `{source_name}` used; can not trust document")
            if package_name not in whitelist_mapping[source_name]:
                raise ValueError(f"`{package_name}` from `{source_name}` is not a trusted package; can not trust document")
        approved_dependencies[source_name].append(dependency_str)
        version_str = match[2] if package_version != "" else ""
        complete_match = f"{source_name}:{package_name}{version_str}@{match[4]}"
        adjusted_search_string = adjusted_search_string.replace(complete_match, f"local:{match[4]}")
    return approved_dependencies['pypi'], approved_dependencies['conda'], adjusted_search_string.strip()

def convert_dependencies_to_installation_string_representation(dependencies: list[str]) -> str:
    return "'"+ "' '".join(dependencies) + "'"
