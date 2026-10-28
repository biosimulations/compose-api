from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.error_detail import ErrorDetail
from ...models.http_validation_error import HTTPValidationError
from ...models.known_problem import KnownProblem
from ...models.known_problem_mark import KnownProblemMark
from ...types import Response


def _get_kwargs(
    name: str,
    *,
    body: KnownProblemMark,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/suites/{name}/problems".format(
            name=quote(str(name), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ErrorDetail | HTTPValidationError | KnownProblem | None:
    if response.status_code == 201:
        response_201 = KnownProblem.from_dict(response.json())

        return response_201

    if response.status_code == 400:
        response_400 = ErrorDetail.from_dict(response.json())

        return response_400

    if response.status_code == 401:
        response_401 = ErrorDetail.from_dict(response.json())

        return response_401

    if response.status_code == 403:
        response_403 = ErrorDetail.from_dict(response.json())

        return response_403

    if response.status_code == 404:
        response_404 = ErrorDetail.from_dict(response.json())

        return response_404

    if response.status_code == 409:
        response_409 = ErrorDetail.from_dict(response.json())

        return response_409

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[ErrorDetail | HTTPValidationError | KnownProblem]:
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
    body: KnownProblemMark,
) -> Response[ErrorDetail | HTTPValidationError | KnownProblem]:
    """Record a known problem of a solver on one of the suite's sources

    Args:
        name (str):
        body (KnownProblemMark): A known problem to record: the source and solver (none for the
            whole source), and why.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ErrorDetail | HTTPValidationError | KnownProblem]
    """

    kwargs = _get_kwargs(
        name=name,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    name: str,
    *,
    client: AuthenticatedClient | Client,
    body: KnownProblemMark,
) -> ErrorDetail | HTTPValidationError | KnownProblem | None:
    """Record a known problem of a solver on one of the suite's sources

    Args:
        name (str):
        body (KnownProblemMark): A known problem to record: the source and solver (none for the
            whole source), and why.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ErrorDetail | HTTPValidationError | KnownProblem
    """

    return sync_detailed(
        name=name,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    name: str,
    *,
    client: AuthenticatedClient | Client,
    body: KnownProblemMark,
) -> Response[ErrorDetail | HTTPValidationError | KnownProblem]:
    """Record a known problem of a solver on one of the suite's sources

    Args:
        name (str):
        body (KnownProblemMark): A known problem to record: the source and solver (none for the
            whole source), and why.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ErrorDetail | HTTPValidationError | KnownProblem]
    """

    kwargs = _get_kwargs(
        name=name,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    name: str,
    *,
    client: AuthenticatedClient | Client,
    body: KnownProblemMark,
) -> ErrorDetail | HTTPValidationError | KnownProblem | None:
    """Record a known problem of a solver on one of the suite's sources

    Args:
        name (str):
        body (KnownProblemMark): A known problem to record: the source and solver (none for the
            whole source), and why.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ErrorDetail | HTTPValidationError | KnownProblem
    """

    return (
        await asyncio_detailed(
            name=name,
            client=client,
            body=body,
        )
    ).parsed
