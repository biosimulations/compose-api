"""A mash-up made for a run without a cluster (docs/plan-environment-composition.md, step 7b): its lock Job and its
background build, replaced."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest

from compose_api.environments import lifecycle
from compose_api.environments.source_credentials import PrivateSource
from compose_api.simulation.models import SimulatorVersion


@dataclass
class Locks:
    """The lock Job, replaced: a distinct lock per request, or a refusal. ``sources`` are the private repositories
    each request was to read."""

    refuse: str | None = None
    asked: list[str] = field(default_factory=list)
    sources: list[tuple[PrivateSource, ...]] = field(default_factory=list)

    async def __call__(
        self,
        toml: str,
        pixi_image: str,
        suffix: str,
        sources: Sequence[PrivateSource] = (),
        evidence: object = (),
    ) -> str:
        from compose_api.simulation.build_k8s import LockFailedError

        self.asked.append(toml)
        self.sources.append(tuple(sources))
        if self.refuse is not None:
            raise LockFailedError(self.refuse)
        return f"version: 7\n# {uuid.uuid4().hex}\n"


@pytest.fixture
def locks(monkeypatch: pytest.MonkeyPatch) -> Locks:
    from compose_api.simulation import build_k8s

    fake = Locks()
    monkeypatch.setattr(build_k8s, "lock_composed", fake)
    return fake


@pytest.fixture
def builds(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The background build, replaced: records which version it was started for."""
    started: list[str] = []

    async def build(version: Any, simulator: SimulatorVersion, suffix: str | None = None) -> None:
        started.append(version.label)

    monkeypatch.setattr(lifecycle, "build_and_export", build)
    return started
