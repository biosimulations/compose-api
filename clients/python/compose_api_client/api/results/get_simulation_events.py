from http import HTTPStatus
from typing import Any, cast

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.run_event_page import RunEventPage
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    after: int | None | Unset = UNSET,
    limit: int | Unset = 500,
    level: None | str | Unset = UNSET,
    event: None | str | Unset = UNSET,
    span_id: None | str | Unset = UNSET,
    simulation_id: int,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_after: int | None | Unset
    if isinstance(after, Unset):
        json_after = UNSET
    else:
        json_after = after
    params["after"] = json_after

    params["limit"] = limit

    json_level: None | str | Unset
    if isinstance(level, Unset):
        json_level = UNSET
    else:
        json_level = level
    params["level"] = json_level

    json_event: None | str | Unset
    if isinstance(event, Unset):
        json_event = UNSET
    else:
        json_event = event
    params["event"] = json_event

    json_span_id: None | str | Unset
    if isinstance(span_id, Unset):
        json_span_id = UNSET
    else:
        json_span_id = span_id
    params["span_id"] = json_span_id

    params["simulation_id"] = simulation_id

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/results/simulation/events",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Any | HTTPValidationError | RunEventPage | None:
    if response.status_code == 200:
        response_200 = RunEventPage.from_dict(response.json())

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
) -> Response[Any | HTTPValidationError | RunEventPage]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    after: int | None | Unset = UNSET,
    limit: int | Unset = 500,
    level: None | str | Unset = UNSET,
    event: None | str | Unset = UNSET,
    span_id: None | str | Unset = UNSET,
    simulation_id: int,
) -> Response[Any | HTTPValidationError | RunEventPage]:
    """Get a page of a simulation's events, in the order they were recorded

    Args:
        after (int | None | Unset): Return events after this cursor (a previous page's next)
        limit (int | Unset):  Default: 500.
        level (None | str | Unset): Only events at this level (debug, info, warning, error)
        event (None | str | Unset): Only events with this name, e.g. job.end
        span_id (None | str | Unset): Only events inside this span
        simulation_id (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError | RunEventPage]
    """

    kwargs = _get_kwargs(
        after=after,
        limit=limit,
        level=level,
        event=event,
        span_id=span_id,
        simulation_id=simulation_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient | Client,
    after: int | None | Unset = UNSET,
    limit: int | Unset = 500,
    level: None | str | Unset = UNSET,
    event: None | str | Unset = UNSET,
    span_id: None | str | Unset = UNSET,
    simulation_id: int,
) -> Any | HTTPValidationError | RunEventPage | None:
    """Get a page of a simulation's events, in the order they were recorded

    Args:
        after (int | None | Unset): Return events after this cursor (a previous page's next)
        limit (int | Unset):  Default: 500.
        level (None | str | Unset): Only events at this level (debug, info, warning, error)
        event (None | str | Unset): Only events with this name, e.g. job.end
        span_id (None | str | Unset): Only events inside this span
        simulation_id (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError | RunEventPage
    """

    return sync_detailed(
        client=client,
        after=after,
        limit=limit,
        level=level,
        event=event,
        span_id=span_id,
        simulation_id=simulation_id,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    after: int | None | Unset = UNSET,
    limit: int | Unset = 500,
    level: None | str | Unset = UNSET,
    event: None | str | Unset = UNSET,
    span_id: None | str | Unset = UNSET,
    simulation_id: int,
) -> Response[Any | HTTPValidationError | RunEventPage]:
    """Get a page of a simulation's events, in the order they were recorded

    Args:
        after (int | None | Unset): Return events after this cursor (a previous page's next)
        limit (int | Unset):  Default: 500.
        level (None | str | Unset): Only events at this level (debug, info, warning, error)
        event (None | str | Unset): Only events with this name, e.g. job.end
        span_id (None | str | Unset): Only events inside this span
        simulation_id (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError | RunEventPage]
    """

    kwargs = _get_kwargs(
        after=after,
        limit=limit,
        level=level,
        event=event,
        span_id=span_id,
        simulation_id=simulation_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    after: int | None | Unset = UNSET,
    limit: int | Unset = 500,
    level: None | str | Unset = UNSET,
    event: None | str | Unset = UNSET,
    span_id: None | str | Unset = UNSET,
    simulation_id: int,
) -> Any | HTTPValidationError | RunEventPage | None:
    """Get a page of a simulation's events, in the order they were recorded

    Args:
        after (int | None | Unset): Return events after this cursor (a previous page's next)
        limit (int | Unset):  Default: 500.
        level (None | str | Unset): Only events at this level (debug, info, warning, error)
        event (None | str | Unset): Only events with this name, e.g. job.end
        span_id (None | str | Unset): Only events inside this span
        simulation_id (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError | RunEventPage
    """

    return (
        await asyncio_detailed(
            client=client,
            after=after,
            limit=limit,
            level=level,
            event=event,
            span_id=span_id,
            simulation_id=simulation_id,
        )
    ).parsed
