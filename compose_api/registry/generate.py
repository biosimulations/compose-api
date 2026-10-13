"""Read the process interfaces each environment provides, inside its image, into `manifests/<name>.json`.

Strategy decision 5, phase B (docs/plan-authoring.md). For every environment in `environments.yaml` this runs
process-bigraph-lang's standalone describe script (pinned there; standard library only) in the environment's image,
over the module roots of the registry entries in its bundle, and writes the manifest it prints (`pbg-interfaces/1`).
CI runs it (`.github/workflows/registry-manifests.yml`) and opens a pull request when a manifest changes; it also runs
anywhere Docker does:

    uv run python -m compose_api.registry.generate                    # every environment
    uv run python -m compose_api.registry.generate --env viva-pde-particle \
        --describe ../process-bigraph-lang/process_bigraph_lang/v2/describe_env.py   # an unreleased script

The shared image is pulled by the reference the service would use, and built from the definition the service
generates when that tag is not published (or not readable). A prebuilt image is pulled by its pin in the
deployment's PREBUILT_SIMULATORS (kustomize/config/compose-api-rke/api.env).
"""

import argparse
import json
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from compose_api.registry.environments import (
    MANIFESTS_DIR,
    EnvironmentSpec,
    load_environments,
    manifest_path,
    module_roots,
    shared_image,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
API_ENV = REPO_ROOT / "kustomize" / "config" / "compose-api-rke" / "api.env"
PLATFORM = "linux/amd64"  # the cluster's architecture; every image is built for it


def prebuilt_pins(api_env: Path = API_ENV) -> dict[str, str]:
    """PREBUILT_SIMULATORS from the deployment's environment file."""
    for line in api_env.read_text().splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "PREBUILT_SIMULATORS":
            pins: dict[str, str] = json.loads(value)
            return pins
    return {}


def image_for(spec: EnvironmentSpec, pins: dict[str, str]) -> str:
    if spec.kind == "shared":
        return shared_image()
    if spec.name not in pins:
        raise SystemExit(f"{spec.name}: not in PREBUILT_SIMULATORS ({API_ENV})")
    return pins[spec.name]


def describe_command(spec: EnvironmentSpec, image: str, roots: list[str], script_dir: Path) -> list[str]:
    """`docker run` of the describe script in the image, through the environment's own Python."""
    entrypoint, *args = spec.python
    return [
        "docker", "run", "--rm", "--platform", PLATFORM,
        "-v", f"{script_dir}:/pblang:ro",
        "--entrypoint", entrypoint,
        image,
        *args, "/pblang/describe_env.py", *roots, "--env-name", spec.name, "--image", image,
    ]  # fmt: skip


def ensure_shared_image(image: str) -> None:
    """Pull the shared image; when that tag is not published (or not readable), build it from the definition."""
    if subprocess.run(["docker", "pull", "--platform", PLATFORM, image], check=False).returncode == 0:  # noqa: S603, S607
        return
    from pbest.containerization.container_constructor import generate_container_def_file
    from pbest.utils.input_types import ContainerizationEngine

    from compose_api.simulation.simulator_registry import registry_dependencies

    print(f"{image} is not pullable: building it from the generated definition", file=sys.stderr)
    dockerfile = generate_container_def_file(registry_dependencies(), ContainerizationEngine.DOCKER).representation
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "Dockerfile").write_text(dockerfile)
        subprocess.run(["docker", "build", "--platform", PLATFORM, "-t", image, tmp], check=True)  # noqa: S603, S607


def fetch_script(destination: Path, local: Path | None = None) -> Path:
    """The describe script at the pinned commit (or a local copy, for trying an unreleased one)."""
    target = destination / "describe_env.py"
    if local is not None:
        target.write_text(local.read_text())
    else:
        url = load_environments().describe.raw_url
        with urllib.request.urlopen(url) as response:  # noqa: S310 - a fixed https URL
            target.write_bytes(response.read())
    return target


def generate(spec: EnvironmentSpec, pins: dict[str, str], script_dir: Path, out_dir: Path) -> Path:
    roots = module_roots(spec.name)
    if not roots:
        raise SystemExit(f"{spec.name}: no registry entry lists it in `bundles`, so there is nothing to describe")
    image = image_for(spec, pins)
    if spec.kind == "shared":
        ensure_shared_image(image)
    # docker from PATH; every argument comes from environments.yaml, the registry and the deployment's pins
    command = describe_command(spec, image, roots, script_dir)
    result = subprocess.run(command, check=False, capture_output=True, text=True)  # noqa: S603
    sys.stderr.write(result.stderr)
    if result.returncode != 0:
        raise SystemExit(f"{spec.name}: describe failed with exit code {result.returncode}")
    manifest = json.loads(result.stdout)
    out = out_dir / manifest_path(spec.name).name
    out.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"{spec.name}: {len(manifest['components'])} component(s), {len(manifest['errors'])} error(s) -> {out}")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read each environment's process interfaces inside its image.")
    parser.add_argument("--env", action="append", help="an environment's name (repeatable; default: every one)")
    parser.add_argument("--list", action="store_true", help="print the environments' names as JSON and stop")
    parser.add_argument("--describe", type=Path, help="a local describe_env.py instead of the pinned one")
    parser.add_argument("--out", type=Path, default=MANIFESTS_DIR, help="where to write <name>.json")
    args = parser.parse_args(argv)
    environments = load_environments().environments
    if args.list:
        print(json.dumps([e.name for e in environments]))
        return 0
    wanted = [e for e in environments if not args.env or e.name in args.env]
    unknown = set(args.env or []) - {e.name for e in environments}
    if unknown:
        raise SystemExit(f"unknown environment(s): {sorted(unknown)}")
    args.out.mkdir(parents=True, exist_ok=True)
    pins = prebuilt_pins()
    with tempfile.TemporaryDirectory() as tmp:
        script = fetch_script(Path(tmp), args.describe)
        for spec in wanted:
            generate(spec, pins, script.parent, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
