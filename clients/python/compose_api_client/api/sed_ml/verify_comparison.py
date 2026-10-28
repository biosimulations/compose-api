from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.error_detail import ErrorDetail
from ...models.http_validation_error import HTTPValidationError
from ...models.verification import Verification
from ...models.verify_request import VerifyRequest
from ...types import UNSET, Response, Unset


def _get_kwargs(
    comparison_id: int,
    *,
    body: None | Unset | VerifyRequest = UNSET,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/comparisons/{comparison_id}/verify".format(
            comparison_id=quote(str(comparison_id), safe=""),
        ),
    }

    if isinstance(body, VerifyRequest):
        _kwargs["json"] = body.to_dict()
    else:
        _kwargs["json"] = body

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ErrorDetail | HTTPValidationError | Verification | None:
    if response.status_code == 200:
        response_200 = Verification.from_dict(response.json())

        return response_200

    if response.status_code == 201:
        response_201 = Verification.from_dict(response.json())

        return response_201

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
) -> Response[ErrorDetail | HTTPValidationError | Verification]:
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
    body: None | Unset | VerifyRequest = UNSET,
) -> Response[ErrorDetail | HTTPValidationError | Verification]:
    """Check a comparison against BioSimulators' simulators through biosim's /verify (queued; 201 when new)

    Args:
        comparison_id (int):
        body (None | Unset | VerifyRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ErrorDetail | HTTPValidationError | Verification]
    """

    kwargs = _get_kwargs(
        comparison_id=comparison_id,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    comparison_id: int,
    *,
    client: AuthenticatedClient | Client,
    body: None | Unset | VerifyRequest = UNSET,
) -> ErrorDetail | HTTPValidationError | Verification | None:
    """Check a comparison against BioSimulators' simulators through biosim's /verify (queued; 201 when new)

    Args:
        comparison_id (int):
        body (None | Unset | VerifyRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ErrorDetail | HTTPValidationError | Verification
    """

    return sync_detailed(
        comparison_id=comparison_id,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    comparison_id: int,
    *,
    client: AuthenticatedClient | Client,
    body: None | Unset | VerifyRequest = UNSET,
) -> Response[ErrorDetail | HTTPValidationError | Verification]:
    """Check a comparison against BioSimulators' simulators through biosim's /verify (queued; 201 when new)

    Args:
        comparison_id (int):
        body (None | Unset | VerifyRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ErrorDetail | HTTPValidationError | Verification]
    """

    kwargs = _get_kwargs(
        comparison_id=comparison_id,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    comparison_id: int,
    *,
    client: AuthenticatedClient | Client,
    body: None | Unset | VerifyRequest = UNSET,
) -> ErrorDetail | HTTPValidationError | Verification | None:
    """Check a comparison against BioSimulators' simulators through biosim's /verify (queued; 201 when new)

    Args:
        comparison_id (int):
        body (None | Unset | VerifyRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ErrorDetail | HTTPValidationError | Verification
    """

    return (
        await asyncio_detailed(
            comparison_id=comparison_id,
            client=client,
            body=body,
        )
    ).parsed
