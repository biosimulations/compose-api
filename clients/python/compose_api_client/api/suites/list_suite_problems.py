from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.error_detail import ErrorDetail
from ...models.http_validation_error import HTTPValidationError
from ...models.known_problem import KnownProblem
from ...types import UNSET, Response, Unset


def _get_kwargs(
    name: str,
    *,
    cleared: bool | None | Unset = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_cleared: bool | None | Unset
    if isinstance(cleared, Unset):
        json_cleared = UNSET
    else:
        json_cleared = cleared
    params["cleared"] = json_cleared

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/suites/{name}/problems".format(
            name=quote(str(name), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ErrorDetail | HTTPValidationError | list[KnownProblem] | None:
    if response.status_code == 200:
        response_200 = []
        _response_200 = response.json()
        for response_200_item_data in _response_200:
            response_200_item = KnownProblem.from_dict(response_200_item_data)

            response_200.append(response_200_item)

        return response_200

    if response.status_code == 404:
        response_404 = ErrorDetail.from_dict(response.json())

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
) -> Response[ErrorDetail | HTTPValidationError | list[KnownProblem]]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    name: str,
    *,
    client: AuthenticatedClient | Client,
    cleared: bool | None | Unset = UNSET,
) -> Response[ErrorDetail | HTTPValidationError | list[KnownProblem]]:
    """A suite's known problems: each solver's expected failures, open and cleared

    Args:
        name (str):
        cleared (bool | None | Unset): only cleared (true) or only open (false) ones

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ErrorDetail | HTTPValidationError | list[KnownProblem]]
    """

    kwargs = _get_kwargs(
        name=name,
        cleared=cleared,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    name: str,
    *,
    client: AuthenticatedClient | Client,
    cleared: bool | None | Unset = UNSET,
) -> ErrorDetail | HTTPValidationError | list[KnownProblem] | None:
    """A suite's known problems: each solver's expected failures, open and cleared

    Args:
        name (str):
        cleared (bool | None | Unset): only cleared (true) or only open (false) ones

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ErrorDetail | HTTPValidationError | list[KnownProblem]
    """

    return sync_detailed(
        name=name,
        client=client,
        cleared=cleared,
    ).parsed


async def asyncio_detailed(
    name: str,
    *,
    client: AuthenticatedClient | Client,
    cleared: bool | None | Unset = UNSET,
) -> Response[ErrorDetail | HTTPValidationError | list[KnownProblem]]:
    """A suite's known problems: each solver's expected failures, open and cleared

    Args:
        name (str):
        cleared (bool | None | Unset): only cleared (true) or only open (false) ones

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ErrorDetail | HTTPValidationError | list[KnownProblem]]
    """

    kwargs = _get_kwargs(
        name=name,
        cleared=cleared,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    name: str,
    *,
    client: AuthenticatedClient | Client,
    cleared: bool | None | Unset = UNSET,
) -> ErrorDetail | HTTPValidationError | list[KnownProblem] | None:
    """A suite's known problems: each solver's expected failures, open and cleared

    Args:
        name (str):
        cleared (bool | None | Unset): only cleared (true) or only open (false) ones

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ErrorDetail | HTTPValidationError | list[KnownProblem]
    """

    return (
        await asyncio_detailed(
            name=name,
            client=client,
            cleared=cleared,
        )
    ).parsed
