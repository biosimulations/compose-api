from http import HTTPStatus
from typing import Any, cast

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.get_simulation_trace_chrome_response_get_simulation_trace_chrome import (
    GetSimulationTraceChromeResponseGetSimulationTraceChrome,
)
from ...models.http_validation_error import HTTPValidationError
from ...types import UNSET, Response


def _get_kwargs(
    *,
    simulation_id: int,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    params["simulation_id"] = simulation_id

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/results/simulation/trace/chrome",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Any | GetSimulationTraceChromeResponseGetSimulationTraceChrome | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = GetSimulationTraceChromeResponseGetSimulationTraceChrome.from_dict(response.json())

        return response_200

    if response.status_code == 404:
        response_404 = cast(Any, None)
        return response_404

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[Any | GetSimulationTraceChromeResponseGetSimulationTraceChrome | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    simulation_id: int,
) -> Response[Any | GetSimulationTraceChromeResponseGetSimulationTraceChrome | HTTPValidationError]:
    """Get a simulation's trace as a Chrome Trace Event document (open it in ui.perfetto.dev)

    Args:
        simulation_id (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | GetSimulationTraceChromeResponseGetSimulationTraceChrome | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        simulation_id=simulation_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient | Client,
    simulation_id: int,
) -> Any | GetSimulationTraceChromeResponseGetSimulationTraceChrome | HTTPValidationError | None:
    """Get a simulation's trace as a Chrome Trace Event document (open it in ui.perfetto.dev)

    Args:
        simulation_id (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | GetSimulationTraceChromeResponseGetSimulationTraceChrome | HTTPValidationError
    """

    return sync_detailed(
        client=client,
        simulation_id=simulation_id,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    simulation_id: int,
) -> Response[Any | GetSimulationTraceChromeResponseGetSimulationTraceChrome | HTTPValidationError]:
    """Get a simulation's trace as a Chrome Trace Event document (open it in ui.perfetto.dev)

    Args:
        simulation_id (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | GetSimulationTraceChromeResponseGetSimulationTraceChrome | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        simulation_id=simulation_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    simulation_id: int,
) -> Any | GetSimulationTraceChromeResponseGetSimulationTraceChrome | HTTPValidationError | None:
    """Get a simulation's trace as a Chrome Trace Event document (open it in ui.perfetto.dev)

    Args:
        simulation_id (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | GetSimulationTraceChromeResponseGetSimulationTraceChrome | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            client=client,
            simulation_id=simulation_id,
        )
    ).parsed
