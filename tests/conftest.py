import pytest  # noqa: F401
import pytest_asyncio  # noqa: F401

from tests.fixtures.api_fixtures import (  # noqa: F401
    fastapi_app,
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
from tests.fixtures.simulation_fixtures import (  # noqa: F401
    simulation_service_slurm,
)
from tests.fixtures.slurm_fixtures import (  # noqa: F401
    slurm_service,
    slurm_template_hello_1s,
    slurm_template_hello_10s,
    slurm_template_hello_TEMPLATE,
    ssh_service,
)
