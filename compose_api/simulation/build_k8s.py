"""Container builds as Kubernetes Jobs (`settings.build_backend = "k8s"`): the shared image (and any definition this
service builds) made where building is possible, then placed on the filesystem the SLURM nodes read.

Why: the SLURM build (`simulation_service.build_container`) runs `singularity build --fakeroot` on a build node, and the
service user has no subordinate id range there (`FATAL: could not use fakeroot: no mapping entry found in /etc/subuid
for svc_compose`, simulator 283, 2026-10-13). A definition with a `%post` needs mount namespaces to build, so the build
runs as root in a **privileged init container** that sees only scratch space, the definition handed to it in the Job
itself (an environment variable); the **unprivileged main container**, running as the service user with the shared
filesystem writable, copies the image into place. The privileged process never writes the filesystem the SLURM nodes
read, and the writer is the user whose files they are. Init containers run to completion in order, so a failed build
fails the pod and the Job.

The privileged container mounts nothing of the shared filesystem: a definition file there may be owned by another user
(the SLURM path wrote them over SSH; simulation 4580 failed rewriting one), and root on a shared filesystem is squashed
anyway. Only the copy mounts the claim, at the path the SLURM nodes read it at, so the image lands at the path the SLURM
job script uses. The build is a run like any other (docs/plan-environment-builds.md, E1, E2): backend `k8s`, external id
the Job's name, its status updated by the job monitor through `K8sPoller`; the handler records the image it leaves.
"""

from __future__ import annotations

import asyncio
import base64
import datetime
import hashlib
import logging
import shlex
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING

from compose_api.common.hpc.models import SlurmJob
from compose_api.config import Settings, get_settings
from compose_api.db.services.hpc_db import HPCDatabaseService
from compose_api.simulation.builds import BuildFailedError, wait_for_run
from compose_api.simulation.hpc_utils import get_image_inspection_file, get_slurm_singularity_container_file
from compose_api.simulation.models import EnvironmentVersion, HpcRun, JobType, SimulatorVersion

if TYPE_CHECKING:
    from kubernetes.client import V1Job

logger = logging.getLogger(__name__)

WORK_DIR = "/work"
SCRATCH_DIR = "/scratch"  # an inspection Job's only writable volume
LABEL = "compose-api-build"


@dataclass(frozen=True)
class BuildSite:
    """Where a build Job runs and whom it writes as: the Apptainer image, the claim on the shared filesystem and
    where it is mounted (the path the SLURM nodes read it at), and the service user."""

    namespace: str
    image: str
    pvc_claim: str
    pvc_mount_path: str
    pvc_sub_path: str
    run_as_uid: int
    run_as_gid: int
    supplemental_groups: tuple[int, ...]
    timeout_seconds: int
    ephemeral_storage: str = ""

    @classmethod
    def from_settings(cls, s: Settings) -> BuildSite:
        if not s.build_k8s_pvc_claim or not s.build_k8s_pvc_mount_path:
            raise ValueError("build_backend=k8s needs build_k8s_pvc_claim and build_k8s_pvc_mount_path")
        groups = tuple(int(g) for g in s.build_k8s_supplemental_groups.replace(" ", "").split(",") if g)
        return cls(
            namespace=s.build_k8s_namespace,
            image=s.build_k8s_image,
            pvc_claim=s.build_k8s_pvc_claim,
            pvc_mount_path=s.build_k8s_pvc_mount_path,
            pvc_sub_path=s.build_k8s_pvc_sub_path,
            run_as_uid=s.build_k8s_run_as_uid,
            run_as_gid=s.build_k8s_run_as_gid,
            supplemental_groups=groups,
            timeout_seconds=s.build_k8s_timeout_seconds,
            ephemeral_storage=s.build_k8s_ephemeral_storage,
        )


DEFINITION_ENV = "CONTAINER_DEFINITION_B64"
DESCRIBE_ENV = "DESCRIBE_SCRIPT_B64"
#: what a build reads from the image it made, by file kind (docs/plan-environment-versions.md, V7)
INSPECTIONS = ("installed.txt", "interfaces.json")

