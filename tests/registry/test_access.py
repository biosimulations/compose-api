"""Private registry entries (docs/plan-private-repo-usage.md, A): the rules that keep one from showing through to
callers without its role, and the roles everything made of one needs. Pure: no database, no API."""

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from compose_api.environments.compliance import COMPLIANCE_DIR
from compose_api.registry.access import entry_roles, environment_roles, may_use, problems, usable, version_roles
from compose_api.registry.environments import EnvironmentSpec, load_environments
from compose_api.registry.manifest import CurationLevel, Manifest, RegistryEntry, load_manifest
from compose_api.registry.solvers import load_solvers

ROLE = "repo-viva-basic-processes"  # a repository role, named as the plan names them (repo-<name>)


def _entry(entry_id: str, **fields: Any) -> RegistryEntry:
    source = f"https://github.com/o/{entry_id}"
    return RegistryEntry(
        id=entry_id, package=entry_id, source=source, version="1", level=CurationLevel.TESTED, **fields
    )


PUBLIC = _entry("pub", module_roots=["viva_pub"])
SECRET = _entry("secret", module_roots=["viva_secret"], access_role=ROLE)
MANIFEST = Manifest(entries=[PUBLIC, SECRET])


def test_nothing_in_this_repository_lets_a_private_entry_show_through() -> None:
    """The CI rule: run against the manifest, environments, solvers and compliance cases as committed."""
    solvers = [(solver.environment, solver.address) for solver in load_solvers().solvers]
    assert problems(load_manifest(), load_environments(), solvers, COMPLIANCE_DIR) == []


def test_each_way_a_private_entry_would_show_through_is_a_problem(tmp_path: Path) -> None:
    secret = _entry("secret", module_roots=["viva_secret"], access_role=ROLE, alternative_to="pub")
    core = _entry("engine", kind="core", module_roots=["viva_engine"], access_role=ROLE)
    public = _entry("pub", module_roots=["viva_secret.sub"], requires=["secret"])
    manifest = Manifest(entries=[public, secret, core])
    shared = EnvironmentSpec(name="shared", kind="shared", python=["python"], entries=["secret"])
    environments = load_environments().model_copy(update={"environments": [shared]})
    case = tmp_path / "secret" / "a-case"
    case.mkdir(parents=True)
    for name in ("case.yaml", "document.pbg", "data.csv"):
        (case / name).write_text("")
    found = "\n".join(problems(manifest, environments, [("shared", "local:viva_secret.Thing")], tmp_path))
    for expected in (
        "engine: a private entry cannot be core",
        "secret: a private entry is no alternative to a public one",
        "pub: requires the private entry secret but is not private to its role",
        "secret: its module root viva_secret overlaps pub's viva_secret.sub",
        "secret: its compliance case holds secret/a-case/data.csv, not a document",
        "shared: the shared environment cannot hold private entries ['secret']",
        "a solver runs in shared, which holds private entries",
        "a solver's class local:viva_secret.Thing is in the private entry secret",
    ):
        assert expected in found
    assert "document.pbg" not in found and "case.yaml" not in found


@pytest.mark.parametrize("role", ["", "  ", "user"])
def test_access_role_names_a_role_only_some_callers_hold(role: str) -> None:
    with pytest.raises(ValidationError, match="names a role only some callers hold"):
        _entry("secret", module_roots=["viva_secret"], access_role=role)


def test_a_caller_without_the_role_uses_a_manifest_without_the_entry() -> None:
    assert [e.id for e in usable(MANIFEST, frozenset()).entries] == ["pub"]
    assert [e.id for e in usable(MANIFEST, frozenset({"user"})).entries] == ["pub"]
    assert usable(MANIFEST, frozenset({"user", ROLE})) is MANIFEST
    public_only = Manifest(entries=[PUBLIC])
    assert usable(public_only, frozenset()) is public_only


def test_what_is_made_of_a_private_entry_needs_its_role() -> None:
    assert entry_roles(["pub", "secret"], MANIFEST) == {ROLE}
    assert entry_roles(["pub"], MANIFEST) == frozenset()
    both = EnvironmentSpec(name="mash-x", kind="mash-up", python=["python"], entries=["pub", "secret"])
    assert environment_roles(both, MANIFEST) == {ROLE}
    assert may_use(frozenset(), frozenset()) and may_use({ROLE}, frozenset({"user", ROLE}))
    assert not may_use({ROLE}, frozenset()) and not may_use({ROLE}, frozenset({"user"}))


def test_a_version_keeps_the_roles_it_was_made_with() -> None:
    """A later manifest edit never narrows a version: the roles its spec recorded stand with its entries' current."""
    spec = {"entries": [{"id": "pub"}, {"id": "secret"}]}
    assert version_roles(spec, MANIFEST) == {ROLE}
    published = Manifest(entries=[PUBLIC, _entry("secret", module_roots=["viva_secret"])])
    assert version_roles(spec, published) == frozenset()
    assert version_roles({**spec, "access_roles": [ROLE]}, published) == {ROLE}
    assert version_roles(None, MANIFEST) == frozenset()


@pytest.mark.asyncio
async def test_a_prebuilt_environment_bundling_a_private_entry_is_private(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A prebuilt image lists no entries: its members are the entries bundled in it (viva-pde-particle's)."""
    from compose_api.registry import manifest as manifest_module
    from compose_api.registry.access import hidden_environments, run_roles

    data = yaml.safe_load(manifest_module._MANIFEST_PATH.read_text())
    next(e for e in data["entries"] if e["id"] == "viva-pde-particle")["access_role"] = ROLE
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(data))
    monkeypatch.setattr(manifest_module, "_MANIFEST_PATH", path)
    manifest = load_manifest()
    prebuilt = next(spec for spec in load_environments().environments if spec.name == "viva-pde-particle")
    assert prebuilt.kind == "prebuilt" and environment_roles(prebuilt, manifest) == {ROLE}
    assert run_roles("viva-pde-particle", None, manifest) == {ROLE}  # its runs, though its versions record no spec
    assert run_roles("registry_env", None, manifest) == frozenset()
    assert "viva-pde-particle" in await hidden_environments(None, frozenset({"user"}))
    assert "viva-pde-particle" not in await hidden_environments(None, frozenset({"user", ROLE}))
