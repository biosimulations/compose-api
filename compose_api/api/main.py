import importlib
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from compose_api.common.gateway.models import ServerMode
from compose_api.config import get_settings
from compose_api.dependencies import (
    get_job_monitor,
    init_standalone,
    set_data_service,
    shutdown_standalone,
)
from compose_api.version import __version__
from tests.fixtures.mocks import TestDataService

logger = logging.getLogger(__name__)


APP_VERSION = __version__
APP_TITLE = "compose-api"
APP_ORIGINS = [
    "http://0.0.0.0:8000",
    "http://127.0.0.1:8000",
    "http://127.0.0.1:8888",
    "http://127.0.0.1:4200",
    "http://127.0.0.1:4201",
    "http://127.0.0.1:4202",
    "http://localhost:4200",
    "http://localhost:4201",
    "http://localhost:4202",
    "http://localhost:8888",
    "http://localhost:8000",
    "http://localhost:3001",
    "https://compose_api.cam.uchc.edu",
]

# APP_SERVERS: list[dict[str, str]] = [
#     {"url": ServerMode.PROD, "description": "Production server"},
#     {"url": ServerMode.DEV, "description": "Main Development server"},
#     {"url": ServerMode.PORT_FORWARD_DEV, "description": "Local port-forward"},
# ]
APP_SERVERS = None
APP_ROUTERS = ["core"]  # for now, just referencing core
assets_dir = Path(get_settings().assets_dir)
ACTIVE_URL = ServerMode.detect(assets_dir / "dev" / "config" / ".dev_env")


# -- app configuration: lifespan and middleware -- #


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    # configure and start standalone services (data, sim, db, etc)
    dev_mode = os.getenv("DEV_MODE", "0")
    start_standalone = partial(init_standalone)
    if bool(int(dev_mode)):
        logger.warning("Development Mode is currently engaged!!!", stacklevel=1)
        start_standalone.keywords["enable_ssl"] = True
        set_data_service(TestDataService())  # Won't require mounting file system
    await start_standalone()

    # --- JobMonitor setup ---
    job_monitor = get_job_monitor()
    if not job_monitor:
        raise RuntimeError("JobMonitor is not initialized. Please check your configuration.")
    if get_settings().hpc_has_messaging:
        await job_monitor.subscribe_nats()
    await job_monitor.start_polling(interval_seconds=5)  # configurable interval

    try:
        yield
    finally:
        await job_monitor.close()
    await shutdown_standalone()


app = FastAPI(title=APP_TITLE, version=APP_VERSION, servers=APP_SERVERS, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=APP_ORIGINS, allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)
for api_name in APP_ROUTERS:
    try:
        api = importlib.import_module(f"compose_api.api.routers.{api_name}")
        app.include_router(
            api.config.router,
            prefix=api.config.prefix,
            dependencies=api.config.dependencies,
        )
    except Exception:
        logger.exception(f"Could not register the following api: {api_name}")


# -- app-level endpoints -- #


@app.get("/health", tags=["BIOSIM API"])
async def check_health() -> dict[str, str]:
    return {"docs": f"{ACTIVE_URL}{app.docs_url}", "version": APP_VERSION}


@app.get("/version", tags=["BIOSIM API"])
async def get_version() -> str:
    return APP_VERSION


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, loop="auto")  # noqa: S104 binding to all interfaces
    logger.info("API Gateway Server started")