# The Python distributions an image holds, read with its own interpreter (standard library only).
_INSTALLED = """\
import importlib.metadata as m
names = {f"{d.metadata['Name']}=={d.version}" for d in m.distributions() if d.metadata['Name']}
print("\\n".join(sorted(names, key=str.lower)))
"""


@dataclass(frozen=True)
class Inspection:
    """Reading back an environment version's image once it is built: its environment's Python (the command that
    enters it), the module roots to describe and the label the manifest carries, and the describe script itself
    (process-bigraph-lang's, standard library only; None reads the installed packages only)."""

    python: tuple[str, ...]
    roots: tuple[str, ...]
    environment: str
    label: str
    describe_script: str | None = None


def inspect_script(inspection: Inspection) -> str:
    """PRIVILEGED, after the build: the image run with its own Python, to list what it installed and describe its
    process interfaces. Best effort: a failure leaves that file out and never fails the build."""
    python = shlex.join(inspection.python)
    run = f"apptainer exec --bind {WORK_DIR} {WORK_DIR}/image.sif {python}"
    describe = shlex.join([*inspection.roots, "--env-name", inspection.environment, "--image", inspection.label])
    return dedent(f"""\
        cat > {WORK_DIR}/installed.py <<'COMPOSE_API_INSTALLED'
        {{installed}}COMPOSE_API_INSTALLED
        {run} {WORK_DIR}/installed.py > {WORK_DIR}/image.installed.txt \\
          || {{ echo "could not list the installed packages" >&2; rm -f {WORK_DIR}/image.installed.txt; }}
        if [ -n "${{{DESCRIBE_ENV}:-}}" ]; then
          echo "${DESCRIBE_ENV}" | base64 -d > {WORK_DIR}/describe_env.py
          {run} {WORK_DIR}/describe_env.py {describe} > {WORK_DIR}/image.interfaces.json \\
            || {{ echo "could not describe the interfaces" >&2; rm -f {WORK_DIR}/image.interfaces.json; }}
        fi
        """).replace("{installed}", _INSTALLED)


INSPECT_CONTAINER = "inspect"
INSPECT_MARKER = "===compose-api-inspection"
INSTALLED_ENV = "INSTALLED_SCRIPT_B64"


def prebuilt_inspect_script(inspection: Inspection) -> str:
    """Inside a prebuilt image, unprivileged, with nothing mounted but scratch: the same two readings as a build's
    (``inspect_script``), printed between markers, since a log is all such a Job leaves. Best effort, as there."""
    python = shlex.join(inspection.python)
    describe = shlex.join([*inspection.roots, "--env-name", inspection.environment, "--image", inspection.label])
    return dedent(f"""\
        cd {SCRATCH_DIR}
        echo "${INSTALLED_ENV}" | base64 -d > installed.py
        {python} {SCRATCH_DIR}/installed.py > installed.txt 2> installed.err || rm -f installed.txt
        if [ -n "${{{DESCRIBE_ENV}:-}}" ]; then
          echo "${DESCRIBE_ENV}" | base64 -d > describe_env.py
          {python} {SCRATCH_DIR}/describe_env.py {describe} > interfaces.json 2> interfaces.err || rm -f interfaces.json
        fi
        for kind in {" ".join(INSPECTIONS)}; do
          if [ -f "$kind" ]; then echo "{INSPECT_MARKER} $kind"; cat "$kind"; echo; fi
        done
        echo "{INSPECT_MARKER} end"
        cat installed.err interfaces.err 2>/dev/null | tail -20 >&2 || true
        """)


def read_inspection_log(log: str) -> dict[str, str]:
    """The files ``prebuilt_inspect_script`` printed, by kind; only those it reached the end of."""
    found: dict[str, str] = {}
    kind: str | None = None
    lines: list[str] = []
    for line in log.splitlines():
        if line.startswith(INSPECT_MARKER + " "):
            if kind is not None:
                found[kind] = "\n".join(lines).rstrip("\n") + "\n"
            kind, lines = line.removeprefix(INSPECT_MARKER + " ").strip(), []
            if kind == "end":
                return found
        elif kind is not None:
            lines.append(line)
    return {}  # cut off before the end: nothing is trusted


