"""A simulator's container definition: the text an image is built or pulled from, and the engine that reads it.

Copied from pbest 0.6.5 (``pbest.utils.input_types``) when compose-api stopped depending on pbest
(docs/plan-environment-composition.md, D8.6). The fields and the enum's members and values are pbest's, so the
simulator rows stored before read unchanged and the wire form (``containerization_engine: 2``) stays as it was.
"""

from enum import Enum

from pydantic import BaseModel


class ContainerizationEngine(Enum):
    NONE = 0
    DOCKER = 1
    APPTAINER = 2
    BOTH = 3


class ContainerizationFileRepr(BaseModel):
    representation: str
    containerization_engine: ContainerizationEngine
