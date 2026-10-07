"""The ``compose-api`` command line: every API operation has a command, and each command's output and exit code.

Commands run through typer's ``CliRunner`` against ``httpx.MockTransport`` (the CLI is synchronous and the app is
reached only asynchronously in process; the service-facing behaviour underneath is pinned in ``test_ext*.py``).
"""

import io
import json
import logging
import zipfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from compose_api_client.cli import CLAIMS, app
from compose_api_client.cli import commands as cli_module
from compose_api_client.cli.commands import Settings, bundled_spec, operations
from compose_api_client.ext import ComposeSession
from typer.testing import CliRunner


@pytest.fixture(autouse=True)
def _quiet_httpx_logs() -> Iterator[None]:
    """httpx logs each request at INFO. Under this repository's live logging (log_cli) a record emitted inside
    CliRunner.invoke is written to the runner's stream after it has been closed."""
    logger = logging.getLogger("httpx")
    level = logger.level
    logger.setLevel(logging.WARNING)
    yield
    logger.setLevel(level)


SPEC = Path(__file__).parents[2] / "compose_api" / "api" / "spec" / "openapi_3_1_0_generated.yaml"
Handler = Callable[[httpx.Request], httpx.Response]
runner = CliRunner()


def test_every_operation_in_the_spec_has_exactly_one_command() -> None:
    """The "exercise every operation" guarantee: adding an endpoint without a command fails here."""
    spec_ops = set(operations(yaml.safe_load(SPEC.read_text())))
    claimed = {op for op in CLAIMS if not op.islower() or "-" in op or "_" in op}  # operationIds, not bare names
    assert spec_ops - set(CLAIMS) == set(), f"operations with no command: {sorted(spec_ops - set(CLAIMS))}"
    assert claimed - spec_ops == set(), f"commands claim operations the spec lacks: {sorted(claimed - spec_ops)}"


def test_the_bundled_spec_is_the_committed_spec() -> None:
    assert bundled_spec() == yaml.safe_load(SPEC.read_text())


def _run(status: str, sim_id: int = 7) -> dict[str, Any]:
    return {
        "database_id": 1,
        "slurmjobid": 4129255,
        "correlation_id": "c",
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


class FakeService:
    """A scripted compose-api: status answers follow ``statuses`` (an int is that HTTP status), then repeat the
    last; everything else has one canned answer."""

    def __init__(self, statuses: list[int | str] | None = None, final_results: bytes | None = None) -> None:
        self.statuses = list(statuses or ["completed"])
        self.results = final_results if final_results is not None else _zip({"results.pber": b"{}"})
        self.requests: list[httpx.Request] = []
        self.events = [_event(i, name) for i, name in enumerate(["dispatch.submitted", "job.start", "job.end"], 1)]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/health":
            return httpx.Response(200, json={"docs": "x/docs", "version": "0.6.0"})
        if path == "/version":
            return httpx.Response(200, json="0.6.0")
        if path in ("/simulation/run", "/curated/copasi", "/curated/tellurium"):
            return httpx.Response(200, json={"simulation_database_id": 7, "simulator_database_id": 134})
        if path in ("/results/simulation/status", "/results/simulator/build/status"):
            answer = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
            if isinstance(answer, int):
                return httpx.Response(answer, json={"detail": "not found"})
            return httpx.Response(200, json=_run(answer))
        if path == "/results/simulations/status/batch":
            ids = json.loads(request.read())
            return httpx.Response(200, json=[_run("running", i) for i in ids if i != 99])
        if path == "/results/simulation/results/file":
            return httpx.Response(200, content=self.results)
        if path.startswith(("/results/simulation/events", "/results/simulation/trace")):
            return self._observability(request)
        if path.startswith("/core/"):
            return self._catalogue(path)
        return httpx.Response(500, text=f"unexpected {path}")

    def _catalogue(self, path: str) -> httpx.Response:
        if path == "/core/simulator/list":
            return httpx.Response(200, json={"versions": [_simulator()], "timestamp": None})
        if path in ("/core/processes/list", "/core/steps/list"):
            return httpx.Response(
                200,
                json=[
                    {
                        "module": "m",
                        "name": "n",
                        "compute_type": "process",
                        "inputs": "{}",
                        "outputs": "{}",
                        "database_id": 3,
                    }
                ],
            )
        return httpx.Response(500, text=f"unexpected {path}")

    def _observability(self, request: httpx.Request) -> httpx.Response:
        path, params = request.url.path, request.url.params
        if path == "/results/simulation/events":
            after, limit = int(params.get("after", 0)), int(params.get("limit", 500))
            page = [e for e in self.events if e["cursor"] > after][:limit]
            following = page[-1]["cursor"] if len(page) == limit else None
            body = {"simulation_id": 7, "trace_id": "t" * 32, "events": page, "next_cursor": following}
            return httpx.Response(200, json=body)
        if path == "/results/simulation/trace":
            return httpx.Response(200, json={"simulation_id": 7, "trace_id": "t" * 32, "roots": [_job_tree()]})
        return httpx.Response(200, json={"traceEvents": [], "displayTimeUnit": "ms", "otherData": {}})


def _event(cursor: int, name: str) -> dict[str, Any]:
    return {
        "cursor": cursor,
        "seq": cursor,
        "source": "job-1",
        "ts": f"2026-10-07T12:00:0{cursor}.000Z",
        "component": "compose_api.job",
        "event": name,
        "level": "info",
        "payload": {"n": cursor},
    }


def _job_tree() -> dict[str, Any]:
    span: dict[str, Any] = {"span_id": "1" * 16, "name": "job", "start_ts": "2026-10-07T12:00:00.000Z"}
    span.update(status="ok", duration_s=3.0)
    return {"span": span, "events": [_event(2, "job.start")], "children": []}


def _simulator() -> dict[str, Any]:
    return {
        "container_def": {"representation": "Bootstrap: docker\nFrom: ghcr.io/x/y:1\n", "containerization_engine": 2},
        "container_def_hash": "abc123",
        "packages": None,
        "database_id": 5,
        "created_at": "2026-10-06T12:00:00",
    }


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., FakeService]]:
    def install(*args: Any, **kwargs: Any) -> FakeService:
        fake = FakeService(*args, **kwargs)

        def make(settings: Settings) -> ComposeSession:
            return ComposeSession(settings.url, token=settings.token, transport=httpx.MockTransport(fake))

        monkeypatch.setattr(cli_module, "make_session", make)
        return fake

    yield install