def inspection_job(name: str, site: BuildSite, image: str, inspection: Inspection) -> V1Job:
    """A Job that runs a prebuilt image to read it back: unprivileged, as the service user, no service account token,
    nothing mounted but scratch (the image is an owner's; it is trusted to run documents, nothing more)."""
    env = {INSTALLED_ENV: base64.b64encode(_INSTALLED.encode()).decode()}
    if inspection.describe_script is not None:
        env[DESCRIBE_ENV] = base64.b64encode(inspection.describe_script.encode()).decode()
    return _scratch_job(name, site, image, prebuilt_inspect_script(inspection), env, deadline_seconds=900)


def _scratch_job(
    name: str, site: BuildSite, image: str, script: str, env: dict[str, str], deadline_seconds: int
) -> V1Job:
    """A Job of one unprivileged container: the service user, no service account token, nothing mounted but an
    emptyDir at ``SCRATCH_DIR``; what it produces it prints, between ``INSPECT_MARKER`` lines (``read_inspection_log``),
    since its log is all it leaves."""
    from kubernetes import client as k8s

    labels = {"app": LABEL, "compose-api-build": name}
    return k8s.V1Job(
        metadata=k8s.V1ObjectMeta(name=name, labels=labels),
        spec=k8s.V1JobSpec(
            backoff_limit=0,
            ttl_seconds_after_finished=3600,
            active_deadline_seconds=deadline_seconds,
            template=k8s.V1PodTemplateSpec(
                metadata=k8s.V1ObjectMeta(labels=labels),
                spec=k8s.V1PodSpec(
                    restart_policy="Never",
                    node_selector={"vlan": "internal"},
                    automount_service_account_token=False,
                    containers=[
                        k8s.V1Container(
                            name=INSPECT_CONTAINER,
                            image=image,
                            command=["/bin/bash", "-c", script],
                            env=[k8s.V1EnvVar(name=k, value=v) for k, v in env.items()],
                            security_context=k8s.V1SecurityContext(
                                privileged=False,
                                run_as_user=site.run_as_uid or None,
                                run_as_group=site.run_as_gid or None,
                                run_as_non_root=bool(site.run_as_uid),
                                allow_privilege_escalation=False,
                            ),
                            volume_mounts=[k8s.V1VolumeMount(name="scratch", mount_path=SCRATCH_DIR)],
                        )
                    ],
                    volumes=[k8s.V1Volume(name="scratch", empty_dir=k8s.V1EmptyDirVolumeSource())],
                ),
            ),
        ),
    )


PIXI_TOML_ENV = "PIXI_TOML_B64"
LOCKED = "pixi.lock"
LOCK_ERROR = "lock.err"


def lock_script() -> str:
    """Inside the pixi image, unprivileged, in scratch: lock the workspace the Job carries (base64, in the env) and
    print the lock, or why it did not resolve. Locking reads packages' metadata, which can run their build code: it
    happens here, never in the API pod."""
    return dedent(f"""        set -u
        cd {SCRATCH_DIR}
        export HOME={SCRATCH_DIR} PIXI_CACHE_DIR={SCRATCH_DIR}/cache RATTLER_CACHE_DIR={SCRATCH_DIR}/cache \
          UV_CACHE_DIR={SCRATCH_DIR}/uv
        echo "${PIXI_TOML_ENV}" | base64 -d > pixi.toml
        if pixi lock > lock.out 2> {LOCK_ERROR}; then kind={LOCKED}; else kind={LOCK_ERROR}; fi
        echo "{INSPECT_MARKER} $kind"
        cat "$kind"
        echo
        echo "{INSPECT_MARKER} end"
        """)


def lock_job(name: str, site: BuildSite, pixi_image: str, toml: str) -> V1Job:
    """The Job that locks a composed environment's ``pixi.toml`` (docs/plan-environment-composition.md, step 3)."""
    env = {PIXI_TOML_ENV: base64.b64encode(toml.encode()).decode()}
    return _scratch_job(name, site, pixi_image, lock_script(), env, deadline_seconds=1800)


class LockFailedError(Exception):
    """The workspace did not resolve; the message is pixi's explanation (the conflicting requirements)."""


