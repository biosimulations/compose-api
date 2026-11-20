"""Fetching a private repository's source (docs/plan-private-repo-usage.md, C). The token: minted by the GitHub App for
exactly a version's private repositories, or not at all. The Jobs: a private version's alone are given it, each in a
Secret it owns, and the privileged build never mounts it. git: the credential helper and the clone, run with real git
and bash. GitHub and Kubernetes are stand-ins (tests/fixtures/private_source_fixtures.py); that the real ones accept
what is asked of them is proven live, in the plan's P5."""

import datetime
import os
import subprocess
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest

from compose_api.config import override_settings
from compose_api.environments import source_credentials
from compose_api.environments.source_credentials import PrivateSource, SourceCredentialsError, private_sources
from compose_api.simulation import build_k8s
from compose_api.simulation.build_k8s import (
    CREDENTIALS_DIR,
    GITCONFIG,
    BuildSite,
    PrivateBuild,
    build_gitconfig,
    build_job,
    clone_script,
)
from tests.fixtures.private_source_fixtures import JOB_UID, TOKEN, FakeGitHub, RecordingBuilds, serialized

V2ECOLI = PrivateSource("https://github.com/vivarium-collective/v2ecoli", "e9250af2bb345cee85a35cc11ac6299d0ad81d9c")
BASIC = PrivateSource(
    "https://github.com/vivarium-collective/viva-basic-processes", "9a1a624dc925cf700c3f89a8cc008a8fa4b4e5d4"
)
PIXI_IMAGE = "ghcr.io/prefix-dev/pixi@sha256:" + "a" * 64
SITE = BuildSite(
    namespace="ns", image="ghcr.io/apptainer/apptainer:1.3.6", pvc_claim="home", pvc_mount_path="/projects/CRBM",
    pvc_sub_path="", run_as_uid=16997, run_as_gid=10000, supplemental_groups=(), timeout_seconds=600,
)  # fmt: skip


def test_a_versions_private_repositories_are_its_entries_with_a_role_that_install_from_git() -> None:
    entries: list[dict[str, Any]] = [
        {"id": "v2ecoli", "install": {"git": V2ECOLI.url, "commit": V2ECOLI.commit}, "access_role": "repo-v2ecoli"},
        {"id": "public", "install": {"git": "https://github.com/o/public", "commit": "b" * 40}, "conda": {}},
        {"id": "from-pypi", "install": None, "access_role": "repo-other"},  # from an index: nothing to fetch
    ]
    assert private_sources(entries) == (V2ECOLI,)
    assert private_sources([]) == ()


@pytest.mark.asyncio
async def test_a_token_reads_exactly_the_versions_private_repositories(fake_github: FakeGitHub) -> None:
    assert await source_credentials.token_for([V2ECOLI, BASIC, V2ECOLI]) == TOKEN
    assert fake_github.minted == [
        {"repositories": ["v2ecoli", "viva-basic-processes"], "permissions": {"contents": "read"}}
    ]


@pytest.mark.asyncio
async def test_a_token_is_reused_only_while_it_outlives_a_job(fake_github: FakeGitHub) -> None:
    """A lock Job may run for 30 minutes: a token is handed out again only while it has 40 left, and only for the same
    repositories."""
    for _ in range(2):
        await source_credentials.token_for([V2ECOLI])
    await source_credentials.token_for([BASIC])
    assert [m["repositories"] for m in fake_github.minted] == [["v2ecoli"], ["viva-basic-processes"]]
    fake_github.lifetime = datetime.timedelta(minutes=39)
    source_credentials._tokens.clear()
    for _ in range(2):
        await source_credentials.token_for([V2ECOLI])
    assert len(fake_github.minted) == 4


