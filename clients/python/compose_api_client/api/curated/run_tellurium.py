from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.body_run_tellurium import BodyRunTellurium
from ...models.http_validation_error import HTTPValidationError
from ...models.simulation_experiment import SimulationExperiment
from ...models.visibility import Visibility
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    body: BodyRunTellurium,
    start_time: float,
    end_time: float,
    num_data_points: float,
    visibility: None | Unset | Visibility = UNSET,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    params: dict[str, Any] = {}

    params["start_time"] = start_time

    params["end_time"] = end_time

    params["num_data_points"] = num_data_points

    json_visibility: None | str | Unset
    if isinstance(visibility, Unset):
        json_visibility = UNSET
    elif isinstance(visibility, Visibility):
        json_visibility = visibility.value
    else:
        json_visibility = visibility
    params["visibility"] = json_visibility

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/curated/tellurium",
        "params": params,
    }

    _kwargs["files"] = body.to_multipart()

    headers["Content-Type"] = "multipart/form-data; boundary=+++"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | SimulationExperiment | None:
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
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[HTTPValidationError | SimulationExperiment]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: BodyRunTellurium,
    start_time: float,
    end_time: float,
    num_data_points: float,
    visibility: None | Unset | Visibility = UNSET,
) -> Response[HTTPValidationError | SimulationExperiment]:
    """Use the tool tellurium.

    Args:
        start_time (float):
        end_time (float):
        num_data_points (float):
        visibility (None | Unset | Visibility): Who may read the run: `private` (the default when
            signed in: you, and admins) or `public` (anyone). Anonymous runs are public; asking for
            private needs signing in. The owner can change it later (PATCH /simulations/{id})
        body (BodyRunTellurium):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | SimulationExperiment]
    """

    kwargs = _get_kwargs(
        body=body,
        start_time=start_time,
        end_time=end_time,
        num_data_points=num_data_points,
        visibility=visibility,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient | Client,
    body: BodyRunTellurium,
    start_time: float,
    end_time: float,
    num_data_points: float,
    visibility: None | Unset | Visibility = UNSET,
) -> HTTPValidationError | SimulationExperiment | None:
    """Use the tool tellurium.

    Args:
        start_time (float):
        end_time (float):
        num_data_points (float):
        visibility (None | Unset | Visibility): Who may read the run: `private` (the default when
            signed in: you, and admins) or `public` (anyone). Anonymous runs are public; asking for
            private needs signing in. The owner can change it later (PATCH /simulations/{id})
        body (BodyRunTellurium):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | SimulationExperiment
    """

    return sync_detailed(
        client=client,
        body=body,
        start_time=start_time,
        end_time=end_time,
        num_data_points=num_data_points,
        visibility=visibility,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: BodyRunTellurium,
    start_time: float,
    end_time: float,
    num_data_points: float,
    visibility: None | Unset | Visibility = UNSET,
) -> Response[HTTPValidationError | SimulationExperiment]:
    """Use the tool tellurium.

    Args:
        start_time (float):
        end_time (float):
        num_data_points (float):
        visibility (None | Unset | Visibility): Who may read the run: `private` (the default when
            signed in: you, and admins) or `public` (anyone). Anonymous runs are public; asking for
            private needs signing in. The owner can change it later (PATCH /simulations/{id})
        body (BodyRunTellurium):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | SimulationExperiment]
    """

    kwargs = _get_kwargs(
        body=body,
        start_time=start_time,
        end_time=end_time,
        num_data_points=num_data_points,
        visibility=visibility,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    body: BodyRunTellurium,
    start_time: float,
    end_time: float,
    num_data_points: float,
    visibility: None | Unset | Visibility = UNSET,
) -> HTTPValidationError | SimulationExperiment | None:
    """Use the tool tellurium.

    Args:
        start_time (float):
        end_time (float):
        num_data_points (float):
        visibility (None | Unset | Visibility): Who may read the run: `private` (the default when
            signed in: you, and admins) or `public` (anyone). Anonymous runs are public; asking for
            private needs signing in. The owner can change it later (PATCH /simulations/{id})
        body (BodyRunTellurium):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | SimulationExperiment
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
            start_time=start_time,
            end_time=end_time,
            num_data_points=num_data_points,
            visibility=visibility,
        )
    ).parsed