async def lock_composed(toml: str, pixi_image: str, suffix: str, poll_seconds: float = 5.0) -> str:
    """Lock ``toml`` in a Job of its own and wait for it: the ``pixi.lock`` text. `LockFailedError` when it does not
    resolve, with pixi's explanation; `RuntimeError` when the Job failed without saying."""
    site = BuildSite.from_settings(get_settings())
    name = f"lock-{hashlib.sha256(toml.encode()).hexdigest()[:12]}-{suffix.lower()[:5]}"
    builds = k8s_builds()
    await asyncio.to_thread(builds.create, lock_job(name, site, pixi_image, toml))
    deadline = asyncio.get_running_loop().time() + 1860
    state = "running"
    while state == "running" and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(poll_seconds)
        state, why = await asyncio.to_thread(builds.state, name)
        if state == "failed":
            logger.warning(f"Lock Job {name} failed: {why}")
    found = read_inspection_log(await asyncio.to_thread(builds.container_log, name, INSPECT_CONTAINER))
    if LOCKED in found:
        return found[LOCKED]
    if LOCK_ERROR in found:
        raise LockFailedError(found[LOCK_ERROR].strip()[-4000:])
    raise RuntimeError(f"lock Job {name} ended ({state}) without a lock or an explanation")


async def inspect_prebuilt(
    image: str, inspection: Inspection, suffix: str, poll_seconds: float = 5.0
) -> dict[str, str]:
    """Run ``image``'s inspection Job and wait for it: the files it printed, by kind ({} when it failed)."""
    site = BuildSite.from_settings(get_settings())
    digest = image.rpartition("@sha256:")[2][:12] or "image"
    name = f"inspect-{digest}-{suffix.lower()[:5]}"
    builds = k8s_builds()
    await asyncio.to_thread(builds.create, inspection_job(name, site, image, inspection))
    deadline = asyncio.get_running_loop().time() + 960
    state = "running"
    while state == "running" and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(poll_seconds)
        state, why = await asyncio.to_thread(builds.state, name)
        if state == "failed":
            logger.warning(f"Inspection Job {name} failed: {why}")
    log = await asyncio.to_thread(builds.container_log, name, INSPECT_CONTAINER)
    return read_inspection_log(log)


def build_script() -> str:
    """PRIVILEGED, as root, in scratch: the image built from the definition the Job carries (base64, in the env).
    Apptainer's temporary sandbox and its cache go in the scratch volume too, not the container's own /tmp and /root,
    so everything the build writes is the volume the Job requests ephemeral storage for."""
    return dedent(f"""\
        set -eu
        export APPTAINER_TMPDIR={WORK_DIR}/scratch APPTAINER_CACHEDIR={WORK_DIR}/cache
        mkdir -p "$APPTAINER_TMPDIR" "$APPTAINER_CACHEDIR"
        apptainer --version
        echo "${DEFINITION_ENV}" | base64 -d > {WORK_DIR}/image.def
        apptainer build {WORK_DIR}/image.sif {WORK_DIR}/image.def
        ls -la {WORK_DIR}/image.sif
        """)


def _publish_inspections(inspections: dict[str, Path]) -> str:
    """Each file read from the image (file kind -> its target) written beside its target and renamed, if it was."""
    return "".join(
        f'if [ -f {WORK_DIR}/image.{kind} ]; then cp {WORK_DIR}/image.{kind} "{target}.part-$HOSTNAME" && '
        f'mv -f "{target}.part-$HOSTNAME" "{target}"; fi\n'
        for kind, target in inspections.items()
    )


def publish_script(container: Path, inspections: dict[str, Path] | None = None) -> str:
    """As the service user: the image written beside its target and renamed, so a reader never sees a partial one;
    then whatever the build read from it (``inspections``: file kind -> its target), each only if it was written."""
    extra = _publish_inspections(inspections or {})
    return (
        dedent(f"""\
        set -eu
        id
        mkdir -p "{container.parent}"
        cp {WORK_DIR}/image.sif "{container}.part-$HOSTNAME"
        mv -f "{container}.part-$HOSTNAME" "{container}"
        ls -la "{container}"
        """)
        + extra
        + 'echo "Finished building container."\n'
    )


