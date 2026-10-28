"""The verification step of the submission worker (docs/plan-verify-oracle.md, V3).

A verification moves ``requested -> submitted -> completed | failed``, one short step per lease, each committing its
own state, so a restart resumes it with the same ``workflow_id``:

- **requested:** read the comparison's archive (`source.omex`, the `sedml-omex` dataset of its first member), drop
  manifest entries for files it lacks (D4, amended), and `POST /verify/omex` within the rate budget.
- **submitted:** `GET /verify/{workflow_id}` every ``verify_poll_seconds``, until it is done or the deadline passes.
- **completed:** each BioSimulators simulator's reports become a reference on the comparison (D1), the comparison is
  scored again so ``close_to_references`` covers them, and ``verify_close`` records whether the simulators agree.

Asking to verify a comparison again resumes a verification that failed while biosim was still working on it (past
the deadline, or out of attempts reading it), with the same ``workflow_id``. A 429 waits out its ``Retry-After``
without counting as an attempt; a network error or a 5xx is retried with the
submission queue's backoff; a 4xx, or a workflow biosim reports as failed, fails the verification with its reason.
"""

import logging
from typing import Any

import httpx
from sqlalchemy import func
from sqlalchemy.sql.elements import ColumnElement

from compose_api.common.gateway.models import Namespace
from compose_api.config import get_settings
from compose_api.db.services.comparisons_db import ClaimedVerification, ComparisonRow
from compose_api.db.tables.comparison_tables import ORMVerification
from compose_api.dependencies import get_required_database_service, get_submission_worker
from compose_api.sedml import service
from compose_api.sedml.models import Comparison, Tolerances, Verification
from compose_api.sedml.verify import (
    RateBudget,
    VerifyClient,
    VerifyOutput,
    VerifyRateLimitedError,
    VerifyRejectedError,
    VerifyStatus,
    agrees_with,
    references_from_output,
    sanitize_archive,
    stored_output,
    verify_close,
)
from compose_api.simulation.hpc_utils import get_internal_experiment_dir
from compose_api.simulation.job_script import SOURCE_FILE_NAME

logger = logging.getLogger(__name__)

#: Backoff after a transient failure, in seconds; the last is repeated (as the submission queue's).
BACKOFF_SECONDS = (30, 60, 120, 240, 480)


class VerificationFailedError(Exception):
    """A failure no retry can fix."""


def _in(seconds: float) -> ColumnElement[Any]:
    return func.localtimestamp() + func.make_interval(0, 0, 0, 0, 0, 0, max(0.0, seconds))


def _released(**values: Any) -> dict[str, Any]:
    return {"lease_owner": None, "lease_expires_at": None, **values}


async def advance(verification: ClaimedVerification, owner: str, client: VerifyClient, budget: RateBudget) -> None:
    """One step of ``verification``, which ``owner`` holds; the lease is given back when the step ends."""
    db = get_required_database_service().get_comparisons_db()
    try:
        if verification.state == "requested":
            values = await _submit(verification, client, budget)
        else:
            values = await _poll(verification, client)
    except VerifyRateLimitedError as e:
        logger.info(f"verification {verification.id}: {e}")
        values = {"next_attempt_at": _in(e.retry_after)}
    except (VerifyRejectedError, VerificationFailedError) as e:
        values = {"state": "failed", "last_error": str(e)}
    except (httpx.HTTPError, OSError) as e:
        attempts = verification.attempts + 1
        error = f"{type(e).__name__}: {e}"
        if attempts >= get_settings().submission_max_attempts:
            values = {"state": "failed", "attempts": attempts, "last_error": error}
        else:
            delay = BACKOFF_SECONDS[min(attempts, len(BACKOFF_SECONDS)) - 1]
            values = {"attempts": attempts, "last_error": error, "next_attempt_at": _in(delay)}
    if values.get("state") == "failed":
        logger.warning(f"verification {verification.id} of comparison {verification.comparison_id}: failed: "
                       f"{values['last_error']}")  # fmt: skip
    await db.update_verification(verification.id, owner, **_released(**values))


async def _submit(verification: ClaimedVerification, client: VerifyClient, budget: RateBudget) -> dict[str, Any]:
    db = get_required_database_service()
    row = await db.get_comparisons_db().get(verification.comparison_id)
    if row is None:
        raise VerificationFailedError("the comparison no longer exists")
    archive = await source_archive(row)
    wait = budget.take()
    if wait:
        return {"next_attempt_at": _in(wait)}
    content, dropped = sanitize_archive(archive)
    tolerances = Tolerances.model_validate(verification.settings.get("tolerances", {}))
    namespace = get_settings().namespace
    output = await client.verify_omex(
        content,
        filename=f"comparison-{row.comparison.id}.omex",
        simulators=verification.simulators,
        tolerances=tolerances,
        description=f"compose-api {namespace} comparison {row.comparison.id}: {row.comparison.name}"[:200],
        workflow_id_prefix=f"compose-api-{namespace}-comparison-{row.comparison.id}-",
    )
    without = f", without {len(dropped)} missing manifest entries" if dropped else ""
    logger.info(f"verification {verification.id} of comparison {row.comparison.id}: {output.workflow_id}{without}")
    return {
        "state": "submitted",
        "workflow_id": output.workflow_id,
        "workflow_status": output.workflow_status.value,
        "settings": {**verification.settings, "dropped_manifest_entries": dropped},
        "submitted_at": func.localtimestamp(),
        "attempts": 0,
        "last_error": None,
        "next_attempt_at": _in(get_settings().verify_poll_seconds),
    }


