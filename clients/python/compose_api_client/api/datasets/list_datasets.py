from http import HTTPStatus
from typing import Any, cast

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.dataset_page import DatasetPage
from ...models.http_validation_error import HTTPValidationError
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    simulation_id: int | None | Unset = UNSET,
    kind: None | str | Unset = UNSET,
    q: None | str | Unset = UNSET,
    available: bool | None | Unset = True,
    limit: int | Unset = 100,
    offset: int | Unset = 0,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_simulation_id: int | None | Unset
    if isinstance(simulation_id, Unset):
        json_simulation_id = UNSET
    else:
        json_simulation_id = simulation_id
    params["simulation_id"] = json_simulation_id

    json_kind: None | str | Unset
    if isinstance(kind, Unset):
        json_kind = UNSET
    else:
        json_kind = kind
    params["kind"] = json_kind

    json_q: None | str | Unset
    if isinstance(q, Unset):
        json_q = UNSET
    else:
        json_q = q
    params["q"] = json_q

    json_available: bool | None | Unset
    if isinstance(available, Unset):
        json_available = UNSET
    else:
        json_available = available
    params["available"] = json_available

    params["limit"] = limit

    params["offset"] = offset

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/datasets",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Any | DatasetPage | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = DatasetPage.from_dict(response.json())

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
) -> Response[Any | DatasetPage | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    simulation_id: int | None | Unset = UNSET,
    kind: None | str | Unset = UNSET,
    q: None | str | Unset = UNSET,
    available: bool | None | Unset = True,
    limit: int | Unset = 100,
    offset: int | Unset = 0,
) -> Response[Any | DatasetPage | HTTPValidationError]:
    """List the datasets runs advertised, newest simulations first

    Args:
        simulation_id (int | None | Unset): Only this simulation's datasets
        kind (None | str | Unset): Only this kind, e.g. results, table, figure, archive
        q (None | str | Unset): Only datasets whose path or name contains this
        available (bool | None | Unset): Only files that still exist (false: only missing)
            Default: True.
        limit (int | Unset):  Default: 100.
        offset (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | DatasetPage | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        simulation_id=simulation_id,
        kind=kind,
        q=q,
        available=available,
        limit=limit,
        offset=offset,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient | Client,
    simulation_id: int | None | Unset = UNSET,
    kind: None | str | Unset = UNSET,
    q: None | str | Unset = UNSET,
    available: bool | None | Unset = True,
    limit: int | Unset = 100,
    offset: int | Unset = 0,
) -> Any | DatasetPage | HTTPValidationError | None:
    """List the datasets runs advertised, newest simulations first

    Args:
        simulation_id (int | None | Unset): Only this simulation's datasets
        kind (None | str | Unset): Only this kind, e.g. results, table, figure, archive
        q (None | str | Unset): Only datasets whose path or name contains this
        available (bool | None | Unset): Only files that still exist (false: only missing)
            Default: True.
        limit (int | Unset):  Default: 100.
        offset (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | DatasetPage | HTTPValidationError
    """

    return sync_detailed(
        client=client,
        simulation_id=simulation_id,
        kind=kind,
        q=q,
        available=available,
        limit=limit,
        offset=offset,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    simulation_id: int | None | Unset = UNSET,
    kind: None | str | Unset = UNSET,
    q: None | str | Unset = UNSET,
    available: bool | None | Unset = True,
    limit: int | Unset = 100,
    offset: int | Unset = 0,
) -> Response[Any | DatasetPage | HTTPValidationError]:
    """List the datasets runs advertised, newest simulations first

    Args:
        simulation_id (int | None | Unset): Only this simulation's datasets
        kind (None | str | Unset): Only this kind, e.g. results, table, figure, archive
        q (None | str | Unset): Only datasets whose path or name contains this
        available (bool | None | Unset): Only files that still exist (false: only missing)
            Default: True.
        limit (int | Unset):  Default: 100.
        offset (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | DatasetPage | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        simulation_id=simulation_id,
        kind=kind,
        q=q,
        available=available,
        limit=limit,
        offset=offset,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    simulation_id: int | None | Unset = UNSET,
    kind: None | str | Unset = UNSET,
    q: None | str | Unset = UNSET,
    available: bool | None | Unset = True,
    limit: int | Unset = 100,
    offset: int | Unset = 0,
) -> Any | DatasetPage | HTTPValidationError | None:
    """List the datasets runs advertised, newest simulations first

    Args:
        simulation_id (int | None | Unset): Only this simulation's datasets
        kind (None | str | Unset): Only this kind, e.g. results, table, figure, archive
        q (None | str | Unset): Only datasets whose path or name contains this
        available (bool | None | Unset): Only files that still exist (false: only missing)
            Default: True.
        limit (int | Unset):  Default: 100.
        offset (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | DatasetPage | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            client=client,
            simulation_id=simulation_id,
            kind=kind,
            q=q,
            available=available,
            limit=limit,
            offset=offset,
        )
    ).parsed