def invoke(*args: str) -> Any:
    return runner.invoke(app, ["--output", "json", "--quiet", *args])


def test_health_version_and_catalogue(service: Callable[..., FakeService]) -> None:
    service()
    r = invoke("health")
    assert r.exit_code == 0 and json.loads(r.stdout) == {"docs": "x/docs", "version": "0.6.0"}
    assert json.loads(invoke("version").stdout) == "0.6.0"
    assert json.loads(invoke("simulators", "list").stdout)["versions"][0]["container_def_hash"] == "abc123"
    assert json.loads(invoke("processes", "list").stdout)[0]["name"] == "n"
    assert json.loads(invoke("steps", "list").stdout)[0]["database_id"] == 3


def test_simulators_table_shows_the_base_image(service: Callable[..., FakeService]) -> None:
    service()
    r = runner.invoke(app, ["--output", "table", "simulators", "list"])
    assert r.exit_code == 0 and "ghcr.io/x/y:1" in r.stdout and "abc123" in r.stdout


def test_run_prints_the_ids_and_sends_the_simulator(service: Callable[..., FakeService], tmp_path: Path) -> None:
    fake = service()
    doc = tmp_path / "experiment.omex"
    doc.write_bytes(b"PK")
    r = invoke("run", str(doc), "--simulator", "viva-pde-particle")
    assert r.exit_code == 0 and json.loads(r.stdout)["simulation_database_id"] == 7
    assert fake.requests[0].url.params["simulator"] == "viva-pde-particle"


def test_run_wait_download_extract(service: Callable[..., FakeService], tmp_path: Path) -> None:
    service([404, "pending", "running", "completed"])
    doc = tmp_path / "experiment.omex"
    doc.write_bytes(b"PK")
    out = tmp_path / "out"
    r = invoke("run", str(doc), "--wait", "--poll", "0", "--download", str(out), "--extract")
    assert r.exit_code == 0, r.output
    rec = json.loads(r.stdout)
    assert rec["status"] == "completed" and rec["slurmjobid"] == 4129255
    assert rec["files"] == [str(out / "results.pber")] and (out / "results.pber").exists()


def test_a_failed_job_exits_1(service: Callable[..., FakeService], tmp_path: Path) -> None:
    service(["running", "failed"])
    doc = tmp_path / "x.omex"
    doc.write_bytes(b"PK")
    r = invoke("run", str(doc), "--wait", "--poll", "0", "--download", str(tmp_path / "out"))
    assert r.exit_code == 1 and json.loads(r.stdout)["status"] == "failed"
    assert not (tmp_path / "out").exists()


def test_wait_timeout_exits_5(service: Callable[..., FakeService]) -> None:
    service(["running"])
    r = invoke("wait", "7", "--poll", "0.01", "--wait-timeout", "0.05")
    assert r.exit_code == 5


def test_status_one_and_several(service: Callable[..., FakeService]) -> None:
    service([404])
    one = invoke("status", "7")
    assert one.exit_code == 0 and json.loads(one.stdout) == {"simulation_id": 7, "status": "submitting"}
    several = json.loads(invoke("status", "7", "99").stdout)
    assert [(r["simulation_id"], r["status"]) for r in several] == [(7, "running"), (99, "submitting")]