async def _poll(verification: ClaimedVerification, client: VerifyClient) -> dict[str, Any]:
    settings = get_settings()
    if verification.workflow_id is None:
        raise VerificationFailedError("submitted, but no workflow id was recorded")
    output = await client.get(verification.workflow_id)
    if not output.workflow_status.is_done:
        if (verification.submitted_seconds_ago or 0) > settings.verify_deadline_seconds:
            raise VerificationFailedError(
                f"{verification.workflow_id} still {output.workflow_status} after {settings.verify_deadline_seconds} s"
            )
        return {
            "workflow_status": output.workflow_status.value,
            "attempts": 0,
            "next_attempt_at": _in(settings.verify_poll_seconds),
        }
    if output.workflow_status is not VerifyStatus.COMPLETED:
        return {
            "state": "failed",
            "workflow_status": output.workflow_status.value,
            "result": stored_output(output),
            "last_error": output.workflow_error or f"biosim reported {output.workflow_status}",
        }
    close = await fold_into_comparison(verification.comparison_id, output)
    return {
        "state": "completed",
        "workflow_status": output.workflow_status.value,
        "result": stored_output(output),
        "verify_close": close,
        "last_error": None,
    }


async def fold_into_comparison(comparison_id: int, output: VerifyOutput) -> bool | None:
    """Attach each simulator's reports to the comparison as a reference, score it again, and return whether the
    simulators agree on its reports."""
    db = get_required_database_service().get_comparisons_db()
    row = await db.get(comparison_id)
    if row is None:
        raise VerificationFailedError("the comparison no longer exists")
    report_ids = list(row.comparison.settings.get("reports", {}))
    for origin, by_output in references_from_output(output).items():
        matched = service.match_references(row.comparison.sedml, report_ids, by_output)
        if matched:
            await db.replace_reference(comparison_id, origin, matched)
    await service.recompute(comparison_id)
    return verify_close(output, {f"{row.comparison.sedml}/{r}" for r in report_ids})


async def source_archive(row: ComparisonRow) -> bytes:
    """The archive the comparison translated, as its first member staged it (D4)."""
    if not row.members:
        raise VerificationFailedError("the comparison has no members, so no archive")
    db = get_required_database_service().get_simulator_db()
    experiment_id = await db.get_simulations_experiment_id(simulation_id=row.members[0].simulation_id)
    path = get_internal_experiment_dir(experiment_id, Namespace(get_settings().namespace)) / SOURCE_FILE_NAME
    try:
        return path.read_bytes()
    except FileNotFoundError as e:
        raise VerificationFailedError(f"its archive {path} is gone") from e


# -- queueing (V4) -- #

ACTIVE = ("requested", "submitted")


def needs_verification(comparison: Comparison) -> bool:
    """D3's "failing": a finished comparison whose solvers differ, that is incomplete, or that no agreeing reference
    settles (none, as for a source with no legacy project, or one that disagrees)."""
    if comparison.status == "running":
        return False
    result = comparison.result or {}
    return not (comparison.close is True and result.get("close_to_references") is True)


async def queue(comparison: ComparisonRow, simulators: list[str] | None = None) -> tuple[ORMVerification, bool]:
    """A verification of the comparison, and whether it is new: one already queued or running for the same
    simulators is returned instead, so asking twice costs biosim nothing."""
    db = get_required_database_service().get_comparisons_db()
    chosen = list(dict.fromkeys(simulators or get_settings().verify_simulators))
    found = [v for v in await db.verifications(comparison.comparison.id) if list(v.simulators) == chosen]
    for existing in found:
        if existing.state in ACTIVE:
            return existing, False
    if found and resumable(found[-1]):
        # biosim is still working on it (we stopped waiting, or could not read it): poll it again, not resubmit
        await db.resume_verification(found[-1].id)
        _kick()
        return next(v for v in await db.verifications(comparison.comparison.id) if v.id == found[-1].id), False
    tolerances = comparison.comparison.settings.get("tolerances", {})
    verification_id = await db.insert_verification(comparison.comparison.id, chosen, {"tolerances": tolerances})
    _kick()
    created = next(v for v in await db.verifications(comparison.comparison.id) if v.id == verification_id)
    return created, True


def resumable(row: ORMVerification) -> bool:
    """A verification that failed on our side while its workflow was still unfinished at biosim: past our deadline,
    or out of attempts at reading it."""
    unfinished = row.workflow_status in (VerifyStatus.PENDING.value, VerifyStatus.IN_PROGRESS.value)
    return row.state == "failed" and row.workflow_id is not None and unfinished


def _kick() -> None:
    worker = get_submission_worker()
    if worker is not None:
        worker.kick()


def view(row: ORMVerification, comparison_result: dict[str, Any] | None = None) -> Verification:
    """The verification as the API shows it; ``agrees_with`` needs its comparison's scored result."""
    result = row.result or {}
    runs = (result.get("workflow_results") or {}).get("sims_run_info") or []
    origins = []
    for info in runs:
        version = (info.get("biosim_sim_run") or {}).get("simulator_version") or {}
        if version.get("id"):
            origins.append(f"biosimulators:{version['id']}:{version.get('version', '')}")
    return Verification(
        verification_id=row.id,
        comparison_id=row.comparison_id,
        state=row.state,  # type: ignore[arg-type]
        simulators=list(row.simulators or []),
        workflow_id=row.workflow_id,
        workflow_status=row.workflow_status,
        verify_close=row.verify_close,
        references=origins if row.state == "completed" else [],
        agrees_with=agrees_with(comparison_result, origins) if row.state == "completed" else [],
        failed_simulators=list(result.get("failed_simulators") or []),
        attempts=row.attempts,
        last_error=row.last_error,
        created_at=service._iso(row.created_at),
        updated_at=service._iso(row.updated_at),
    )
