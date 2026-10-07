"""The client's application layer (compose_api_client.ext) over httpx.MockTransport: no service, no network."""

import io
import json
import zipfile
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from compose_api_client.ext import (
    ApiTimeout,
    AsyncComposeSession,
    BadRequest,
    ComposeSession,
    JobState,
    NotFound,
    ServerError,
)

Handler = Callable[[httpx.Request], httpx.Response]


def _run(status: str, sim_id: int = 7) -> dict[str, object]:
    return {
        "database_id": 1,
        "slurmjobid": 4129255,
        "correlation_id": "simulation-x",
        "job_type": "simulation",
        "sim_id": sim_id,
        "simulator_id": None,
        "status": status,
        "start_time": "2026-10-07 00:34:36",
        "end_time": None,
        "error_message": None,
    }


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _session(handler: Handler) -> ComposeSession:
    return ComposeSession("http://compose.test", transport=httpx.MockTransport(handler))


def _statuses(*sequence: int | str) -> Handler:
    """A status endpoint that answers 404 for each int in ``sequence`` and the job record for each string, then
    keeps answering the last."""
    answers = list(sequence)

    def handler(request: httpx.Request) -> httpx.Response:
        answer = answers.pop(0) if len(answers) > 1 else answers[0]
        if isinstance(answer, int):
            return httpx.Response(answer, json={"detail": "not found"})
        return httpx.Response(200, json=_run(answer))

    return handler


def test_status_before_the_slurm_job_exists_is_submitting() -> None:
    with _session(_statuses(404)) as s:
        state = s.status(7)
    assert state == JobState("submitting") and not state.terminal and state.slurm_job is None


def test_wait_reports_each_change_and_returns_the_final_state() -> None:
    seen: list[str] = []
    with _session(_statuses(404, 404, "pending", "running", "running", "completed")) as s:
        state = s.wait(7, poll=0, on_update=lambda st: seen.append(st.status))
    assert seen == ["submitting", "pending", "running", "completed"]
    assert state.ok and state.terminal and state.slurm_job == 4129255


@pytest.mark.parametrize("final", ["failed", "timeout", "out_of_memory", "cancelled"])
def test_wait_stops_on_every_terminal_status(final: str) -> None:
    with _session(_statuses("running", final)) as s:
        state = s.wait(7, poll=0)
    assert state.terminal and not state.ok and state.status == final


def test_wait_raises_at_its_deadline_with_the_last_state() -> None:
    with _session(_statuses("running")) as s, pytest.raises(ApiTimeout) as err:
        s.wait(7, poll=0.01, timeout=0.05)
    assert isinstance(err.value.last, JobState) and err.value.last.status == "running"


def test_submit_sends_the_file_and_the_simulator() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["query"] = dict(request.url.params)
        seen["body"] = request.read()
        return httpx.Response(200, json={"simulation_database_id": 4192, "simulator_database_id": 134})

    with _session(handler) as s:
        sim = s.submit(b"PK-omex-bytes", simulator="viva-pde-particle", interval=2.0)
    assert sim.simulation_database_id == 4192
    assert seen["path"] == "/simulation/run"
    assert seen["query"] == {"interval_time": "2.0", "batch_submission": "false", "simulator": "viva-pde-particle"}
    assert b"PK-omex-bytes" in seen["body"]  # type: ignore[operator]


def test_a_rejected_document_raises_bad_request_with_its_violations() -> None:
    detail = {"message": "invalid document", "violations": [{"path": "state.x", "error": "unknown address"}]}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"detail": detail})

    with _session(handler) as s, pytest.raises(BadRequest) as err:
        s.submit(b"x")
    assert err.value.status_code == 400
    assert err.value.violations == detail["violations"]


def test_errors_map_to_types() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/results/file"):
            return httpx.Response(404, json={"detail": "no results yet"})
        return httpx.Response(503, text="upstream down")

    with _session(handler) as s:
        with pytest.raises(NotFound) as nf:
            s.results(7)
        assert nf.value.detail == "no results yet"
        with pytest.raises(ServerError) as se:
            s.statuses([7, 8])
        assert se.value.detail == "upstream down"


def test_download_saves_or_extracts(tmp_path: Path) -> None:
    archive = _zip({"results_1.pber": b"{}", "sub/log.txt": b"ok"})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=archive)

    with _session(handler) as s:
        saved = s.download(7, f"{tmp_path}/out/")  # a trailing slash (or an existing directory) means a directory
        assert saved == tmp_path / "out" / "simulation_7_results.zip" and saved.read_bytes() == archive
        assert s.download(7, tmp_path) == tmp_path / "simulation_7_results.zip"
        named = s.download(7, tmp_path / "r.zip")
        assert named == tmp_path / "r.zip"
        extracted = s.extract(7, tmp_path / "x")
    assert sorted(p.relative_to(tmp_path / "x").as_posix() for p in extracted) == ["results_1.pber", "sub/log.txt"]


def test_extract_refuses_paths_outside_the_destination(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_zip({"../escape.txt": b"x"}))

    with _session(handler) as s, pytest.raises(ValueError, match="unsafe path"):
        s.extract(7, tmp_path / "x")
    assert not (tmp_path / "escape.txt").exists()


def test_run_and_wait_downloads_only_a_completed_job(tmp_path: Path) -> None:
    def make(final: str) -> Handler:
        status = _statuses("running", final)

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/simulation/run":
                return httpx.Response(200, json={"simulation_database_id": 7, "simulator_database_id": 1})
            if request.url.path.endswith("/results/file"):
                return httpx.Response(200, content=_zip({"results.pber": b"{}"}))
            return status(request)

        return handler

    with _session(make("completed")) as s:
        sim, state, saved = s.run_and_wait(b"x", poll=0, dest=tmp_path / "ok", extract=True)
    assert sim.simulation_database_id == 7 and state.ok and saved == [tmp_path / "ok" / "results.pber"]
    with _session(make("failed")) as s:
        _, state, saved = s.run_and_wait(b"x", poll=0, dest=tmp_path / "bad")
    assert state.status == "failed" and saved == [] and not (tmp_path / "bad").exists()


def test_catalogue_and_health() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        bodies: dict[str, object] = {
            "/health": {"docs": "https://compose.test/docs", "version": "0.6.0"},
            "/version": "0.6.0",
            "/core/processes/list": [],
            "/core/steps/list": [],
            "/results/simulations/status/batch": [_run("completed", 7), _run("running", 8)],
        }
        return httpx.Response(200, content=json.dumps(bodies[request.url.path]).encode())

    with _session(handler) as s:
        assert s.health() == {"docs": "https://compose.test/docs", "version": "0.6.0"}
        assert s.version() == "0.6.0"
        assert s.processes() == [] and s.steps() == []
        assert [str(r.status) for r in s.statuses([7, 8])] == ["completed", "running"]


def test_a_token_selects_the_authenticated_client() -> None:
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json="0.6.0")

    with ComposeSession("http://compose.test", token="t0k", transport=httpx.MockTransport(handler)) as s:
        s.version()
    assert seen["auth"] == "Bearer t0k"


@pytest.mark.asyncio
async def test_async_session_waits_and_downloads(tmp_path: Path) -> None:
    status = _statuses(404, "running", "completed")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/results/file"):
            return httpx.Response(200, content=_zip({"results.pber": b"{}"}))
        return status(request)

    async with AsyncComposeSession("http://compose.test", transport=httpx.MockTransport(handler)) as s:
        state = await s.wait(7, poll=0)
        files = await s.extract(7, tmp_path)
    assert state.ok and files == [tmp_path / "results.pber"]