def build_job(
    name: str, site: BuildSite, definition: str, container: Path, inspection: Inspection | None = None
) -> V1Job:
    """The build Job, as a value (what a test reads). With ``inspection``, the image is read back once built, and
    what was read is placed beside it (``get_image_inspection_file``)."""
    from kubernetes import client as k8s

    script, env = (
        build_script(),
        [k8s.V1EnvVar(name=DEFINITION_ENV, value=base64.b64encode(definition.encode()).decode())],
    )
    inspections: dict[str, Path] = {}
    if inspection is not None:
        script += inspect_script(inspection)
        if inspection.describe_script is not None:
            encoded = base64.b64encode(inspection.describe_script.encode()).decode()
            env.append(k8s.V1EnvVar(name=DESCRIBE_ENV, value=encoded))
        stem = container.name.removesuffix(".sif")
        inspections = {kind: get_image_inspection_file(stem, kind) for kind in INSPECTIONS}

    shared = k8s.V1VolumeMount(name="shared", mount_path=site.pvc_mount_path, sub_path=site.pvc_sub_path or None)
    work = k8s.V1VolumeMount(name="work", mount_path=WORK_DIR)
    # A request, not a limit: the scheduler places the build on a node with that much disk free (k8s-wn-02 filled up
    # mid-build on 2026-10-24, "[Errno 28] No space left on device"), and a build that needs more is not evicted.
    scratch = (
        k8s.V1ResourceRequirements(requests={"ephemeral-storage": site.ephemeral_storage})
        if site.ephemeral_storage
        else None
    )
    labels = {"app": LABEL, "compose-api-build": name}
    return k8s.V1Job(
        metadata=k8s.V1ObjectMeta(name=name, labels=labels),
        spec=k8s.V1JobSpec(
            backoff_limit=0,  # a failed build is reported, not retried behind the caller's back
            ttl_seconds_after_finished=86400,
            active_deadline_seconds=site.timeout_seconds,
            template=k8s.V1PodTemplateSpec(
                metadata=k8s.V1ObjectMeta(labels=labels),
                spec=k8s.V1PodSpec(
                    restart_policy="Never",
                    node_selector={"vlan": "internal"},
                    security_context=k8s.V1PodSecurityContext(
                        fs_group=site.run_as_gid or None, supplemental_groups=list(site.supplemental_groups) or None
                    ),
                    init_containers=[
                        k8s.V1Container(
                            name="build",
                            image=site.image,
                            command=["/bin/bash", "-c", script],
                            env=env,
                            security_context=k8s.V1SecurityContext(privileged=True, run_as_user=0),
                            resources=scratch,
                            volume_mounts=[work],
                        )
                    ],
                    containers=[
                        k8s.V1Container(
                            name="copy",
                            image=site.image,
                            command=["/bin/bash", "-c", publish_script(container, inspections)],
                            security_context=k8s.V1SecurityContext(
                                privileged=False,
                                run_as_user=site.run_as_uid,
                                run_as_group=site.run_as_gid,
                                run_as_non_root=bool(site.run_as_uid),
                                allow_privilege_escalation=False,
                            ),
                            volume_mounts=[shared, work],
                        )
                    ],
                    volumes=[
                        k8s.V1Volume(
                            name="shared",
                            persistent_volume_claim=k8s.V1PersistentVolumeClaimVolumeSource(claim_name=site.pvc_claim),
                        ),
                        k8s.V1Volume(name="work", empty_dir=k8s.V1EmptyDirVolumeSource()),
                    ],
                ),
            ),
        ),
    )


def _reread_setup() -> str:
    """As in ``build_script``: Apptainer's temporary files in the work volume, not the container's /tmp and /root."""
    return dedent(f"""\
        set -u
        export APPTAINER_TMPDIR={WORK_DIR}/scratch APPTAINER_CACHEDIR={WORK_DIR}/cache
        mkdir -p "$APPTAINER_TMPDIR" "$APPTAINER_CACHEDIR"
        """)


