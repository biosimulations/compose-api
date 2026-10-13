from http import HTTPStatus
from typing import Any, cast

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.biomodel_hit import BiomodelHit
from ...models.http_validation_error import HTTPValidationError
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    q: str,
    limit: int | Unset = 20,
    curated: bool | Unset = True,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    params["q"] = q

    params["limit"] = limit

    params["curated"] = curated

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/sources/biomodels/search",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Any | HTTPValidationError | list[BiomodelHit] | None:
    if response.status_code == 200:
        response_200 = []
        _response_200 = response.json()
        for response_200_item_data in _response_200:
            response_200_item = BiomodelHit.from_dict(response_200_item_data)

            response_200.append(response_200_item)

        return response_200

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if response.status_code == 502:
        response_502 = cast(Any, None)
        return response_502

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[Any | HTTPValidationError | list[BiomodelHit]]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    q: str,
    limit: int | Unset = 20,
    curated: bool | Unset = True,
) -> Response[Any | HTTPValidationError | list[BiomodelHit]]:
    """Search EBI BioModels (manually curated models unless curated=false)

    Args:
        q (str):
        limit (int | Unset):  Default: 20.
        curated (bool | Unset):  Default: True.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError | list[BiomodelHit]]
    """

    kwargs = _get_kwargs(
        q=q,
        limit=limit,
        curated=curated,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient | Client,
    q: str,
    limit: int | Unset = 20,
    curated: bool | Unset = True,
) -> Any | HTTPValidationError | list[BiomodelHit] | None:
    """Search EBI BioModels (manually curated models unless curated=false)

    Args:
        q (str):
        limit (int | Unset):  Default: 20.
        curated (bool | Unset):  Default: True.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError | list[BiomodelHit]
    """

    return sync_detailed(
        client=client,
        q=q,
        limit=limit,
        curated=curated,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    q: str,
    limit: int | Unset = 20,
    curated: bool | Unset = True,
) -> Response[Any | HTTPValidationError | list[BiomodelHit]]:
    """Search EBI BioModels (manually curated models unless curated=false)

    Args:
        q (str):
        limit (int | Unset):  Default: 20.
        curated (bool | Unset):  Default: True.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError | list[BiomodelHit]]
    """

    kwargs = _get_kwargs(
        q=q,
        limit=limit,
        curated=curated,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    q: str,
    limit: int | Unset = 20,
    curated: bool | Unset = True,
) -> Any | HTTPValidationError | list[BiomodelHit] | None:
    """Search EBI BioModels (manually curated models unless curated=false)

    Args:
        q (str):
        limit (int | Unset):  Default: 20.
        curated (bool | Unset):  Default: True.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError | list[BiomodelHit]
    """

    return (
        await asyncio_detailed(
            client=client,
            q=q,
            limit=limit,
            curated=curated,
        )
    ).parsed
