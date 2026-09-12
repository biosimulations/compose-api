import pytest
import pytest_asyncio  # noqa: F401

from tests.fixtures.api_fixtures import (  # noqa: F401
    fastapi_app,
    http_api_client,
    in_memory_api_client,
    local_base_url,
)
from tests.fixtures.mongodb_fixtures import (  # noqa: F401
    mongo_test_client,
    mongo_test_collection,
    mongo_test_database,
    mongodb_container,
)
from tests.fixtures.nats_fixtures import (  # noqa: F401
    # jetstream_client,
    nats_container_uri,
    nats_producer_client,
    nats_subscriber_client,
)
from tests.fixtures.postgres_fixtures import async_postgres_engine, database_service, postgres_url  # noqa: F401
from tests.fixtures.simulation_fixtures import job_monitor, simulation_service_slurm, simulator  # noqa: F401
from tests.fixtures.slurm_fixtures import (  # noqa: F401
    data_service,
    simulation_request,
    slurm_service,
    slurm_template_hello_1s,
    slurm_template_hello_10s,
    slurm_template_hello_TEMPLATE,
    ssh_service,
)
from tests.fixtures.slurm_fixtures_backend import (  # noqa: F401
    SlurmBackend,
    _container_cluster,
    cluster_credentials_present,
    docker_available,
    slurm_backend,
)


def pytest_addoption(parser: "pytest.Parser") -> None:
    parser.addoption(
        "--slurm-backend",
        action="append",
        default=[],
        choices=["container", "cluster"],
        help=(
            "Which SLURM backend(s) to run the scheduler tests against. Repeatable. "
            "Defaults to 'container' when Docker is available, otherwise nothing. "
            "Use 'cluster' for the real submit host (needs a key and VPN)."
        ),
    )


def pytest_generate_tests(metafunc: "pytest.Metafunc") -> None:
    """Parameterise any test that asks for a `slurm_backend` over the selected backends.

    One test body, one parameter, so the two backends cannot drift. A test left with no
    backend is skipped with a reason that says what to do, never silently passed.
    """
    if "slurm_backend" not in metafunc.fixturenames:
        return
    chosen: list[str] = list(metafunc.config.getoption("--slurm-backend"))
    if not chosen:
        chosen = ["container"] if docker_available() else []

    if any(mark.name == "cluster_only" for mark in metafunc.definition.iter_markers()):
        # The container has no simulator images and cannot run a --fakeroot singularity
        # build, so these need the real submit host and only run when it is asked for.
        chosen = [kind for kind in chosen if kind == "cluster"]
        reason = "needs the real SLURM cluster: rerun with --slurm-backend cluster"
    else:
        reason = "no SLURM backend selected: start Docker, or pass --slurm-backend"

    params: list[object] = list(chosen) or [pytest.param(None, marks=pytest.mark.skip(reason=reason), id="unavailable")]
    metafunc.parametrize("slurm_backend", params, indirect=True, scope="session")