def reread_job(name: str, site: BuildSite, container: Path, inspection: Inspection) -> V1Job:
    """A Job that reads back a shared image already built, as its build would have (``inspect_script``): for a version
    whose image was built before builds read images back. As in a build, the privileged container sees only the work
    volume: the service user copies the image in from the shared filesystem (read-only), and places what was read
    beside it."""
    from kubernetes import client as k8s

    env = []
    if inspection.describe_script is not None:
        encoded = base64.b64encode(inspection.describe_script.encode()).decode()
        env.append(k8s.V1EnvVar(name=DESCRIBE_ENV, value=encoded))
    stem = container.name.removesuffix(".sif")
    inspections = {kind: get_image_inspection_file(stem, kind) for kind in INSPECTIONS}
    service_user = k8s.V1SecurityContext(
        privileged=False,
        run_as_user=site.run_as_uid,
        run_as_group=site.run_as_gid,
        run_as_non_root=bool(site.run_as_uid),
        allow_privilege_escalation=False,
    )
    shared = k8s.V1VolumeMount(name="shared", mount_path=site.pvc_mount_path, sub_path=site.pvc_sub_path or None)
    shared_read_only = k8s.V1VolumeMount(
        name="shared", mount_path=site.pvc_mount_path, sub_path=site.pvc_sub_path or None, read_only=True
    )
    work = k8s.V1VolumeMount(name="work", mount_path=WORK_DIR)
    scratch = (
        k8s.V1ResourceRequirements(requests={"ephemeral-storage": site.ephemeral_storage})
        if site.ephemeral_storage
        else None
    )
    labels = {"app": LABEL, "compose-api-build": name}
    return k8s.V1Job(
        metadata=k8s.V1ObjectMeta(name=name, labels=labels),
        spec=k8s.V1JobSpec(
            backoff_limit=0,
            ttl_seconds_after_finished=3600,
            active_deadline_seconds=1800,
            template=k8s.V1PodTemplateSpec(
                metadata=k8s.V1ObjectMeta(labels=labels),
                spec=k8s.V1PodSpec(
                    restart_policy="Never",
                    node_selector={"vlan": "internal"},
                    security_context=k8s.V1PodSecurityContext(
                        fs_group=site.run_as_gid or None, supplemental_groups=list(site.supplemental_groups) or None
                    ),
                    init_containers=[
                        k8s.V1Container(
                            name="fetch",
                            image=site.image,
                            command=["/bin/bash", "-c", f'set -eu\ncp "{container}" {WORK_DIR}/image.sif\n'],
                            security_context=service_user,
                            resources=scratch,
                            volume_mounts=[shared_read_only, work],
                        ),
                        k8s.V1Container(
                            name=INSPECT_CONTAINER,
                            image=site.image,
                            command=["/bin/bash", "-c", _reread_setup() + inspect_script(inspection)],
                            env=env,
                            security_context=k8s.V1SecurityContext(privileged=True, run_as_user=0),
                            volume_mounts=[work],
                        ),
                    ],
                    containers=[
                        k8s.V1Container(
                            name="copy",
                            image=site.image,
                            command=["/bin/bash", "-c", "set -eu\n" + _publish_inspections(inspections)],
                            security_context=service_user,
                            volume_mounts=[shared, work],
                        )
                    ],
                    volumes=[
                        k8s.V1Volume(
                            name="shared",
                            persistent_volume_claim=k8s.V1PersistentVolumeClaimVolumeSource(claim_name=site.pvc_claim),
                        ),
                        k8s.V1Volume(name="work", empty_dir=k8s.V1EmptyDirVolumeSource()),
                    ],
                ),
            ),
        ),
    )


async def reread_shared(singularity_hash: str, inspection: Inspection, suffix: str, poll_seconds: float = 5.0) -> bool:
    """Run the read-back Job for the shared image ``singularity_hash`` and wait for it: whether it completed (what it
    read is then beside the image)."""
    site = BuildSite.from_settings(get_settings())
    container = get_slurm_singularity_container_file(singularity_hash=singularity_hash)
    name = f"reread-{singularity_hash[:12]}-{suffix.lower()[:5]}"
    builds = k8s_builds()
    await asyncio.to_thread(builds.create, reread_job(name, site, container, inspection))
    deadline = asyncio.get_running_loop().time() + 1860
    state = "running"
    while state == "running" and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(poll_seconds)
        state, why = await asyncio.to_thread(builds.state, name)
        if state == "failed":
            logger.warning(f"Read-back Job {name} failed: {why}")
    return state == "completed"


