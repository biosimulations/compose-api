from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.biomodel_info import BiomodelInfo
from ...models.error_detail import ErrorDetail
from ...models.http_validation_error import HTTPValidationError
from ...types import Response


def _get_kwargs(
    model_id: str,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/sources/biomodels/{model_id}".format(
            model_id=quote(str(model_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> BiomodelInfo | ErrorDetail | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = BiomodelInfo.from_dict(response.json())

        return response_200

    if response.status_code == 404:
        response_404 = ErrorDetail.from_dict(response.json())

        return response_404

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if response.status_code == 502:
        response_502 = ErrorDetail.from_dict(response.json())

        return response_502

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[BiomodelInfo | ErrorDetail | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    model_id: str,
    *,
    client: AuthenticatedClient | Client,
) -> Response[BiomodelInfo | ErrorDetail | HTTPValidationError]:
    """One BioModels entry: name, curation status, latest revision

    Args:
        model_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[BiomodelInfo | ErrorDetail | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        model_id=model_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    model_id: str,
    *,
    client: AuthenticatedClient | Client,
) -> BiomodelInfo | ErrorDetail | HTTPValidationError | None:
    """One BioModels entry: name, curation status, latest revision

    Args:
        model_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        BiomodelInfo | ErrorDetail | HTTPValidationError
    """

    return sync_detailed(
        model_id=model_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    model_id: str,
    *,
    client: AuthenticatedClient | Client,
) -> Response[BiomodelInfo | ErrorDetail | HTTPValidationError]:
    """One BioModels entry: name, curation status, latest revision

    Args:
        model_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[BiomodelInfo | ErrorDetail | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        model_id=model_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    model_id: str,
    *,
    client: AuthenticatedClient | Client,
) -> BiomodelInfo | ErrorDetail | HTTPValidationError | None:
    """One BioModels entry: name, curation status, latest revision

    Args:
        model_id (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        BiomodelInfo | ErrorDetail | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            model_id=model_id,
            client=client,
        )
    ).parsed