@pytest.mark.asyncio
async def test_a_build_gets_a_token_with_nearly_its_hour_left(fake_github: FakeGitHub) -> None:
    """A build's clone runs when its pod starts, which can wait for a node: a token a lock Job would still take (50
    minutes left) is not handed to a build."""
    fake_github.lifetime = datetime.timedelta(minutes=50)
    await source_credentials.token_for([V2ECOLI])
    await source_credentials.token_for([V2ECOLI])
    assert len(fake_github.minted) == 1
    await source_credentials.token_for([V2ECOLI], build_k8s.BUILD_TOKEN_LIFETIME_SECONDS)
    assert len(fake_github.minted) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case", "why"),
    [
        ("not installed", "GitHub gave no read access to vivarium-collective/{elsewhere}"),
        ("GitHub unavailable", "GitHub gave no read access"),
        ("two organizations", "one organization at a time"),
        ("not on GitHub", "not a GitHub repository"),
        ("not a token", "GitHub's answer for vivarium-collective/{v2ecoli} was not a token"),
    ],
)
async def test_no_token_is_had_for_what_the_app_cannot_read(case: str, why: str, fake_github: FakeGitHub) -> None:
    sources = [V2ECOLI]
    if case == "not installed":
        sources = [PrivateSource("https://github.com/vivarium-collective/elsewhere", "c" * 40)]
    elif case == "GitHub unavailable":
        fake_github.available = False
    elif case == "two organizations":
        sources = [V2ECOLI, PrivateSource("https://github.com/biosimulations/private", "c" * 40)]
    elif case == "not on GitHub":
        sources = [PrivateSource("https://gitlab.com/vivarium-collective/v2ecoli", V2ECOLI.commit)]
    elif case == "not a token":
        fake_github.malformed = True
    with pytest.raises(SourceCredentialsError) as refused:
        await source_credentials.token_for(sources)
    assert why in str(refused.value)
    assert "Bearer" not in str(refused.value) and "eyJ" not in str(refused.value)  # never the App's JWT
    assert fake_github.minted == (
        [] if case != "not a token" else [{"repositories": ["v2ecoli"], "permissions": {"contents": "read"}}]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case", "why"),
    [
        ("no App", "no GitHub App"),
        ("no key", "key could not be read: FileNotFoundError"),
        ("not a key", "not an RSA private key: InvalidKeyError"),
    ],
)
async def test_no_token_is_had_without_the_apps_id_and_key(
    case: str, why: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refused before anything is asked of GitHub (no stand-in for it here: a request would fail the test)."""
    monkeypatch.setattr(source_credentials, "_tokens", {})
    garbled = tmp_path / "garbled.pem"
    garbled.write_text("-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----\n")
    settings = {
        "no App": {"github_app_id": "", "github_app_key_file": str(garbled)},
        "no key": {"github_app_id": "424242", "github_app_key_file": str(tmp_path / "absent.pem")},
        "not a key": {"github_app_id": "424242", "github_app_key_file": str(garbled)},
    }[case]
    monkeypatch.setattr(source_credentials, "transport", httpx.MockTransport(lambda request: pytest.fail("asked")))
    with override_settings(**settings), pytest.raises(SourceCredentialsError, match=why) as refused:
        await source_credentials.token_for([V2ECOLI])
    assert str(garbled.read_text()).strip() not in str(refused.value)  # never the key


LockFunction = Callable[..., Awaitable[str]]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("lock", "printed"), [(build_k8s.lock_composed, build_k8s.LOCKED), (build_k8s.uv_lock, build_k8s.UV_LOCKED)]
)
async def test_only_a_private_versions_lock_jobs_read_a_secret_and_it_is_theirs(
    lock: LockFunction, printed: str, fake_github: FakeGitHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(BuildSite, "from_settings", classmethod(lambda cls, s: SITE))
    log = f"{build_k8s.INSPECT_MARKER} {printed}\nversion: 7\n\n{build_k8s.INSPECT_MARKER} end\n"
    sources: Sequence[PrivateSource]
    for sources in ((), (V2ECOLI,)):
        builds = RecordingBuilds(log)
        monkeypatch.setattr(build_k8s, "k8s_builds", lambda b=builds: b)
        assert await lock("[workspace]\n", PIXI_IMAGE, "abcde", sources, poll_seconds=0) == "version: 7\n"
        (job,) = builds.of("job")
        pod = job.spec.template.spec
        (container,) = pod.containers
        assert TOKEN not in serialized(job)
        if not sources:
            assert [kind for kind, _ in builds.calls] == ["job"]
            assert all(v.secret is None for v in pod.volumes)
            assert "GIT_CONFIG_GLOBAL" not in {e.name for e in container.env}
            continue
        assert [kind for kind, _ in builds.calls] == ["job", "secret"]  # the Job first: the Secret names it its owner
        (secret,) = builds.of("secret")
        (owner,) = secret.metadata.owner_references
        assert (owner.api_version, owner.kind, owner.name, owner.uid) == ("batch/v1", "Job", job.metadata.name, JOB_UID)
        assert not owner.block_owner_deletion  # more than the API's Role (secrets: create) may set
        assert secret.string_data == {
            "gitconfig": GITCONFIG,
            "credentials": f"username=x-access-token\npassword={TOKEN}\n",
        }
        (volume,) = [v for v in pod.volumes if v.secret is not None]
        assert volume.secret.secret_name == secret.metadata.name == f"{job.metadata.name}-git"
        (mount,) = [m for m in container.volume_mounts if m.name == volume.name]
        assert (mount.mount_path, mount.read_only) == (CREDENTIALS_DIR, True)
        assert {e.name: e.value for e in container.env}["GIT_CONFIG_GLOBAL"] == f"{CREDENTIALS_DIR}/gitconfig"
    assert [m["repositories"] for m in fake_github.minted] == [["v2ecoli"]]


@pytest.mark.asyncio
async def test_a_secret_that_cannot_be_made_takes_its_job_with_it(
    fake_github: FakeGitHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Its pod would wait for the Secret to mount until the Job's deadline: the Job is deleted instead, at once."""
    from kubernetes.client.exceptions import ApiException

    monkeypatch.setattr(BuildSite, "from_settings", classmethod(lambda cls, s: SITE))
    builds = RecordingBuilds(refuse_secrets=True)
    monkeypatch.setattr(build_k8s, "k8s_builds", lambda: builds)
    with pytest.raises(ApiException):
        await build_k8s.lock_composed("[workspace]\n", PIXI_IMAGE, "abcde", (V2ECOLI,), poll_seconds=0)
    (job,) = builds.of("job")
    assert builds.calls[1:] == [("delete", job.metadata.name)]


def _private(lock: str = "") -> PrivateBuild:
    return PrivateBuild(sources=(V2ECOLI,), pixi_image=PIXI_IMAGE, lock=lock)


def test_a_private_build_clones_unprivileged_and_its_privileged_build_never_mounts_the_token() -> None:
    definition = "Bootstrap: docker\nFrom: busybox\n"
    job: Any = build_job("build-abc-x", SITE, definition, Path("/p/abc.sif"), None, {"pixi.lock": "x"}, _private())
    pod = job.spec.template.spec
    clone, build = pod.init_containers
    assert (clone.name, clone.image) == ("clone", PIXI_IMAGE)
    assert clone.security_context.privileged is False and clone.security_context.run_as_user == 16997
    assert clone.security_context.allow_privilege_escalation is False
    assert {m.mount_path: m.read_only for m in clone.volume_mounts} == {"/work": None, CREDENTIALS_DIR: True}
    assert {e.name: e.value for e in clone.env} == {"GIT_CONFIG_GLOBAL": f"{CREDENTIALS_DIR}/gitconfig"}
    # the privileged build and the copy see the clones in the work volume, never the Secret
    assert build.security_context.privileged is True
    assert [m.mount_path for m in build.volume_mounts] == ["/work"]
    (copy,) = pod.containers
    assert CREDENTIALS_DIR not in [m.mount_path for m in copy.volume_mounts]
    assert "export APPTAINERENV_GIT_CONFIG_GLOBAL=/mnt/gitconfig\n" in build.command[-1]
    assert "apptainer build --bind /work/git:/mnt /work/image.sif /work/image.def" in build.command[-1]
    (secret,) = [v for v in pod.volumes if v.secret is not None]
    assert secret.secret.secret_name == "build-abc-x-git"  # noqa: S105 -- a Secret's name
    assert TOKEN not in serialized(job)

    public: Any = build_job("build-abc-x", SITE, definition, Path("/p/abc.sif"), None, {"pixi.lock": "x"})
    assert [c.name for c in public.spec.template.spec.init_containers] == ["build"]
    assert all(v.secret is None for v in public.spec.template.spec.volumes)
    assert "apptainer build /work/image.sif /work/image.def" in public.spec.template.spec.init_containers[0].command[-1]


def _git(env: dict[str, str], *args: str, stdin: str = "", cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 git, with arguments from test constants
        ["git", *args],  # noqa: S607 the PATH's git, as the Jobs' scripts run it
        input=stdin,
        env=env,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def _git_env(tmp_path: Path, config: Path, **more: str) -> dict[str, str]:
    """Only ``config``: no system or user gitconfig (a developer's credential helper), and no prompting."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return {
        "PATH": os.environ["PATH"], "HOME": str(home), "GIT_CONFIG_GLOBAL": str(config), "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0", **more,
    }  # fmt: skip


def test_the_credential_helper_gives_github_the_token_and_stores_nothing(tmp_path: Path) -> None:
    """The Secret's gitconfig, read by real git, with its directory moved here: git gets the token for github.com from
    the helper, and the helper ignores git's `store` and `erase` (the mount is read-only) without failing."""
    secret = tmp_path / "secret"
    secret.mkdir()
    credentials = secret / "credentials"
    credentials.write_text(f"username=x-access-token\npassword={TOKEN}\n")
    config = secret / "gitconfig"
    config.write_text(GITCONFIG.replace(CREDENTIALS_DIR, str(secret)))
    assert config.read_text() != GITCONFIG
    env = _git_env(tmp_path, config)
    asked = "protocol=https\nhost=github.com\npath=vivarium-collective/v2ecoli\n\n"
    filled = _git(env, "credential", "fill", stdin=asked)
    assert filled.returncode == 0, filled.stderr
    assert "username=x-access-token\n" in filled.stdout and f"password={TOKEN}\n" in filled.stdout
    for action in ("approve", "reject"):
        done = _git(env, "credential", action, stdin="protocol=https\nhost=github.com\nusername=u\npassword=p\n\n")
        assert done.returncode == 0, done.stderr
    assert sorted(p.name for p in secret.iterdir()) == ["credentials", "gitconfig"]
    assert credentials.read_text() == f"username=x-access-token\npassword={TOKEN}\n"
    elsewhere = _git(env, "credential", "fill", stdin="protocol=https\nhost=gitlab.com\npath=o/r\n\n")
    assert elsewhere.returncode != 0 and TOKEN not in elsewhere.stdout  # no other host is answered


def test_the_builds_gitconfig_sends_only_the_private_repositories_to_their_clones(tmp_path: Path) -> None:
    """git rewrites a URL by the longest matching prefix, so a locked repository the private one's URL is a prefix of
    (v2ecoli-extras) maps to itself, not to the clone."""
    extras = f"{V2ECOLI.url}-extras"
    lock = (
        f"- pypi: git+{V2ECOLI.url}?rev={V2ECOLI.commit}#{V2ECOLI.commit}\n"
        f"- pypi: git+{extras}?branch=main#{'d' * 40}\n"
        f"- pypi: git+https://github.com/vivarium-collective/process-bigraph.git?branch=main#{'e' * 40}\n"
    )
    config = tmp_path / "gitconfig"
    config.write_text(build_gitconfig(_private(lock)))
    env = _git_env(tmp_path, config)

    def rewritten(url: str) -> str:
        return _git(env, "ls-remote", "--get-url", url).stdout.strip()

    assert rewritten(V2ECOLI.url) == rewritten(f"{V2ECOLI.url}.git") == "file:///mnt/0"  # however a lock spells it
    assert rewritten(extras) == extras
    process_bigraph = "https://github.com/vivarium-collective/process-bigraph.git"
    assert rewritten(process_bigraph) == process_bigraph
    assert _git(env, "config", "--get", "safe.directory").stdout.strip() == "*"


def test_the_clone_fetches_each_locked_commit_and_writes_the_builds_gitconfig(tmp_path: Path) -> None:
    """The clone container's script, run by bash with real git; GitHub is a local repository whose main has moved past
    the locked commit, and the pixi that brings git in the Job is a stand-in that runs it."""
    origin = tmp_path / "origin"
    origin.mkdir()
    plain = _git_env(tmp_path, tmp_path / "none", GIT_AUTHOR_NAME="a", GIT_AUTHOR_EMAIL="a@a", GIT_COMMITTER_NAME="a",
                     GIT_COMMITTER_EMAIL="a@a")  # fmt: skip
    commits = []
    for n in range(2):
        (origin / "pyproject.toml").write_text(f'[project]\nname = "v2ecoli"\nversion = "0.{n}"\n')
        for args in (["init", "-q", "-b", "main"], ["add", "."], ["commit", "-qm", f"c{n}"]):
            assert _git(plain, *args, cwd=origin).returncode == 0
        commits.append(_git(plain, "rev-parse", "HEAD", cwd=origin).stdout.strip())
    private = PrivateBuild(sources=(PrivateSource(V2ECOLI.url, commits[0]),), pixi_image=PIXI_IMAGE, lock="")
    github = tmp_path / "github.gitconfig"
    github.write_text(
        f'[url "file://{origin}"]\n\tinsteadOf = {V2ECOLI.url}\n[uploadpack]\n\tallowAnySHA1InWant = true\n'
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "pixi").write_text('#!/bin/bash\n[ "$1" = exec ] || exit 2\nwhile [ "$1" != -- ]; do shift; done\n'
                                  'shift; exec "$@"\n')  # fmt: skip
    (bin_dir / "pixi").chmod(0o755)
    work = tmp_path / "work"
    env = _git_env(tmp_path, github, PATH=f"{bin_dir}:{os.environ['PATH']}")
    ran = subprocess.run(  # noqa: S603 the clone container's script, rendered from test constants
        ["/bin/bash", "-c", clone_script(private, str(work))], env=env, capture_output=True, text=True, check=False
    )
    assert ran.returncode == 0, ran.stderr
    assert _git(plain, "rev-parse", "FETCH_HEAD", cwd=work / "git" / "0").stdout.strip() == commits[0]
    assert (work / "git" / "gitconfig").read_text() == build_gitconfig(private)
    assert sorted(p.name for p in work.iterdir()) == ["git"]  # its home and pixi's cache are gone

    # the build's uv fetches the commit from the clone as it fetches from GitHub (its command, from the pinned pixi
    # image's lock log); the clone is shallow, so git keeps no ref for it, but the commit arrives, and uv uses that
    uv = tmp_path / "uv"
    assert _git(plain, "init", "-q", str(uv)).returncode == 0
    commit = commits[0]
    fetched = _git(
        plain, "fetch", "--force", "--update-head-ok", f"file://{work}/git/0", f"+{commit}:refs/commit/{commit}", cwd=uv
    )
    assert fetched.returncode == 0, fetched.stderr
    assert _git(plain, "cat-file", "-t", commit, cwd=uv).stdout.strip() == "commit"


def test_a_private_builds_log_includes_its_clone() -> None:
    """The build log route reads every container a build's pod has: the clone's too, where an expired token shows."""
    init: list[str] = []  # the pod's init containers
    read: list[str] = []

    def pods(namespace: str, label_selector: str) -> Any:
        spec = SimpleNamespace(
            init_containers=[SimpleNamespace(name=n) for n in init], containers=[SimpleNamespace(name="copy")]
        )
        return SimpleNamespace(items=[SimpleNamespace(metadata=SimpleNamespace(name="pod"), spec=spec)])

    def log(name: str, namespace: str, container: str, tail_lines: int) -> str:
        read.append(container)
        return f"{container} said so\n"

    builds = build_k8s.K8sBuilds.__new__(build_k8s.K8sBuilds)  # its API clients only, no cluster configuration
    builds.namespace = "ns"
    builds.core = cast(Any, SimpleNamespace(list_namespaced_pod=pods, read_namespaced_pod_log=log))
    for init[:], containers in ((["clone", "build"], ["clone", "build", "copy"]), (["build"], ["build", "copy"])):
        read.clear()
        text = builds.logs("build-abc-x")
        assert read == containers and all(f"{c} said so" in text for c in containers)