class K8sBuilds:
    """Create a build Job, read its state and its pods' logs (the API pod's service account, in its namespace)."""

    def __init__(self, namespace: str) -> None:
        from kubernetes import client as k8s
        from kubernetes import config as k8s_config

        try:
            k8s_config.load_incluster_config()  # type: ignore[no-untyped-call]
        except k8s_config.ConfigException:
            k8s_config.load_kube_config()  # type: ignore[no-untyped-call]
        self.namespace = namespace
        self.batch = k8s.BatchV1Api()
        self.core = k8s.CoreV1Api()

    def create(self, job: V1Job) -> None:
        self.batch.create_namespaced_job(namespace=self.namespace, body=job)

    def state(self, name: str) -> tuple[str, str]:
        """`running`, `completed` or `failed`, and why when it failed. A Job whose pod cannot be created (refused by
        the namespace's admission policy, say) has no condition, only `FailedCreate` events: that is a failure too."""
        job = self.batch.read_namespaced_job_status(name=name, namespace=self.namespace)
        for condition in (job.status.conditions or []) if job.status else []:
            if condition.status == "True" and condition.type == "Complete":
                return "completed", ""
            if condition.status == "True" and condition.type == "Failed":
                return "failed", condition.message or condition.reason or ""
        if not (job.status and (job.status.active or job.status.succeeded or job.status.failed)):
            events = self.core.list_namespaced_event(
                namespace=self.namespace, field_selector=f"involvedObject.name={name},reason=FailedCreate"
            )
            if events.items:
                return "failed", events.items[-1].message or "the build pod could not be created"
        return "running", ""

    def logs(self, name: str) -> str:
        """The build's pods' logs, both containers, for the build log route and failures."""
        pods = self.core.list_namespaced_pod(namespace=self.namespace, label_selector=f"compose-api-build={name}")
        out: list[str] = []
        for pod in pods.items:
            pod_name = pod.metadata.name if pod.metadata is not None else None
            if not pod_name:
                continue
            for container in ("build", "copy"):
                try:
                    text = self.core.read_namespaced_pod_log(
                        name=pod_name, namespace=self.namespace, container=container, tail_lines=400
                    )
                except Exception as e:  # a container that never started has no log
                    text = f"({type(e).__name__}: {e})"
                out.append(f"== {pod_name} / {container} ==\n{text}")
        return "\n".join(out)

    def container_log(self, name: str, container: str) -> str:
        """One container's whole log, from the Job's newest pod ("" when it has none)."""
        pods = self.core.list_namespaced_pod(namespace=self.namespace, label_selector=f"compose-api-build={name}")
        names = [p.metadata.name for p in pods.items if p.metadata is not None and p.metadata.name]
        if not names:
            return ""
        log: str = self.core.read_namespaced_pod_log(name=names[-1], namespace=self.namespace, container=container)
        return log


_builds: K8sBuilds | None = None


def k8s_builds() -> K8sBuilds:
    global _builds
    if _builds is None:
        _builds = K8sBuilds(get_settings().build_k8s_namespace)
    return _builds


class K8sPoller:
    """The monitor's view of build Jobs (docs/plan-environment-builds.md, E2): each Job's state as a SlurmJob."""

    async def states(self, external_ids: list[str]) -> dict[str, SlurmJob]:
        builds = k8s_builds()
        found: dict[str, SlurmJob] = {}
        for name in external_ids:
            try:
                state, _why = await asyncio.to_thread(builds.state, name)
            except Exception as e:
                if getattr(e, "status", None) == 404:  # the Job is gone (expired, deleted): it cannot finish now
                    state = "failed"
                else:
                    raise
            found[name] = SlurmJob(
                job_id=0, name=name, account="k8s", user_name="k8s", job_state=_JOB_STATES[state],
                end_time=None if state == "running" else datetime.datetime.now().isoformat(timespec="seconds"),
            )  # fmt: skip
        return found


