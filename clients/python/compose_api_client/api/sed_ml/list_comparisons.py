from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.comparison_page import ComparisonPage
from ...models.error_detail import ErrorDetail
from ...models.http_validation_error import HTTPValidationError
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    source: None | str | Unset = UNSET,
    favorite: bool | Unset = False,
    limit: int | Unset = 25,
    offset: int | Unset = 0,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_source: None | str | Unset
    if isinstance(source, Unset):
        json_source = UNSET
    else:
        json_source = source
    params["source"] = json_source

    params["favorite"] = favorite

    params["limit"] = limit

    params["offset"] = offset

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/comparisons",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ComparisonPage | ErrorDetail | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = ComparisonPage.from_dict(response.json())

        return response_200

    if response.status_code == 401:
        response_401 = ErrorDetail.from_dict(response.json())

        return response_401

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[ComparisonPage | ErrorDetail | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    source: None | str | Unset = UNSET,
    favorite: bool | Unset = False,
    limit: int | Unset = 25,
    offset: int | Unset = 0,
) -> Response[ComparisonPage | ErrorDetail | HTTPValidationError]:
    """List comparisons, newest first

    Args:
        source (None | str | Unset): Only this source, e.g. upload:x.omex or biomodels:BIOMD…
        favorite (bool | Unset): Only those the caller starred (`PUT /favorites/comparison/{id}`);
            needs a signed-in caller Default: False.
        limit (int | Unset):  Default: 25.
        offset (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ComparisonPage | ErrorDetail | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        source=source,
        favorite=favorite,
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
    source: None | str | Unset = UNSET,
    favorite: bool | Unset = False,
    limit: int | Unset = 25,
    offset: int | Unset = 0,
) -> ComparisonPage | ErrorDetail | HTTPValidationError | None:
    """List comparisons, newest first

    Args:
        source (None | str | Unset): Only this source, e.g. upload:x.omex or biomodels:BIOMD…
        favorite (bool | Unset): Only those the caller starred (`PUT /favorites/comparison/{id}`);
            needs a signed-in caller Default: False.
        limit (int | Unset):  Default: 25.
        offset (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ComparisonPage | ErrorDetail | HTTPValidationError
    """

    return sync_detailed(
        client=client,
        source=source,
        favorite=favorite,
        limit=limit,
        offset=offset,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    source: None | str | Unset = UNSET,
    favorite: bool | Unset = False,
    limit: int | Unset = 25,
    offset: int | Unset = 0,
) -> Response[ComparisonPage | ErrorDetail | HTTPValidationError]:
    """List comparisons, newest first

    Args:
        source (None | str | Unset): Only this source, e.g. upload:x.omex or biomodels:BIOMD…
        favorite (bool | Unset): Only those the caller starred (`PUT /favorites/comparison/{id}`);
            needs a signed-in caller Default: False.
        limit (int | Unset):  Default: 25.
        offset (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ComparisonPage | ErrorDetail | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        source=source,
        favorite=favorite,
        limit=limit,
        offset=offset,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    source: None | str | Unset = UNSET,
    favorite: bool | Unset = False,
    limit: int | Unset = 25,
    offset: int | Unset = 0,
) -> ComparisonPage | ErrorDetail | HTTPValidationError | None:
    """List comparisons, newest first

    Args:
        source (None | str | Unset): Only this source, e.g. upload:x.omex or biomodels:BIOMD…
        favorite (bool | Unset): Only those the caller starred (`PUT /favorites/comparison/{id}`);
            needs a signed-in caller Default: False.
        limit (int | Unset):  Default: 25.
        offset (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ComparisonPage | ErrorDetail | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            client=client,
            source=source,
            favorite=favorite,
            limit=limit,
            offset=offset,
        )
    ).parsed
