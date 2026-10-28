from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.error_detail import ErrorDetail
from ...models.http_validation_error import HTTPValidationError
from ...models.suite_run_view import SuiteRunView
from ...types import Response


def _get_kwargs(
    name: str,
    number: int,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/suites/{name}/runs/{number}".format(
            name=quote(str(name), safe=""),
            number=quote(str(number), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ErrorDetail | HTTPValidationError | SuiteRunView | None:
    if response.status_code == 200:
        response_200 = SuiteRunView.from_dict(response.json())

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
) -> Response[ErrorDetail | HTTPValidationError | SuiteRunView]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    name: str,
    number: int,
    *,
    client: AuthenticatedClient | Client,
) -> Response[ErrorDetail | HTTPValidationError | SuiteRunView]:
    """One suite run: per source, agreement, references, and drift from the baseline run

    Args:
        name (str):
        number (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ErrorDetail | HTTPValidationError | SuiteRunView]
    """

    kwargs = _get_kwargs(
        name=name,
        number=number,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    name: str,
    number: int,
    *,
    client: AuthenticatedClient | Client,
) -> ErrorDetail | HTTPValidationError | SuiteRunView | None:
    """One suite run: per source, agreement, references, and drift from the baseline run

    Args:
        name (str):
        number (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ErrorDetail | HTTPValidationError | SuiteRunView
    """

    return sync_detailed(
        name=name,
        number=number,
        client=client,
    ).parsed


async def asyncio_detailed(
    name: str,
    number: int,
    *,
    client: AuthenticatedClient | Client,
) -> Response[ErrorDetail | HTTPValidationError | SuiteRunView]:
    """One suite run: per source, agreement, references, and drift from the baseline run

    Args:
        name (str):
        number (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ErrorDetail | HTTPValidationError | SuiteRunView]
    """

    kwargs = _get_kwargs(
        name=name,
        number=number,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    name: str,
    number: int,
    *,
    client: AuthenticatedClient | Client,
) -> ErrorDetail | HTTPValidationError | SuiteRunView | None:
    """One suite run: per source, agreement, references, and drift from the baseline run

    Args:
        name (str):
        number (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ErrorDetail | HTTPValidationError | SuiteRunView
    """

    return (
        await asyncio_detailed(
            name=name,
            number=number,
            client=client,
        )
    ).parsed
