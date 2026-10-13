from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.comparison import Comparison
from ...models.http_validation_error import HTTPValidationError
from ...types import Response


def _get_kwargs(
    comparison_id: int,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/comparisons/{comparison_id}".format(
            comparison_id=quote(str(comparison_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Any | Comparison | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = Comparison.from_dict(response.json())

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
) -> Response[Any | Comparison | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    comparison_id: int,
    *,
    client: AuthenticatedClient | Client,
) -> Response[Any | Comparison | HTTPValidationError]:
    """One comparison: its runs, and per report and data set each solver pair's score

    Args:
        comparison_id (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | Comparison | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        comparison_id=comparison_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    comparison_id: int,
    *,
    client: AuthenticatedClient | Client,
) -> Any | Comparison | HTTPValidationError | None:
    """One comparison: its runs, and per report and data set each solver pair's score

    Args:
        comparison_id (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | Comparison | HTTPValidationError
    """

    return sync_detailed(
        comparison_id=comparison_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    comparison_id: int,
    *,
    client: AuthenticatedClient | Client,
) -> Response[Any | Comparison | HTTPValidationError]:
    """One comparison: its runs, and per report and data set each solver pair's score

    Args:
        comparison_id (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | Comparison | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        comparison_id=comparison_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    comparison_id: int,
    *,
    client: AuthenticatedClient | Client,
) -> Any | Comparison | HTTPValidationError | None:
    """One comparison: its runs, and per report and data set each solver pair's score

    Args:
        comparison_id (int):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | Comparison | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            comparison_id=comparison_id,
            client=client,
        )
    ).parsed
