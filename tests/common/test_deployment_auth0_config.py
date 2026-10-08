"""Checks on the Auth0 values the Kubernetes overlays deploy.

The env-file checks read sources the way kustomize's configMapGenerator does: one KEY=VALUE per line, `#` lines
skipped, and no inline-comment stripping (a trailing `# note` would become part of the value). The render test
builds the overlays with `kustomize` or `kubectl kustomize`, which is what CI installs for this file.
"""

import shutil
import subprocess
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


def _render_overlay(overlay: Path) -> list[dict[str, object]]:
    kustomize = shutil.which("kustomize")
    if kustomize is not None:
        command = [kustomize, "build", str(overlay)]
    else:
        kubectl = shutil.which("kubectl")
        if kubectl is None:
            pytest.fail("kustomize or kubectl is required to render the Auth0 overlays")
        command = [kubectl, "kustomize", str(overlay)]
    result = subprocess.run(command, check=True, capture_output=True, text=True)  # noqa: S603
    documents = [document for document in yaml.safe_load_all(result.stdout) if isinstance(document, dict)]
    return documents


def _rendered_api_config(documents: list[dict[str, object]]) -> dict[str, str]:
    configs: list[dict[str, object]] = []
    for document in documents:
        metadata = document.get("metadata")
        name = metadata.get("name") if isinstance(metadata, dict) else None
        if document.get("kind") == "ConfigMap" and isinstance(name, str) and name.startswith("api-config"):
            configs.append(document)
    assert len(configs) == 1, "each overlay must render exactly one api-config ConfigMap"
    data = configs[0].get("data")
    assert isinstance(data, dict)
    return {str(key): str(value) for key, value in data.items()}


def test_rendered_overlays_merge_auth0_without_dropping_shared_config() -> None:
    shared = _read_env(KUSTOMIZE / "config" / "compose-api-rke" / "shared.env")
    production_env = _read_env(PRODUCTION_ENV)
    local_env = _read_env(_local_auth0_env())
    production = _rendered_api_config(_render_overlay(KUSTOMIZE / "overlays" / "compose-api-rke"))
    local = _rendered_api_config(_render_overlay(LOCAL_OVERLAY))

    assert production["AUTH0_DOMAIN"] == production_env["AUTH0_DOMAIN"]
    assert production["AUTH0_AUDIENCE"] == production_env["AUTH0_AUDIENCE"]
    assert local["AUTH0_DOMAIN"] == local_env["AUTH0_DOMAIN"]
    assert local["AUTH0_AUDIENCE"] == local_env["AUTH0_AUDIENCE"]
    assert local["AUTH0_AUDIENCE"] != production["AUTH0_AUDIENCE"]
    assert local["INTERNAL_MOUNT_DIR"] == production_env["INTERNAL_MOUNT_DIR"]
    # The Auth0 keys share api.env with the prebuilt simulators; both clusters must keep that setting too.
    assert production["PREBUILT_SIMULATORS"] == production_env["PREBUILT_SIMULATORS"]
    assert local["PREBUILT_SIMULATORS"] == production_env["PREBUILT_SIMULATORS"]
    for key, value in shared.items():
        assert production[key] == value
        assert local[key] == value
