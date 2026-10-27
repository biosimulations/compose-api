"""A wheel installed by URL and sha256 (docs/plan-environment-composition.md, 7c-2, D7c.1): one no index publishes, such
as Smoldyn built for VCell. pixi checks no hash for a direct URL, neither when it locks nor when it installs (checked
2026-10-27), so the build checks each wheel against its entry's sha256 before installing."""

import hashlib
import subprocess
from pathlib import Path

import pytest

from compose_api.environments import pixi, uv_export
from compose_api.environments.pixi import ComposedSpec, PixiLock, composed_definition, pixi_toml
from compose_api.registry.environments import EnvironmentSpec
from compose_api.registry.manifest import CurationLevel, Install, Manifest, RegistryEntry, load_manifest
from tests.environments.test_pixi import COMPOSITION, WHEN, _registry_env

SHA = "2f427b5b0e554773f8effebb7768ce8980273b321f21ef4d57e832fcd0cef63a"
WHEEL = (
    "https://github.com/virtualcell/Smoldyn/releases/download/vcell-pyhybrid-e86d552/"
    "smoldyn-2.76.dev0+vcell.e86d552-cp312-cp312-linux_x86_64.whl"
)


def _smoldyn() -> RegistryEntry:
    return RegistryEntry(
        id="smoldyn-vcell",
        kind="library",
        package="smoldyn",
        source=WHEEL,
        version="2.76.dev0+vcell.e86d552",
        level=CurationLevel.INSTALLABLE,
        install=Install(url=WHEEL, sha256=SHA),
    )


def test_a_url_install_is_an_https_wheel_with_its_sha256() -> None:
    install = Install(url=WHEEL, sha256=SHA)
    assert install.name == "smoldyn"  # from the wheel's file name
    for bad, match in (
        ({"url": WHEEL}, "needs the wheel's `sha256`"),
        ({"url": WHEEL, "sha256": "abc"}, "needs the wheel's `sha256`"),
        ({"url": WHEEL.replace("https", "http"), "sha256": SHA}, "https URL of a `.whl`"),
        ({"url": WHEEL.removesuffix(".whl") + ".tar.gz", "sha256": SHA}, "https URL of a `.whl`"),
        ({"url": WHEEL + "#sha256=" + SHA, "sha256": SHA}, "https URL of a `.whl`"),
        ({"url": WHEEL, "sha256": SHA, "pypi": "smoldyn", "version": "1"}, "exactly one of"),
        ({"pypi": "smoldyn", "version": "1", "sha256": SHA}, "`sha256` is for a `url` install"),
    ):
        with pytest.raises(ValueError, match=match):
            Install.model_validate(bad)


def test_the_workspace_carries_the_hash_in_the_url() -> None:
    spec = _registry_env()
    with_wheel = ComposedSpec(**{**spec.__dict__, "entries": (*spec.entries, _smoldyn())})
    toml = pixi_toml(with_wheel)
    assert f'"smoldyn" = {{ "url" = "{WHEEL}#sha256={SHA}" }}' in toml


def test_only_a_lock_with_url_wheels_gets_the_check() -> None:
    spec = _registry_env()
    plain = composed_definition(spec, PixiLock("version: 7\n"), COMPOSITION.pixi_image).representation
    # every other definition is byte for byte what it was, so no existing version's identity changes
    assert "curl" not in plain and "rm -rf /var/lib/apt/lists/*\ncd /opt/environment\n" in plain
    lock = PixiLock(f"version: 7\npackages:\n- pypi: direct+{WHEEL}#sha256={SHA}\n  name: smoldyn\n")
    assert pixi.url_wheels(lock) == [(WHEEL, SHA)]
    checked = composed_definition(spec, lock, COMPOSITION.pixi_image).representation
    assert "apt-get install -y --no-install-recommends curl" in checked
    assert f"curl -fsSL '{WHEEL}' -o /tmp/url.whl || exit 1" in checked
    assert checked.index("sha256sum -c") < checked.index("pixi install --frozen")


@pytest.mark.parametrize("matches", [True, False])
def test_the_check_passes_the_wheel_or_fails_the_build(tmp_path: Path, matches: bool) -> None:
    wheel = tmp_path / "x.whl"
    wheel.write_bytes(b"a wheel")
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest() if matches else "0" * 64
    fetched = "/tmp/url.whl"  # noqa: S108 - the build's own path, replaced by one under tmp_path here
    script = pixi._URL_CHECK.format(url=wheel.as_uri(), sha256=digest).replace(fetched, str(tmp_path / "f"))
    done = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)  # noqa: S603, S607
    assert (done.returncode == 0) == matches, done.stderr
    if not matches:
        assert "sha256 mismatch" in done.stderr


def test_a_mash_up_may_list_a_url_entry() -> None:
    manifest = Manifest(entries=[*load_manifest().entries, _smoldyn()])
    spec = EnvironmentSpec(name="mash-x", kind="mash-up", python=["python"], entries=["smoldyn-vcell"])
    composed = ComposedSpec.of(spec, manifest, COMPOSITION, WHEN)
    assert composed.as_json()["entries"][0]["install"] == {"url": WHEEL, "sha256": SHA}


def test_the_uv_export_requires_the_wheel_by_its_url_and_hash() -> None:
    requirement = uv_export._requirement({"install": {"url": WHEEL, "sha256": SHA}})
    assert requirement == f"smoldyn @ {WHEEL}#sha256={SHA}"
