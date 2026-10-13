"""Container builds as Kubernetes Jobs (`settings.build_backend = "k8s"`): the shared image (and any definition this
service builds) made where building is possible, then placed on the filesystem the SLURM nodes read.

Why: the SLURM build (`simulation_service.build_container`) runs `singularity build --fakeroot` on a build node, and
the service user has no subordinate id range there (`FATAL: could not use fakeroot: no mapping entry found in
/etc/subuid for svc_compose`, simulator 283, 2026-10-13). A definition with a `%post` needs mount namespaces to build,
so the build runs as root in a **privileged init container** that sees only scratch space and, read-only, the
definition file; the **unprivileged main container**, running as the service user with the shared filesystem
writable, copies the image into place. The privileged process never writes the filesystem the SLURM nodes read, and
the writer is the user whose files they are. Init containers run to completion in order, so a failed build fails the
pod and the Job.

The definition is written onto the shared filesystem through the API pod's own mount of it (`internal_mount_dir`),
and the Job mounts the claim at the path the SLURM nodes read it at, so every path in it is the path the SLURM job
script uses. The build is a run like any other (docs/plan-environment-builds.md, E1, E2): backend `k8s`, external id
the Job's name, its status updated by the job monitor through `K8sPoller`; the handler records the image it leaves.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING

from compose_api.common.hpc.models import SlurmJob
from compose_api.config import Settings, get_settings
from compose_api.db.services.hpc_db import HPCDatabaseService
from compose_api.simulation import images
from compose_api.simulation.hpc_utils import get_slurm_singularity_container_file, get_slurm_singularity_def_file
from compose_api.simulation.models import HpcRun, JobStatus, JobType, SimulatorVersion

if TYPE_CHECKING:
    from kubernetes.client import V1Job

logger = logging.getLogger(__name__)

WORK_DIR = "/work"
POLL_SECONDS = 10.0  # how often a waiter reads its build run's status
LABEL = "compose-api-build"


class BuildFailedError(RuntimeError):
    pass


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
        )


def build_script(definition: Path) -> str:
    """PRIVILEGED, as root, in scratch: the image built from the definition (read-only on the shared filesystem)."""
    return dedent(f"""\
        set -eu
        apptainer --version
        apptainer build {WORK_DIR}/image.sif "{definition}"
        ls -la {WORK_DIR}/image.sif
        """)


def publish_script(container: Path) -> str:
    """As the service user: the image written beside its target and renamed, so a reader never sees a partial one."""
    return dedent(f"""\
        set -eu
        id
        mkdir -p "{container.parent}"
        cp {WORK_DIR}/image.sif "{container}.part-$HOSTNAME"
        mv -f "{container}.part-$HOSTNAME" "{container}"
        ls -la "{container}"
        echo "Finished building container."
        """)


def build_job(name: str, site: BuildSite, definition: Path, container: Path) -> V1Job:
    """The build Job, as a value (what a test reads)."""
    from kubernetes import client as k8s

    shared = k8s.V1VolumeMount(name="shared", mount_path=site.pvc_mount_path, sub_path=site.pvc_sub_path or None)
    shared_read_only = k8s.V1VolumeMount(
        name="shared", mount_path=site.pvc_mount_path, sub_path=site.pvc_sub_path or None, read_only=True
    )
    work = k8s.V1VolumeMount(name="work", mount_path=WORK_DIR)
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
                            command=["/bin/bash", "-c", build_script(definition)],
                            security_context=k8s.V1SecurityContext(privileged=True, run_as_user=0),
                            volume_mounts=[shared_read_only, work],
                        )
                    ],
                    containers=[
                        k8s.V1Container(
                            name="copy",
                            image=site.image,
                            command=["/bin/bash", "-c", publish_script(container)],
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


async def submit_build(simulator_version: SimulatorVersion, hpc_db: HPCDatabaseService, suffix: str) -> HpcRun:
    """Write the definition onto the shared filesystem (through the API's mount of it), create the build Job, and
    record it as the simulator's build run: backend ``k8s``, external id the Job's name; the monitor polls it."""
    site = BuildSite.from_settings(get_settings())
    definition = get_slurm_singularity_def_file(singularity_hash=simulator_version.container_def_hash)
    container = get_slurm_singularity_container_file(singularity_hash=simulator_version.container_def_hash)
    local = images.internal_path(str(definition))
    if local is None:
        raise BuildFailedError(f"The store is not mounted here, so {definition} cannot be written for a build Job")
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(simulator_version.container_def.representation)
    name = job_name(simulator_version, suffix)
    await asyncio.to_thread(k8s_builds().create, build_job(name, site, definition, container))
    logger.info("Submitted container build %s as a Kubernetes Job (%s -> %s)", name, definition, container)
    return await hpc_db.insert_hpcrun(
        slurmjobid=None, job_type=JobType.BUILD_CONTAINER, ref_id=simulator_version.database_id,
        correlation_id=f"build_container-{name}", backend="k8s", external_id=name,
    )  # fmt: skip


async def wait_for_build(run: HpcRun, hpc_db: HPCDatabaseService) -> HpcRun:
    """Wait for the monitor to see the build finish, reading its status in the database (any API process may wait on
    a build another started). `BuildFailedError` with the pods' logs if it fails or outlives its deadline."""
    timeout = get_settings().build_k8s_timeout_seconds + 300
    deadline = datetime.datetime.now() + datetime.timedelta(seconds=timeout)
    current: HpcRun | None = run
    while current is not None and current.status not in (JobStatus.COMPLETED, JobStatus.FAILED):
        if datetime.datetime.now() > deadline:
            break
        await asyncio.sleep(POLL_SECONDS)
        current = await hpc_db.get_hpcrun(run.database_id)
    if current is not None and current.status == JobStatus.COMPLETED:
        return current
    status = current.status if current is not None else "missing"
    try:
        logs = await asyncio.to_thread(k8s_builds().logs, run.external_id or "")
    except Exception as e:
        logs = f"(no logs: {type(e).__name__}: {e})"
    raise BuildFailedError(f"Container build Job {run.external_id} {status}\n{logs[-4000:]}")


async def build_and_wait(simulator_version: SimulatorVersion, hpc_db: HPCDatabaseService, suffix: str) -> HpcRun:
    return await wait_for_build(await submit_build(simulator_version, hpc_db, suffix), hpc_db)