def test_results_saves_or_extracts(service: Callable[..., FakeService], tmp_path: Path) -> None:
    service(final_results=_zip({"a.txt": b"1"}))
    saved = json.loads(invoke("results", "7", "--out", str(tmp_path)).stdout)
    assert saved["files"] == [str(tmp_path / "simulation_7_results.zip")]
    unpacked = json.loads(invoke("results", "7", "--extract", str(tmp_path / "x")).stdout)
    assert unpacked["files"] == [str(tmp_path / "x" / "a.txt")]


def test_curated_and_build_status(service: Callable[..., FakeService], tmp_path: Path) -> None:
    fake = service(["completed"])
    sbml = tmp_path / "m.xml"
    sbml.write_text("<sbml/>")
    c = invoke("curated", "copasi", str(sbml), "--start", "0", "--duration", "10", "--points", "5")
    assert c.exit_code == 0 and json.loads(c.stdout)["simulation_database_id"] == 7
    t = invoke("curated", "tellurium", str(sbml), "--start", "0", "--end", "10", "--points", "5")
    assert t.exit_code == 0
    assert dict(fake.requests[-1].url.params) == {"start_time": "0.0", "end_time": "10.0", "num_data_points": "5"}
    b = invoke("build-status", "134", "--wait", "--poll", "0")
    assert b.exit_code == 0 and json.loads(b.stdout)["simulator_id"] == 134


def test_errors_have_messages_and_exit_codes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def respond(code: int, body: Any) -> None:
        def make(settings: Settings) -> ComposeSession:
            return ComposeSession(
                settings.url, transport=httpx.MockTransport(lambda r: httpx.Response(code, json=body))
            )

        monkeypatch.setattr(cli_module, "make_session", make)

    doc = tmp_path / "x.omex"
    doc.write_bytes(b"PK")
    respond(400, {"detail": {"message": "invalid document", "violations": ["state.x: unknown address"]}})
    r = invoke("run", str(doc))
    assert r.exit_code == 3 and "invalid document" in r.stderr and "state.x: unknown address" in r.stderr
    respond(404, {"detail": "Simulation 7 not found"})
    r = invoke("results", "7")
    assert r.exit_code == 4 and "Simulation 7 not found" in r.stderr
    respond(500, {"detail": "boom"})
    assert invoke("version").exit_code == 3
    assert invoke("run", str(tmp_path / "missing.omex")).exit_code == 2  # typer validates the path


def test_unreachable_service_exits_3(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    monkeypatch.setattr(
        cli_module, "make_session", lambda s: ComposeSession(s.url, transport=httpx.MockTransport(refuse))
    )
    r = invoke("health")
    assert r.exit_code == 3 and "cannot reach" in r.stderr


def test_openapi_diff_reports_skew(monkeypatch: pytest.MonkeyPatch) -> None:
    live = json.loads(json.dumps(bundled_spec()))
    live["paths"]["/version"]["get"]["operationId"] = "renamed-version"
    monkeypatch.setattr(cli_module, "fetch_spec", lambda settings: live)
    r = invoke("openapi", "--diff")
    report = json.loads(r.stdout)
    assert r.exit_code == 1
    assert report["only_in_client"] == ["get_version_version_get"]
    assert report["only_in_service"] == ["renamed-version"]
    monkeypatch.setattr(cli_module, "fetch_spec", lambda settings: bundled_spec())
    assert invoke("openapi", "--diff").exit_code == 0
    assert json.loads(invoke("openapi").stdout)["info"]["title"]


def test_events_pages_through_and_prints_json_lines(service: Callable[..., FakeService]) -> None:
    fake = service()
    r = runner.invoke(app, ["--output", "json", "events", "7"])
    assert r.exit_code == 0, r.output
    assert [json.loads(line)["event"] for line in r.stdout.splitlines()] == [
        "dispatch.submitted",
        "job.start",
        "job.end",
    ]
    assert fake.requests[0].url.params["simulation_id"] == "7"
    table = runner.invoke(app, ["--output", "table", "events", "7", "--level", "info"])
    assert table.exit_code == 0 and "job.end" in table.stdout
    assert fake.requests[-1].url.params["level"] == "info"


def test_events_follow_stops_when_the_job_is_finished(service: Callable[..., FakeService]) -> None:
    service(["running", "completed"])
    r = runner.invoke(app, ["--output", "json", "events", "7", "--follow", "--poll", "0"])
    assert r.exit_code == 0 and len(r.stdout.splitlines()) == 3


def test_trace_tree_and_chrome_file(service: Callable[..., FakeService], tmp_path: Path) -> None:
    service()
    tree = json.loads(invoke("trace", "7").stdout)
    assert tree["roots"][0]["span"]["name"] == "job"
    shown = runner.invoke(app, ["--output", "table", "trace", "7"])
    assert shown.exit_code == 0 and "job" in shown.stdout and "job.start" in shown.stdout
    out = tmp_path / "t.json"
    saved = json.loads(invoke("trace", "7", "--chrome", str(out)).stdout)
    assert saved["files"] == [str(out)] and json.loads(out.read_text())["displayTimeUnit"] == "ms"
