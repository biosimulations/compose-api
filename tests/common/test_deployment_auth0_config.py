"""Checks on the Auth0 values the Kubernetes overlays deploy.

CI has no kubectl, so this reads the env files the way kustomize's configMapGenerator does: one KEY=VALUE per line,
`#` lines skipped, and no inline-comment stripping (a trailing `# note` would become part of the value).
"""

from pathlib import Path

import pytest
import yaml

from compose_api.config import REPO_ROOT

KUSTOMIZE = Path(REPO_ROOT) / "kustomize"
# The API pods in both overlays load this production config; compose-api-local overrides only the Auth0 keys.
PRODUCTION_ENV = KUSTOMIZE / "config" / "compose-api-rke" / "api.env"
LOCAL_OVERLAY = KUSTOMIZE / "overlays" / "compose-api-local"


def _read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            values[key.strip()] = value
    return values


def _local_auth0_env() -> Path:
    kustomization = yaml.safe_load((LOCAL_OVERLAY / "kustomization.yaml").read_text())
    [generator] = [g for g in kustomization.get("configMapGenerator", []) if g["name"] == "api-config"]
    assert generator["behavior"] == "merge", "the local overlay must override the shared config, not replace it"
    [env_file] = generator["envs"]
    return LOCAL_OVERLAY / str(env_file)


@pytest.mark.parametrize("env_file", [PRODUCTION_ENV, _local_auth0_env()], ids=["rke", "local"])
def test_auth0_values_are_well_formed(env_file: Path) -> None:
    values = _read_env(env_file)
    domain, audience = values["AUTH0_DOMAIN"], values["AUTH0_AUDIENCE"]
    for value in (domain, audience):
        assert value and value == value.strip(), f"{env_file.name}: empty or padded value"
        assert "#" not in value and "<" not in value, f"{env_file.name}: comment or placeholder left in {value!r}"
    assert not domain.startswith(("http://", "https://")) and not domain.endswith("/"), "AUTH0_DOMAIN is a bare host"


def test_local_cluster_does_not_share_the_production_audience() -> None:
    production = _read_env(PRODUCTION_ENV)["AUTH0_AUDIENCE"]
    local = _read_env(_local_auth0_env())["AUTH0_AUDIENCE"]
    assert local != production, "a development token must never be accepted by production"
