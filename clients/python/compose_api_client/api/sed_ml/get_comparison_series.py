from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.comparison_series import ComparisonSeries
from ...models.error_detail import ErrorDetail
from ...models.http_validation_error import HTTPValidationError
from ...types import UNSET, Response


def _get_kwargs(
    comparison_id: int,
    *,
    report: str,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    params["report"] = report

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/comparisons/{comparison_id}/series".format(
            comparison_id=quote(str(comparison_id), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ComparisonSeries | ErrorDetail | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = ComparisonSeries.from_dict(response.json())

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
) -> Response[ComparisonSeries | ErrorDetail | HTTPValidationError]:
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
    report: str,
) -> Response[ComparisonSeries | ErrorDetail | HTTPValidationError]:
    """One report's columns from each run and each reference, for overlays

    Args:
        comparison_id (int):
        report (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ComparisonSeries | ErrorDetail | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        comparison_id=comparison_id,
        report=report,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    comparison_id: int,
    *,
    client: AuthenticatedClient | Client,
    report: str,
) -> ComparisonSeries | ErrorDetail | HTTPValidationError | None:
    """One report's columns from each run and each reference, for overlays

    Args:
        comparison_id (int):
        report (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ComparisonSeries | ErrorDetail | HTTPValidationError
    """

    return sync_detailed(
        comparison_id=comparison_id,
        client=client,
        report=report,
    ).parsed


async def asyncio_detailed(
    comparison_id: int,
    *,
    client: AuthenticatedClient | Client,
    report: str,
) -> Response[ComparisonSeries | ErrorDetail | HTTPValidationError]:
    """One report's columns from each run and each reference, for overlays

    Args:
        comparison_id (int):
        report (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ComparisonSeries | ErrorDetail | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        comparison_id=comparison_id,
        report=report,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    comparison_id: int,
    *,
    client: AuthenticatedClient | Client,
    report: str,
) -> ComparisonSeries | ErrorDetail | HTTPValidationError | None:
    """One report's columns from each run and each reference, for overlays

    Args:
        comparison_id (int):
        report (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ComparisonSeries | ErrorDetail | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            comparison_id=comparison_id,
            client=client,
            report=report,
        )
    ).parsed
