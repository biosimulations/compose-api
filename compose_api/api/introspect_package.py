import logging
import urllib
from urllib.parse import ParseResult

from pbest.utils.input_types import ExperimentPrimaryDependencies

from compose_api.simulation.models import PackageOutline, PackageType

logger = logging.getLogger(__name__)


def introspect_package(dependencies: ExperimentPrimaryDependencies) -> list[PackageOutline]:
    package_outlines = []
    for dep in dependencies.get_pypi_dependencies():
        package_outlines.append(PackageOutline(package_type=PackageType.PYPI, name=dep, compute=[]))
    for dep in dependencies.get_conda_dependencies():
        package_outlines.append(PackageOutline(package_type=PackageType.CONDA, name=dep, compute=[]))
    return package_outlines


def _get_package_github_origin(pypi_package: str) -> ParseResult:
    if "https://github.com" in pypi_package:
        url, branch = pypi_package.split("+")[1].split("@")
        url = url.split(".git")[0]
        parsed_url = urllib.parse.urlparse(url)
        github_url = f"https://raw.githubusercontent.com{parsed_url.path}/refs/heads/{branch}/pb_outline.json"
        return urllib.parse.urlparse(github_url)

    raise ValueError(f"Not implemented yet: {pypi_package}")
    # package_name = pypi_package.split("/")[-1]
    # package_version = pypi_package.split("/")[-2]
    # url = f"https://pypi.org/pypi/{package_name}/{package_version}/json"
    #
    # response = requests.get(url)
    # response.raise_for_status()
    # data = response.json()


# def _live_pypi_introspection(pypi_package: str) -> BiGraphPackage:
#     return BiGraphPackage()


if __name__ == "__main__":
    packages = introspect_package(
        ExperimentPrimaryDependencies(
            pypi_dependencies=["git+https://github.com/biosimulators/bspil-basico.git@initial_work"],
            conda_dependencies=[],
        )
    )
    print(packages)
