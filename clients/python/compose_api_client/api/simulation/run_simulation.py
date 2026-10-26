from http import HTTPStatus
from typing import Any, cast

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.body_run_simulation import BodyRunSimulation
from ...models.http_validation_error import HTTPValidationError
from ...models.simulation_experiment import SimulationExperiment
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    body: BodyRunSimulation,
    interval_time: float | Unset = 1.0,
    batch_submission: bool | Unset = False,
    simulator: None | str | Unset = UNSET,
    tags: list[str] | None | Unset = UNSET,
    description: None | str | Unset = UNSET,
    environment: None | str | Unset = UNSET,
    environment_version: int | None | Unset = UNSET,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    params: dict[str, Any] = {}

    params["interval_time"] = interval_time

    params["batch_submission"] = batch_submission

    json_simulator: None | str | Unset
    if isinstance(simulator, Unset):
        json_simulator = UNSET
    else:
        json_simulator = simulator
    params["simulator"] = json_simulator

    json_tags: list[str] | None | Unset
    if isinstance(tags, Unset):
        json_tags = UNSET
    elif isinstance(tags, list):
        json_tags = tags

    else:
        json_tags = tags
    params["tags"] = json_tags

    json_description: None | str | Unset
    if isinstance(description, Unset):
        json_description = UNSET
    else:
        json_description = description
    params["description"] = json_description

    json_environment: None | str | Unset
    if isinstance(environment, Unset):
        json_environment = UNSET
    else:
        json_environment = environment
    params["environment"] = json_environment

    json_environment_version: int | None | Unset
    if isinstance(environment_version, Unset):
        json_environment_version = UNSET
    else:
        json_environment_version = environment_version
    params["environment_version"] = json_environment_version

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/simulation/run",
        "params": params,
    }

    _kwargs["files"] = body.to_multipart()

    headers["Content-Type"] = "multipart/form-data; boundary=+++"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Any | HTTPValidationError | SimulationExperiment | None:
    if response.status_code == 200:
        response_200 = SimulationExperiment.from_dict(response.json())

        return response_200

    if response.status_code == 400:
        response_400 = cast(Any, None)
        return response_400

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[Any | HTTPValidationError | SimulationExperiment]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: BodyRunSimulation,
    interval_time: float | Unset = 1.0,
    batch_submission: bool | Unset = False,
    simulator: None | str | Unset = UNSET,
    tags: list[str] | None | Unset = UNSET,
    description: None | str | Unset = UNSET,
    environment: None | str | Unset = UNSET,
    environment_version: int | None | Unset = UNSET,
) -> Response[Any | HTTPValidationError | SimulationExperiment]:
    """Run a simulation

     `environment` names the environment to run in; `simulator` is the older way to name a prebuilt one
    (an
    owner-published image this deployment lists, settings.prebuilt_simulators). With neither, and no
    `environment_version`, the environment is inferred from the classes the documents name
    (docs/plan-environment-composition.md, step 7a): the shared environment for everything it provides,
    as before;
    otherwise the smallest offered environment that provides them all.
    `environment_version` picks a version of that environment (docs/plan-environment-versions.md); the
    run is labelled
    `environment_version=<environment>@<number>` either way.

    The run is labelled `source=upload` and `environment=<simulator or registry_env>`; `tags` and
    `description` are
    stored with it as given (compose_api/simulation/labels.py) and filter `GET /simulations`.

    Args:
        interval_time (float | Unset):  Default: 1.0.
        batch_submission (bool | Unset):  Default: False.
        simulator (None | str | Unset):
        tags (list[str] | None | Unset): Tags to find the run by later; at most 20, each up to 64
            characters
        description (None | str | Unset): What the run is for; up to 2000 characters
        environment (None | str | Unset): The environment to run in, by name (GET
            /registry/environments lists them). Omitted with `simulator` and `environment_version`:
            inferred from the classes the documents name
        environment_version (int | None | Unset): The version of the environment to run in
            (registry_env@3 is 3, or of the prebuilt simulator named); omitted: its default. GET
            /registry/environments/{name}/versions lists them
        body (BodyRunSimulation):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError | SimulationExperiment]
    """

    kwargs = _get_kwargs(
        body=body,
        interval_time=interval_time,
        batch_submission=batch_submission,
        simulator=simulator,
        tags=tags,
        description=description,
        environment=environment,
        environment_version=environment_version,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient | Client,
    body: BodyRunSimulation,
    interval_time: float | Unset = 1.0,
    batch_submission: bool | Unset = False,
    simulator: None | str | Unset = UNSET,
    tags: list[str] | None | Unset = UNSET,
    description: None | str | Unset = UNSET,
    environment: None | str | Unset = UNSET,
    environment_version: int | None | Unset = UNSET,
) -> Any | HTTPValidationError | SimulationExperiment | None:
    """Run a simulation

     `environment` names the environment to run in; `simulator` is the older way to name a prebuilt one
    (an
    owner-published image this deployment lists, settings.prebuilt_simulators). With neither, and no
    `environment_version`, the environment is inferred from the classes the documents name
    (docs/plan-environment-composition.md, step 7a): the shared environment for everything it provides,
    as before;
    otherwise the smallest offered environment that provides them all.
    `environment_version` picks a version of that environment (docs/plan-environment-versions.md); the
    run is labelled
    `environment_version=<environment>@<number>` either way.

    The run is labelled `source=upload` and `environment=<simulator or registry_env>`; `tags` and
    `description` are
    stored with it as given (compose_api/simulation/labels.py) and filter `GET /simulations`.

    Args:
        interval_time (float | Unset):  Default: 1.0.
        batch_submission (bool | Unset):  Default: False.
        simulator (None | str | Unset):
        tags (list[str] | None | Unset): Tags to find the run by later; at most 20, each up to 64
            characters
        description (None | str | Unset): What the run is for; up to 2000 characters
        environment (None | str | Unset): The environment to run in, by name (GET
            /registry/environments lists them). Omitted with `simulator` and `environment_version`:
            inferred from the classes the documents name
        environment_version (int | None | Unset): The version of the environment to run in
            (registry_env@3 is 3, or of the prebuilt simulator named); omitted: its default. GET
            /registry/environments/{name}/versions lists them
        body (BodyRunSimulation):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError | SimulationExperiment
    """

    return sync_detailed(
        client=client,
        body=body,
        interval_time=interval_time,
        batch_submission=batch_submission,
        simulator=simulator,
        tags=tags,
        description=description,
        environment=environment,
        environment_version=environment_version,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: BodyRunSimulation,
    interval_time: float | Unset = 1.0,
    batch_submission: bool | Unset = False,
    simulator: None | str | Unset = UNSET,
    tags: list[str] | None | Unset = UNSET,
    description: None | str | Unset = UNSET,
    environment: None | str | Unset = UNSET,
    environment_version: int | None | Unset = UNSET,
) -> Response[Any | HTTPValidationError | SimulationExperiment]:
    """Run a simulation

     `environment` names the environment to run in; `simulator` is the older way to name a prebuilt one
    (an
    owner-published image this deployment lists, settings.prebuilt_simulators). With neither, and no
    `environment_version`, the environment is inferred from the classes the documents name
    (docs/plan-environment-composition.md, step 7a): the shared environment for everything it provides,
    as before;
    otherwise the smallest offered environment that provides them all.
    `environment_version` picks a version of that environment (docs/plan-environment-versions.md); the
    run is labelled
    `environment_version=<environment>@<number>` either way.

    The run is labelled `source=upload` and `environment=<simulator or registry_env>`; `tags` and
    `description` are
    stored with it as given (compose_api/simulation/labels.py) and filter `GET /simulations`.

    Args:
        interval_time (float | Unset):  Default: 1.0.
        batch_submission (bool | Unset):  Default: False.
        simulator (None | str | Unset):
        tags (list[str] | None | Unset): Tags to find the run by later; at most 20, each up to 64
            characters
        description (None | str | Unset): What the run is for; up to 2000 characters
        environment (None | str | Unset): The environment to run in, by name (GET
            /registry/environments lists them). Omitted with `simulator` and `environment_version`:
            inferred from the classes the documents name
        environment_version (int | None | Unset): The version of the environment to run in
            (registry_env@3 is 3, or of the prebuilt simulator named); omitted: its default. GET
            /registry/environments/{name}/versions lists them
        body (BodyRunSimulation):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError | SimulationExperiment]
    """

    kwargs = _get_kwargs(
        body=body,
        interval_time=interval_time,
        batch_submission=batch_submission,
        simulator=simulator,
        tags=tags,
        description=description,
        environment=environment,
        environment_version=environment_version,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    body: BodyRunSimulation,
    interval_time: float | Unset = 1.0,
    batch_submission: bool | Unset = False,
    simulator: None | str | Unset = UNSET,
    tags: list[str] | None | Unset = UNSET,
    description: None | str | Unset = UNSET,
    environment: None | str | Unset = UNSET,
    environment_version: int | None | Unset = UNSET,
) -> Any | HTTPValidationError | SimulationExperiment | None:
    """Run a simulation

     `environment` names the environment to run in; `simulator` is the older way to name a prebuilt one
    (an
    owner-published image this deployment lists, settings.prebuilt_simulators). With neither, and no
    `environment_version`, the environment is inferred from the classes the documents name
    (docs/plan-environment-composition.md, step 7a): the shared environment for everything it provides,
    as before;
    otherwise the smallest offered environment that provides them all.
    `environment_version` picks a version of that environment (docs/plan-environment-versions.md); the
    run is labelled
    `environment_version=<environment>@<number>` either way.

    The run is labelled `source=upload` and `environment=<simulator or registry_env>`; `tags` and
    `description` are
    stored with it as given (compose_api/simulation/labels.py) and filter `GET /simulations`.

    Args:
        interval_time (float | Unset):  Default: 1.0.
        batch_submission (bool | Unset):  Default: False.
        simulator (None | str | Unset):
        tags (list[str] | None | Unset): Tags to find the run by later; at most 20, each up to 64
            characters
        description (None | str | Unset): What the run is for; up to 2000 characters
        environment (None | str | Unset): The environment to run in, by name (GET
            /registry/environments lists them). Omitted with `simulator` and `environment_version`:
            inferred from the classes the documents name
        environment_version (int | None | Unset): The version of the environment to run in
            (registry_env@3 is 3, or of the prebuilt simulator named); omitted: its default. GET
            /registry/environments/{name}/versions lists them
        body (BodyRunSimulation):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError | SimulationExperiment
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
            interval_time=interval_time,
            batch_submission=batch_submission,
            simulator=simulator,
            tags=tags,
            description=description,
            environment=environment,
            environment_version=environment_version,
        )
    ).parsed