_JOB_STATES = {"running": "RUNNING", "completed": "COMPLETED", "failed": "FAILED"}


def job_name(simulator_version: SimulatorVersion, suffix: str) -> str:
    return f"build-{simulator_version.container_def_hash[:12]}-{suffix.lower()[:5]}"


_describe_scripts: dict[str, str] = {}


async def describe_script() -> str | None:
    """process-bigraph-lang's describe script at the commit ``environments.yaml`` pins, fetched once; None when it
    cannot be fetched (the build then lists the installed packages only)."""
    import httpx

    from compose_api.registry.environments import load_environments

    url = load_environments().describe.raw_url
    if url not in _describe_scripts:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(url)
                response.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning(f"The describe script could not be fetched ({url}): {e}")
            return None
        _describe_scripts[url] = response.text
    return _describe_scripts[url]


async def inspection_of(version: EnvironmentVersion) -> Inspection | None:
    """How to read back a version's image: its environment's Python and module roots (None for an environment
    ``environments.yaml`` does not list). A prebuilt manifest names the image; a shared one, the version."""
    from compose_api.registry.environments import load_environments, module_roots

    spec = next((e for e in load_environments().environments if e.name == version.environment), None)
    if spec is None:
        return None
    from compose_api.environments import pixi

    roots = tuple(module_roots(spec.name))
    # a composed image (runtime contract 2) is entered through pixi's activation, whatever the environment's other
    # versions use
    python = pixi.PYTHON if version.runtime_contract == pixi.RUNTIME_CONTRACT else tuple(spec.python)
    return Inspection(
        python=python,
        roots=roots,
        environment=spec.name,
        label=version.image or version.label,
        describe_script=await describe_script() if roots else None,
    )


async def inspection_for(simulator_version: SimulatorVersion) -> Inspection | None:
    """How to read back the image of an environment version's simulator; None for a simulator no version names."""
    from compose_api.dependencies import get_database_service  # late: dependencies imports the simulation modules

    database_service = get_database_service()
    if database_service is None:
        return None
    version = await database_service.get_environments_db().of_simulator(simulator_version.database_id)
    return await inspection_of(version) if version is not None else None


async def submit_build(simulator_version: SimulatorVersion, hpc_db: HPCDatabaseService, suffix: str) -> HpcRun:
    """Create the build Job, carrying the definition, and record it as the simulator's build run: backend ``k8s``,
    external id the Job's name; the monitor polls it. An environment version's image is read back once built."""
    site = BuildSite.from_settings(get_settings())
    container = get_slurm_singularity_container_file(singularity_hash=simulator_version.container_def_hash)
    name = job_name(simulator_version, suffix)
    inspection = await inspection_for(simulator_version)
    job = build_job(name, site, simulator_version.container_def.representation, container, inspection)
    await asyncio.to_thread(k8s_builds().create, job)
    logger.info("Submitted container build %s as a Kubernetes Job (-> %s)", name, container)
    return await hpc_db.insert_hpcrun(
        slurmjobid=None, job_type=JobType.BUILD_CONTAINER, ref_id=simulator_version.database_id,
        correlation_id=f"build_container-{name}", backend="k8s", external_id=name,
    )  # fmt: skip


async def wait_for_build(run: HpcRun, hpc_db: HPCDatabaseService) -> HpcRun:
    """Wait for the monitor to see the build finish (`builds.wait_for_run`); on failure, the pods' logs too."""
    try:
        return await wait_for_run(run, hpc_db)
    except BuildFailedError as e:
        try:
            logs = await asyncio.to_thread(k8s_builds().logs, run.external_id or "")
        except Exception as le:
            logs = f"(no logs: {type(le).__name__}: {le})"
        raise BuildFailedError(f"{e}\n{logs[-4000:]}") from e


async def build_and_wait(simulator_version: SimulatorVersion, hpc_db: HPCDatabaseService, suffix: str) -> HpcRun:
    return await wait_for_build(await submit_build(simulator_version, hpc_db, suffix), hpc_db)
