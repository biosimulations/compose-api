from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote
from uuid import UUID

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...types import Response


def _get_kwargs(
    dataset_id: UUID,
    subpath: str,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/datasets/{dataset_id}/files/{subpath}".format(
            dataset_id=quote(str(dataset_id), safe=""),
            subpath=quote(str(subpath), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Any | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = cast(Any, response.content)
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
) -> Response[Any | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    dataset_id: UUID,
    subpath: str,
    *,
    client: AuthenticatedClient | Client,
) -> Response[Any | HTTPValidationError]:
    """Read one file inside a directory dataset, e.g. a zarr store's metadata or chunk (supports HTTP
    Range)

     A directory dataset (a ``*.fenics`` results bundle, a ``*.zarr`` store) is read file by file, so a
    browser
    can fetch one chunk at a time with no server-side reduction (docs/plan-viewers.md F1). ``no-cache``:
    a live
    run rewrites the bundle's manifest after every row, so clients revalidate (the ETag makes that
    cheap).

    Args:
        dataset_id (UUID):
        subpath (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        subpath=subpath,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    dataset_id: UUID,
    subpath: str,
    *,
    client: AuthenticatedClient | Client,
) -> Any | HTTPValidationError | None:
    """Read one file inside a directory dataset, e.g. a zarr store's metadata or chunk (supports HTTP
    Range)

     A directory dataset (a ``*.fenics`` results bundle, a ``*.zarr`` store) is read file by file, so a
    browser
    can fetch one chunk at a time with no server-side reduction (docs/plan-viewers.md F1). ``no-cache``:
    a live
    run rewrites the bundle's manifest after every row, so clients revalidate (the ETag makes that
    cheap).

    Args:
        dataset_id (UUID):
        subpath (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError
    """

    return sync_detailed(
        dataset_id=dataset_id,
        subpath=subpath,
        client=client,
    ).parsed


async def asyncio_detailed(
    dataset_id: UUID,
    subpath: str,
    *,
    client: AuthenticatedClient | Client,
) -> Response[Any | HTTPValidationError]:
    """Read one file inside a directory dataset, e.g. a zarr store's metadata or chunk (supports HTTP
    Range)

     A directory dataset (a ``*.fenics`` results bundle, a ``*.zarr`` store) is read file by file, so a
    browser
    can fetch one chunk at a time with no server-side reduction (docs/plan-viewers.md F1). ``no-cache``:
    a live
    run rewrites the bundle's manifest after every row, so clients revalidate (the ETag makes that
    cheap).

    Args:
        dataset_id (UUID):
        subpath (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        subpath=subpath,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    dataset_id: UUID,
    subpath: str,
    *,
    client: AuthenticatedClient | Client,
) -> Any | HTTPValidationError | None:
    """Read one file inside a directory dataset, e.g. a zarr store's metadata or chunk (supports HTTP
    Range)

     A directory dataset (a ``*.fenics`` results bundle, a ``*.zarr`` store) is read file by file, so a
    browser
    can fetch one chunk at a time with no server-side reduction (docs/plan-viewers.md F1). ``no-cache``:
    a live
    run rewrites the bundle's manifest after every row, so clients revalidate (the ETag makes that
    cheap).

    Args:
        dataset_id (UUID):
        subpath (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            dataset_id=dataset_id,
            subpath=subpath,
            client=client,
        )
    ).parsed
