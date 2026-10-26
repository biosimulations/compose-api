"""A composed version as uv files, for people who use uv rather than pixi (docs/plan-environment-composition.md, C2a,
step 4b).

pixi builds every image; a version whose entries need nothing from conda-forge (beyond Python) is also offered as a
``pyproject.toml`` and ``uv.lock`` for ``uv sync``. The project names the entries and the core as its dependencies and
constrains every other package to exactly the version ``pixi.lock`` holds, so uv can only arrive at the same set; the
uv lock is made in a Job (``build_k8s.uv_lock_job``) and kept only if it did (:func:`differences`).
"""

import re
import tomllib
from typing import Any

import yaml

from compose_api.environments.pixi import _toml

# what pixi locked for, and the image runs
PLATFORM = "sys_platform == 'linux' and platform_machine == 'x86_64' and implementation_name == 'cpython'"


def _normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def needs_conda(spec: dict[str, Any]) -> bool:
    """Whether a composed version's recorded spec needs anything from conda-forge besides Python."""
    return any(entry.get("conda") for entry in spec.get("entries", []))


def pypi_pins(pixi_lock: str) -> dict[str, str]:
    """Every PyPI package ``pixi.lock`` resolved, by normalized name: its version (a git source's included)."""
    packages = (yaml.safe_load(pixi_lock) or {}).get("packages", [])
    return {_normalized(p["name"]): str(p["version"]) for p in packages if "pypi" in p and "name" in p}


def _requirement(entry: dict[str, Any]) -> str | None:
    install = entry.get("install")
    if not install:
        return None
    name = install.get("pypi") or install["git"].rstrip("/").removesuffix(".git").rsplit("/", 1)[-1]
    extras = f"[{','.join(install['extras'])}]" if install.get("extras") else ""
    if install.get("git"):
        return f"{name}{extras} @ git+{install['git']}@{install['commit']}"
    return f"{name}{extras}=={install['version']}"


def pyproject(environment: str, number: int, spec: dict[str, Any], pins: dict[str, str]) -> str:
    """The uv project for a version: its entries and core as dependencies, every other package pinned by constraint
    to what pixi resolved, for the same platform (Linux x86-64), and the same resolution date."""
    requirements = [r for r in (_requirement(e) for e in spec.get("entries", [])) if r is not None]
    requirements += [f"{name}=={version}" for name, version in sorted(spec.get("core", {}).items())]
    direct = {_normalized(re.split(r"[\[ =@]", r, maxsplit=1)[0]) for r in requirements}
    constraints = [f"{name}=={version}" for name, version in sorted(pins.items()) if name not in direct]
    exclude_newer = _exclude_newer(spec.get("pixi_toml", ""))
    lines = [
        "[project]",
        f"name = {_toml(_normalized(f'{environment}-{number}'))}",
        'version = "0"',
        f"requires-python = {_toml('==' + str(spec.get('python', '3.12')) + '.*')}",
        f"dependencies = {_toml(requirements)}",
        "",
        "[tool.uv]",
        "package = false",
        # what pixi locked for, and the image runs: CPython on Linux x86-64 (uv would otherwise resolve for every
        # platform and implementation, PyPy's extra dependencies included)
        f"environments = {_toml([PLATFORM])}",
        f"constraint-dependencies = {_toml(constraints)}",
        *([f"exclude-newer = {_toml(exclude_newer)}"] if exclude_newer else []),
        "",
    ]
    return "\n".join(lines)


def _exclude_newer(pixi_toml: str) -> str | None:
    found = re.search(r'^exclude-newer = "([^"]+)"', pixi_toml, re.MULTILINE)
    return found.group(1) if found else None


def uv_pins(uv_lock: str) -> dict[str, str]:
    """Every package ``uv.lock`` resolved, by normalized name, but the project itself (a virtual one: no version)."""
    return {
        _normalized(p["name"]): str(p["version"])
        for p in tomllib.loads(uv_lock).get("package", [])
        if "version" in p and not (p.get("source") or {}).get("virtual")
    }


def differences(pixi: dict[str, str], uv: dict[str, str]) -> list[str]:
    """How uv's resolution differs from pixi's (empty when it is the same set, at the same versions)."""
    return [
        f"{name}: pixi {pixi.get(name, '-')}, uv {uv.get(name, '-')}"
        for name in sorted(pixi.keys() | uv.keys())
        if pixi.get(name) != uv.get(name)
    ]
