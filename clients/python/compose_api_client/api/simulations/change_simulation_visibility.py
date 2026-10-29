from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.error_detail import ErrorDetail
from ...models.http_validation_error import HTTPValidationError
from ...models.visibility_change import VisibilityChange
from ...models.visibility_changed import VisibilityChanged
from ...types import Response


def _get_kwargs(
    simulation_id: int,
    *,
    body: VisibilityChange,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "patch",
        "url": "/simulations/{simulation_id}".format(
            simulation_id=quote(str(simulation_id), safe=""),
        ),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ErrorDetail | HTTPValidationError | VisibilityChanged | None:
    if response.status_code == 200:
        response_200 = VisibilityChanged.from_dict(response.json())

        return response_200

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
) -> Response[ErrorDetail | HTTPValidationError | VisibilityChanged]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    simulation_id: int,
    *,
    client: AuthenticatedClient | Client,
    body: VisibilityChange,
) -> Response[ErrorDetail | HTTPValidationError | VisibilityChanged]:
    """Make a run public or private; the other runs of every comparison it is in change with it

     By its owner or a configured admin (docs/plan-favorites-and-studies.md, step 1b). A comparison is
    readable only
    when all its runs are, so a SED-ML run's runs change together; a run with no owner stays public.

    Args:
        simulation_id (int):
        body (VisibilityChange): ``PATCH /simulations/{id}``'s body: who may read the run.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ErrorDetail | HTTPValidationError | VisibilityChanged]
    """

    kwargs = _get_kwargs(
        simulation_id=simulation_id,
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    simulation_id: int,
    *,
    client: AuthenticatedClient | Client,
    body: VisibilityChange,
) -> ErrorDetail | HTTPValidationError | VisibilityChanged | None:
    """Make a run public or private; the other runs of every comparison it is in change with it

     By its owner or a configured admin (docs/plan-favorites-and-studies.md, step 1b). A comparison is
    readable only
    when all its runs are, so a SED-ML run's runs change together; a run with no owner stays public.

    Args:
        simulation_id (int):
        body (VisibilityChange): ``PATCH /simulations/{id}``'s body: who may read the run.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ErrorDetail | HTTPValidationError | VisibilityChanged
    """

    return sync_detailed(
        simulation_id=simulation_id,
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    simulation_id: int,
    *,
    client: AuthenticatedClient | Client,
    body: VisibilityChange,
) -> Response[ErrorDetail | HTTPValidationError | VisibilityChanged]:
    """Make a run public or private; the other runs of every comparison it is in change with it

     By its owner or a configured admin (docs/plan-favorites-and-studies.md, step 1b). A comparison is
    readable only
    when all its runs are, so a SED-ML run's runs change together; a run with no owner stays public.

    Args:
        simulation_id (int):
        body (VisibilityChange): ``PATCH /simulations/{id}``'s body: who may read the run.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ErrorDetail | HTTPValidationError | VisibilityChanged]
    """

    kwargs = _get_kwargs(
        simulation_id=simulation_id,
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    simulation_id: int,
    *,
    client: AuthenticatedClient | Client,
    body: VisibilityChange,
) -> ErrorDetail | HTTPValidationError | VisibilityChanged | None:
    """Make a run public or private; the other runs of every comparison it is in change with it

     By its owner or a configured admin (docs/plan-favorites-and-studies.md, step 1b). A comparison is
    readable only
    when all its runs are, so a SED-ML run's runs change together; a run with no owner stays public.

    Args:
        simulation_id (int):
        body (VisibilityChange): ``PATCH /simulations/{id}``'s body: who may read the run.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ErrorDetail | HTTPValidationError | VisibilityChanged
    """

    return (
        await asyncio_detailed(
            simulation_id=simulation_id,
            client=client,
            body=body,
        )
    ).parsed
