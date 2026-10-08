"""The ``compose-api`` command line: every API operation has a command, and each command's output and exit code.

Commands run through typer's ``CliRunner`` against ``httpx.MockTransport`` (the CLI is synchronous and the app is
reached only asynchronously in process; the service-facing behaviour underneath is pinned in ``test_ext*.py``).
"""

import datetime
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
        routes: list[tuple[tuple[str, ...], Callable[[], httpx.Response]]] = [
            (("/results/simulation/events", "/results/simulation/trace"), lambda: self._observability(request)),
            (("/auth/me",), lambda: self._identity(request)),
            (("/core/",), lambda: self._catalogue(path)),
            (("/datasets",), lambda: _datasets(path)),
            (("/simulations",), lambda: _simulations(path)),
        ]
        for prefixes, respond in routes:
            if path.startswith(prefixes):
                return respond()
        return httpx.Response(500, text=f"unexpected {path}")

    def _identity(self, request: httpx.Request) -> httpx.Response:
        if request.headers.get("authorization") != "Bearer test-token":
            return httpx.Response(401, json={"detail": "Invalid authentication credentials"})
        return httpx.Response(
            200,
            json={
                "issuer": "https://compose-test.example.auth0.com/",
                "subject": "auth0|test-user",
                "audience": ["https://compose-api.test"],
                "roles": ["user"],
                "scopes": ["openid", "profile"],
                "permissions": [],
            },
        )

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


DATASET_ID = "0b6f5d2e-6a39-4d55-9a4e-4b1f0d6c8a11"


def _dataset() -> dict[str, Any]:
    return {
        "id": DATASET_ID,
        "simulation_id": 7,
        "path": "output/a.csv",
        "kind": "table",
        "media_type": "text/csv",
        "display_name": "a.csv",
        "size_bytes": 4,
        "origin": "manifest",
        "available": True,
    }


def _summary(sim_id: int, status: str) -> dict[str, Any]:
    return {
        "simulation_id": sim_id,
        "created_at": "2026-10-07T17:27:37Z",
        "experiment_id": f"abc_{sim_id}",
        "simulator_id": 138,
        "simulator": "viva-pde-particle",
        "container_def_hash": "94e598ed",
        "visibility": "public",
        "status": status,
    }


def _simulations(path: str) -> httpx.Response:
    if path == "/simulations":
        rows = [_summary(4334, "completed"), _summary(4333, "submitting")]
        return httpx.Response(200, json={"simulations": rows, "total": 7, "next_offset": 2})
    return httpx.Response(200, json={**_summary(4334, "completed"), "event_count": 21, "dataset_count": 2})


def _datasets(path: str) -> httpx.Response:
    if path == "/datasets":
        return httpx.Response(200, json={"datasets": [_dataset()], "total": 1, "next_offset": None})
    if path == f"/datasets/{DATASET_ID}":
        return httpx.Response(200, json=_dataset())
    if path == f"/datasets/{DATASET_ID}/content":
        return httpx.Response(200, content=b"a,b\n")
    return httpx.Response(404, json={"detail": "Dataset not found."})


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


def test_auth_whoami_reports_the_service_identity(service: Callable[..., FakeService]) -> None:
    service()
    r = runner.invoke(app, ["--output", "json", "auth", "whoami"], env={"COMPOSE_API_TOKEN": "test-token"})
    assert r.exit_code == 0, r.output
    assert json.loads(r.stdout)["subject"] == "auth0|test-user"


def test_auth_whoami_without_credentials_exits_3(service: Callable[..., FakeService]) -> None:
    service()
    r = invoke("auth", "whoami")
    assert r.exit_code == 3 and "401" in r.stderr


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


def test_datasets_list_show_and_get(service: Callable[..., FakeService], tmp_path: Path) -> None:
    fake = service()
    listed = json.loads(invoke("datasets", "list", "--sim", "7", "--kind", "table").stdout)
    assert [d["path"] for d in listed] == ["output/a.csv"]
    assert dict(fake.requests[-1].url.params) == {
        "simulation_id": "7",
        "kind": "table",
        "available": "true",
        "limit": "100",
        "offset": "0",
    }
    assert json.loads(invoke("datasets", "show", DATASET_ID).stdout)["media_type"] == "text/csv"
    got = json.loads(invoke("datasets", "get", DATASET_ID, "--out", str(tmp_path)).stdout)
    assert got["files"] == [str(tmp_path / "a.csv")] and (tmp_path / "a.csv").read_bytes() == b"a,b\n"
    assert invoke("datasets", "show", "00000000-0000-0000-0000-000000000000").exit_code == 4


def test_simulations_list_and_show(service: Callable[..., FakeService]) -> None:
    fake = service()
    listed = json.loads(invoke("simulations", "list", "--status", "completed", "--since", "2d", "--limit", "2").stdout)
    assert [r["simulation_id"] for r in listed] == [4334, 4333]
    params = fake.requests[-1].url.params
    assert (params["status"], params["limit"]) == ("completed", "2") and params["since"].startswith("20")
    table = runner.invoke(app, ["--output", "table", "simulations", "list"], env={"COLUMNS": "200"})
    assert table.exit_code == 0 and "4334" in table.stdout and "of 7" in table.stdout
    assert "simulator_id" in table.stdout and "138" in table.stdout
    shown = json.loads(invoke("simulations", "show", "4334").stdout)
    assert (shown["event_count"], shown["dataset_count"]) == (21, 2)
    assert invoke("simulations", "list", "--since", "yesterday").exit_code == 2


def test_parse_since() -> None:
    from compose_api_client.cli.commands import parse_since

    now = datetime.datetime.now(tz=datetime.UTC)
    assert abs((now - parse_since("6h")).total_seconds() - 6 * 3600) < 5
    assert parse_since("2026-10-07T12:00:00") == datetime.datetime(2026, 10, 7, 12, tzinfo=datetime.UTC)
    assert parse_since("2026-10-07T12:00:00Z").tzinfo is not None


def test_every_command_takes_json(service: Callable[..., FakeService]) -> None:
    """--json, given after the command, overrides --output table: added to every command by ``handled``."""
    from compose_api_client.cli.commands import app as cli_app
    from typer.main import get_command

    group = get_command(cli_app)
    commands = [
        (name, sub)
        for name, cmd in group.commands.items()  # type: ignore[attr-defined]
        for name, sub in ([(name, cmd)] if not hasattr(cmd, "commands") else cmd.commands.items())
    ]
    assert commands and all(any(p.name == "json_output" for p in sub.params) for _, sub in commands)

    service()
    r = runner.invoke(app, ["--output", "table", "simulations", "show", "4334", "--json"])
    assert r.exit_code == 0 and json.loads(r.stdout)["event_count"] == 21
    assert json.loads(runner.invoke(app, ["--output", "table", "version", "--json"]).stdout) == "0.6.0"
