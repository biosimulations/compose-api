"""How long a run may simulate, and how long its SLURM job may take (Settings.max_interval_time and the rest): any run
up to max_interval_time; a caller holding long_run_role (any signed-in caller while it is empty) up to
max_long_run_interval_time, and a run past the usual cap gets a SLURM limit scaled by its interval. Runs the service
starts itself (compliance, SED-ML) never pass through here, so they keep the usual limit whatever their interval."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from compose_api.api.main import app
from compose_api.api.routers.simulation import time_limit_minutes
from compose_api.authentication import AuthenticatedPrincipal, get_optional_principal
from compose_api.authorization import capabilities, may_run_long
from compose_api.config import Settings, override_settings
from compose_api.db.database_service import DatabaseService, DatabaseServiceSQL
from compose_api.simulation.models import SimulationExperiment, SimulationRequest
from tests.api.test_submission_rejection import PREBUILT, SIM_IMAGE, pbg
from tests.fixtures.postgres_fixtures import register_prebuilt

MEMBER = AuthenticatedPrincipal("auth0|member", "i", ("a",), frozenset(), frozenset(), frozenset({"user"}))
HOLDER = AuthenticatedPrincipal("auth0|holder", "i", ("a",), frozenset(), frozenset(), frozenset({"user", "long-runs"}))
LONG_RUNS = {"max_long_run_interval_time": 86400.0, "slurm_max_time_limit_minutes": 720, "long_run_role": "long-runs"}
LIMITS = (
    "max_interval_time",
    "max_long_run_interval_time",
    "slurm_time_limit_minutes",
    "slurm_max_time_limit_minutes",
)
#: What a deployment that sets none of them gets (pinned here, so a local env file cannot change the tests below).
DEFAULTS = {name: Settings.model_fields[name].default for name in LIMITS}


def test_the_limit_scales_with_the_interval_past_the_anonymous_cap_up_to_the_maximum() -> None:
    with override_settings(max_interval_time=1000.0, slurm_time_limit_minutes=30, slurm_max_time_limit_minutes=720):
        assert time_limit_minutes(0) is None and time_limit_minutes(1000) is None  # the usual limit
        assert time_limit_minutes(1000.5) == 31  # 30.015 minutes, rounded up
        assert time_limit_minutes(2000) == 60
        assert time_limit_minutes(24000) == 720
        assert time_limit_minutes(86400) == 720  # 2,592 minutes at that scale, held to the maximum


def test_long_runs_are_for_the_roles_holders_or_any_signed_in_caller_while_no_role_is_named() -> None:
    with override_settings(**LONG_RUNS):
        assert may_run_long(HOLDER) and not may_run_long(MEMBER) and not may_run_long(None)
        assert "simulations:long-runs" in capabilities(HOLDER)  # what GET /auth/me reports, so the UI offers it
        assert "simulations:long-runs" not in capabilities(MEMBER)
    with override_settings(**{**LONG_RUNS, "long_run_role": ""}):
        assert may_run_long(MEMBER) and not may_run_long(None)
    with override_settings(**DEFAULTS, long_run_role="long-runs"):
        assert not may_run_long(HOLDER), "no one runs long while the two caps are equal"


@pytest.fixture
def submitted(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[SimulationRequest]]:
    """The requests that got past every check, as the handler would record them; nothing is recorded or run."""
    seen: list[SimulationRequest] = []

    async def record(*, simulation_request: SimulationRequest, **_: object) -> SimulationExperiment:
        seen.append(simulation_request)
        return SimulationExperiment(simulation_database_id=1, simulator_database_id=1)

    monkeypatch.setattr("compose_api.api.routers.simulation.run_simulation", record)
    monkeypatch.setattr("compose_api.api.routers.simulation.get_simulation_service", lambda: object())
    monkeypatch.setattr("compose_api.api.routers.simulation.get_job_monitor", lambda: object())
    yield seen
    app.dependency_overrides.pop(get_optional_principal, None)


async def _submit(client: httpx.AsyncClient, interval: str, caller: AuthenticatedPrincipal | None) -> httpx.Response:
    if caller is not None:
        app.dependency_overrides[get_optional_principal] = lambda: caller
    else:
        app.dependency_overrides.pop(get_optional_principal, None)
    # a registered prebuilt image: its classes are not looked up, so any document gets past validation
    return await client.post(
        "/simulation/run",
        params={"interval_time": interval, "simulator": PREBUILT},
        files={"uploaded_file": ("doc.pbg", pbg("local:sim_a.processes.Solver"), "application/json")},
    )


@pytest.mark.asyncio
async def test_only_a_holder_of_the_role_may_run_longer_with_a_longer_slurm_limit(
    http_api_client: httpx.AsyncClient, database_service: DatabaseService, submitted: list[SimulationRequest]
) -> None:
    await register_prebuilt(database_service, PREBUILT, SIM_IMAGE)
    refusal = "Invalid interval time, it has to be between 0 and 1000; up to 86400 with the long-runs role"
    with override_settings(**LONG_RUNS):
        for caller in (None, MEMBER):  # anonymous, and signed in without the role: the usual cap, as before
            assert (await _submit(http_api_client, "1000", caller)).status_code == 200
            too_long = await _submit(http_api_client, "1000.5", caller)
            assert too_long.status_code == 400
            assert too_long.json()["detail"] == refusal

        day = await _submit(http_api_client, "86400", HOLDER)
        assert day.status_code == 200, day.text
        short = await _submit(http_api_client, "1000", HOLDER)
        assert short.status_code == 200, short.text
        past = await _submit(http_api_client, "86400.5", HOLDER)
        assert past.status_code == 400
        assert past.json()["detail"] == "Invalid interval time, it has to be between 0 and 86400"
    assert [(r.end_time_point, r.time_limit_minutes) for r in submitted] == [
        (1000, None),
        (1000, None),
        (86400, 720),
        (1000, None),
    ]


@pytest.mark.asyncio
async def test_with_no_role_named_any_signed_in_caller_may_run_longer(
    http_api_client: httpx.AsyncClient, database_service: DatabaseService, submitted: list[SimulationRequest]
) -> None:
    await register_prebuilt(database_service, PREBUILT, SIM_IMAGE)
    with override_settings(**{**LONG_RUNS, "long_run_role": ""}):
        assert (await _submit(http_api_client, "86400", MEMBER)).status_code == 200
        anonymous = await _submit(http_api_client, "1000.5", None)
        assert anonymous.status_code == 400
        assert (
            anonymous.json()["detail"]
            == "Invalid interval time, it has to be between 0 and 1000; up to 86400 signed in"
        )
    assert [(r.end_time_point, r.time_limit_minutes) for r in submitted] == [(86400, 720)]


@pytest.mark.asyncio
@pytest.mark.parametrize("interval", ["nan", "inf", "-inf", "-1"])
@pytest.mark.parametrize("caller", [None, MEMBER, HOLDER])
async def test_an_interval_outside_the_range_is_refused(
    http_api_client: httpx.AsyncClient,
    database_service: DatabaseService,
    submitted: list[SimulationRequest],
    interval: str,
    caller: AuthenticatedPrincipal | None,
) -> None:
    """NaN fails every comparison, so a check written as `x < 0 or x > cap` let it through to the runner."""
    await register_prebuilt(database_service, PREBUILT, SIM_IMAGE)
    with override_settings(**LONG_RUNS):
        response = await _submit(http_api_client, interval, caller)
    assert response.status_code == 400, response.text
    assert response.json()["detail"].startswith("Invalid interval time"), response.text
    assert submitted == []


@pytest.mark.asyncio
async def test_by_default_every_caller_keeps_the_usual_cap(
    http_api_client: httpx.AsyncClient, database_service: DatabaseService, submitted: list[SimulationRequest]
) -> None:
    """A deployment that sets nothing behaves as before: 1000 for everyone, the same message, the usual limit."""
    assert DEFAULTS == {
        "max_interval_time": 1000.0,
        "max_long_run_interval_time": 1000.0,
        "slurm_time_limit_minutes": 30,
        "slurm_max_time_limit_minutes": 30,
    }
    assert Settings.model_fields["long_run_role"].default == ""
    await register_prebuilt(database_service, PREBUILT, SIM_IMAGE)
    with override_settings(**DEFAULTS, long_run_role=""):
        for caller in (None, MEMBER, HOLDER):
            refused = await _submit(http_api_client, "1001", caller)
            assert refused.status_code == 400
            assert refused.json()["detail"] == "Invalid interval time, it has to be between 0 and 1000"
            accepted = await _submit(http_api_client, "1000", caller)
            assert accepted.status_code == 200, accepted.text
    assert [(r.end_time_point, r.time_limit_minutes) for r in submitted] == [(1000, None)] * 3


@pytest.mark.parametrize(
    "fields",
    [
        {"max_interval_time": 0},  # would divide by zero for every long run
        {"max_interval_time": float("inf")},
        {"max_long_run_interval_time": float("nan")},
        {"slurm_time_limit_minutes": 0},  # sbatch reads --time=0 as no limit at all
        {"max_long_run_interval_time": 999},  # long runs held below the usual cap
        {"slurm_max_time_limit_minutes": 29},  # long runs given less time than short ones
    ],
)
def test_run_limits_that_would_misbehave_fail_at_startup(fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Settings(**{**DEFAULTS, **fields})


@pytest.mark.asyncio
async def test_a_queued_run_records_who_submitted_it(
    http_api_client: httpx.AsyncClient,
    database_service: DatabaseServiceSQL,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The queue keeps the submitter for fair scheduling (docs/plan-durable-submission.md, Q3), but the run endpoint
    never passed it on, so every interactive run was queued under no one."""
    await register_prebuilt(database_service, PREBUILT, SIM_IMAGE)
    monkeypatch.setattr("compose_api.api.routers.simulation.get_simulation_service", lambda: object())
    monkeypatch.setattr("compose_api.api.routers.simulation.get_job_monitor", lambda: object())
    ids: list[int] = []
    try:
        with override_settings(submission_staging_dir=str(tmp_path / "staging")):
            for caller, submitter in ((MEMBER, MEMBER.subject), (None, None)):
                response = await _submit(http_api_client, "10", caller)
                assert response.status_code == 200, response.text
                ids.append(response.json()["simulation_database_id"])
                queued = await database_service.get_hpc_db().get_submission(ids[-1])
                assert queued is not None and queued.requested_by == submitter
    finally:
        app.dependency_overrides.pop(get_optional_principal, None)
        for simulation_id in ids:
            await database_service.get_simulator_db().delete_simulation(simulation_id)
