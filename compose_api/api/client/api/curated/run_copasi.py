from http import HTTPStatus
from typing import Any, Optional, Union, cast

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.body_run_copasi import BodyRunCopasi
from ...models.http_validation_error import HTTPValidationError
from ...models.simulation_experiment import SimulationExperiment
from typing import cast


def _get_kwargs(
    *,
    body: BodyRunCopasi,
    start_time: float,
    duration: float,
    num_data_points: float,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    params: dict[str, Any] = {}

    params["start_time"] = start_time

    params["duration"] = duration

    params["num_data_points"] = num_data_points

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/curated/copasi",
        "params": params,
    }

    _kwargs["files"] = body.to_multipart()

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: Union[AuthenticatedClient, Client], response: httpx.Response
) -> Optional[Union[HTTPValidationError, SimulationExperiment]]:
    if response.status_code == 200:
        response_200 = SimulationExperiment.from_dict(response.json())

        return response_200
    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422
    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: Union[AuthenticatedClient, Client], response: httpx.Response
) -> Response[Union[HTTPValidationError, SimulationExperiment]]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: Union[AuthenticatedClient, Client],
    body: BodyRunCopasi,
    start_time: float,
    duration: float,
    num_data_points: float,
) -> Response[Union[HTTPValidationError, SimulationExperiment]]:
    """Use the tool copasi.

    Args:
        start_time (float):
        duration (float):
        num_data_points (float):
        body (BodyRunCopasi):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Union[HTTPValidationError, SimulationExperiment]]
    """

    kwargs = _get_kwargs(
        body=body,
        start_time=start_time,
        duration=duration,
        num_data_points=num_data_points,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: Union[AuthenticatedClient, Client],
    body: BodyRunCopasi,
    start_time: float,
    duration: float,
    num_data_points: float,
) -> Optional[Union[HTTPValidationError, SimulationExperiment]]:
    """Use the tool copasi.

    Args:
        start_time (float):
        duration (float):
        num_data_points (float):
        body (BodyRunCopasi):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Union[HTTPValidationError, SimulationExperiment]
    """

    return sync_detailed(
        client=client,
        body=body,
        start_time=start_time,
        duration=duration,
        num_data_points=num_data_points,
    ).parsed


async def asyncio_detailed(
    *,
    client: Union[AuthenticatedClient, Client],
    body: BodyRunCopasi,
    start_time: float,
    duration: float,
    num_data_points: float,
) -> Response[Union[HTTPValidationError, SimulationExperiment]]:
    """Use the tool copasi.

    Args:
        start_time (float):
        duration (float):
        num_data_points (float):
        body (BodyRunCopasi):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Union[HTTPValidationError, SimulationExperiment]]
    """

    kwargs = _get_kwargs(
        body=body,
        start_time=start_time,
        duration=duration,
        num_data_points=num_data_points,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: Union[AuthenticatedClient, Client],
    body: BodyRunCopasi,
    start_time: float,
    duration: float,
    num_data_points: float,
) -> Optional[Union[HTTPValidationError, SimulationExperiment]]:
    """Use the tool copasi.

    Args:
        start_time (float):
        duration (float):
        num_data_points (float):
        body (BodyRunCopasi):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Union[HTTPValidationError, SimulationExperiment]
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
            start_time=start_time,
            duration=duration,
            num_data_points=num_data_points,
        )
    ).parsed
