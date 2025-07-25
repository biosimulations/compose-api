import pytest


@pytest.fixture(scope="session", autouse=True)
def configure_logging() -> None:
    import biosim_api.dependencies  # noqa: F401. to ensure logging is configured before any tests run
