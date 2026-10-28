from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.error_detail import ErrorDetail
from ...models.http_validation_error import HTTPValidationError
from ...models.suite_verify_result import SuiteVerifyResult
from ...models.verify_suite_run_which import VerifySuiteRunWhich
from ...types import UNSET, Response, Unset


def _get_kwargs(
    name: str,
    number: int,
    *,
    which: VerifySuiteRunWhich | Unset = VerifySuiteRunWhich.FAILING,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_which: str | Unset = UNSET
    if not isinstance(which, Unset):
        json_which = which.value

    params["which"] = json_which

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/suites/{name}/runs/{number}/verify".format(
            name=quote(str(name), safe=""),
            number=quote(str(number), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ErrorDetail | HTTPValidationError | SuiteVerifyResult | None:
    if response.status_code == 200:
        response_200 = SuiteVerifyResult.from_dict(response.json())

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
) -> Response[ErrorDetail | HTTPValidationError | SuiteVerifyResult]:
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
    which: VerifySuiteRunWhich | Unset = VerifySuiteRunWhich.FAILING,
) -> Response[ErrorDetail | HTTPValidationError | SuiteVerifyResult]:
    """Queue a verification against biosim's /verify for a suite run's finished comparisons

    Args:
        name (str):
        number (int):
        which (VerifySuiteRunWhich | Unset): failing: those that differ, are incomplete, or no
            agreeing reference settles; all: every one Default: VerifySuiteRunWhich.FAILING.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ErrorDetail | HTTPValidationError | SuiteVerifyResult]
    """

    kwargs = _get_kwargs(
        name=name,
        number=number,
        which=which,
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
    which: VerifySuiteRunWhich | Unset = VerifySuiteRunWhich.FAILING,
) -> ErrorDetail | HTTPValidationError | SuiteVerifyResult | None:
    """Queue a verification against biosim's /verify for a suite run's finished comparisons

    Args:
        name (str):
        number (int):
        which (VerifySuiteRunWhich | Unset): failing: those that differ, are incomplete, or no
            agreeing reference settles; all: every one Default: VerifySuiteRunWhich.FAILING.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ErrorDetail | HTTPValidationError | SuiteVerifyResult
    """

    return sync_detailed(
        name=name,
        number=number,
        client=client,
        which=which,
    ).parsed


async def asyncio_detailed(
    name: str,
    number: int,
    *,
    client: AuthenticatedClient | Client,
    which: VerifySuiteRunWhich | Unset = VerifySuiteRunWhich.FAILING,
) -> Response[ErrorDetail | HTTPValidationError | SuiteVerifyResult]:
    """Queue a verification against biosim's /verify for a suite run's finished comparisons

    Args:
        name (str):
        number (int):
        which (VerifySuiteRunWhich | Unset): failing: those that differ, are incomplete, or no
            agreeing reference settles; all: every one Default: VerifySuiteRunWhich.FAILING.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ErrorDetail | HTTPValidationError | SuiteVerifyResult]
    """

    kwargs = _get_kwargs(
        name=name,
        number=number,
        which=which,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    name: str,
    number: int,
    *,
    client: AuthenticatedClient | Client,
    which: VerifySuiteRunWhich | Unset = VerifySuiteRunWhich.FAILING,
) -> ErrorDetail | HTTPValidationError | SuiteVerifyResult | None:
    """Queue a verification against biosim's /verify for a suite run's finished comparisons

    Args:
        name (str):
        number (int):
        which (VerifySuiteRunWhich | Unset): failing: those that differ, are incomplete, or no
            agreeing reference settles; all: every one Default: VerifySuiteRunWhich.FAILING.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ErrorDetail | HTTPValidationError | SuiteVerifyResult
    """

    return (
        await asyncio_detailed(
            name=name,
            number=number,
            client=client,
            which=which,
        )
    ).parsed
