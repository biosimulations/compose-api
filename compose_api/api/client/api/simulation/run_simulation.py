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
) -> Response[Any | HTTPValidationError | SimulationExperiment]:
    """Run a simulation

     `simulator` names an owner-published image this deployment lists (settings.prebuilt_simulators);
    the job then runs in that image instead of the shared container. Omitted: the shared container.

    Args:
        interval_time (float | Unset):  Default: 1.0.
        batch_submission (bool | Unset):  Default: False.
        simulator (None | str | Unset):
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
) -> Any | HTTPValidationError | SimulationExperiment | None:
    """Run a simulation

     `simulator` names an owner-published image this deployment lists (settings.prebuilt_simulators);
    the job then runs in that image instead of the shared container. Omitted: the shared container.

    Args:
        interval_time (float | Unset):  Default: 1.0.
        batch_submission (bool | Unset):  Default: False.
        simulator (None | str | Unset):
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
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: BodyRunSimulation,
    interval_time: float | Unset = 1.0,
    batch_submission: bool | Unset = False,
    simulator: None | str | Unset = UNSET,
) -> Response[Any | HTTPValidationError | SimulationExperiment]:
    """Run a simulation

     `simulator` names an owner-published image this deployment lists (settings.prebuilt_simulators);
    the job then runs in that image instead of the shared container. Omitted: the shared container.

    Args:
        interval_time (float | Unset):  Default: 1.0.
        batch_submission (bool | Unset):  Default: False.
        simulator (None | str | Unset):
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
) -> Any | HTTPValidationError | SimulationExperiment | None:
    """Run a simulation

     `simulator` names an owner-published image this deployment lists (settings.prebuilt_simulators);
    the job then runs in that image instead of the shared container. Omitted: the shared container.

    Args:
        interval_time (float | Unset):  Default: 1.0.
        batch_submission (bool | Unset):  Default: False.
        simulator (None | str | Unset):
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
        )
    ).parsed
