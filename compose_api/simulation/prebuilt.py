"""Prebuilt simulator images: run a submission in an image its owner publishes, instead of the shared one.

Every submission otherwise runs in one container whose package list is fixed here (the simulator
registry). A workspace with conda-forge dependencies or a compiled extension cannot be expressed that
way, so its owners publish an OCI image, and the deployment lists it under a name in the
``prebuilt_simulators`` setting. A request naming that simulator gets an Apptainer definition that is
just the image:

    Bootstrap: docker
    From: <image>

From there everything is unchanged:
- the definition's hash is the simulator version;
- the image is fetched once into ``images/<hash>.sif``, by pulling the image itself
  (:func:`prebuilt_image_of` gives ``_download_or_build_container`` the source);
- every job runs ``singularity run --compat <sif> run /experiment/<id>.<suffix> -o <out> -n <t>``.

The image's ENTRYPOINT must answer that command.

Only names in the setting are accepted, so a request can never pull an arbitrary image. Pin images by
digest or an immutable tag: the definition text, and so the cached SIF, is keyed on the reference.
"""

from pbest.utils.input_types import ContainerizationEngine, ContainerizationFileRepr

from compose_api.config import get_settings

_HEADER = "Bootstrap: docker\nFrom: "


class UnknownSimulatorError(LookupError):
    """The request names a simulator this deployment does not list."""


def prebuilt_image(simulator: str) -> str:
    """The image reference the deployment lists for ``simulator``."""
    images = get_settings().prebuilt_simulators
    if simulator not in images:
        listed = ", ".join(sorted(images)) or "none"
        msg = f"unknown simulator {simulator!r}; this deployment lists: {listed}"
        raise UnknownSimulatorError(msg)
    return images[simulator]


def prebuilt_definition(image: str) -> ContainerizationFileRepr:
    """The Apptainer definition that is just ``image``."""
    return ContainerizationFileRepr(
        representation=f"{_HEADER}{image}\n", containerization_engine=ContainerizationEngine.APPTAINER
    )


def prebuilt_image_of(definition: ContainerizationFileRepr) -> str | None:
    """The image a :func:`prebuilt_definition` names, or None for any other definition."""
    text = definition.representation
    if not text.startswith(_HEADER):
        return None
    image = text[len(_HEADER) :].strip()
    return image if image and "\n" not in image else None
