from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.suite_run_info import SuiteRunInfo
from ...types import UNSET, Response


def _get_kwargs(
    name: str,
    *,
    environment_version: list[str],
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_environment_version = environment_version

    params["environment_version"] = json_environment_version

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/suites/{name}/run".format(
            name=quote(str(name), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Any | HTTPValidationError | SuiteRunInfo | None:
    if response.status_code == 200:
        response_200 = SuiteRunInfo.from_dict(response.json())

        return response_200

    if response.status_code == 400:
        response_400 = cast(Any, None)
        return response_400

    if response.status_code == 404:
        response_404 = cast(Any, None)
        return response_404

    if response.status_code == 409:
        response_409 = cast(Any, None)
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
) -> Response[Any | HTTPValidationError | SuiteRunInfo]:
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
    environment_version: list[str],
) -> Response[Any | HTTPValidationError | SuiteRunInfo]:
    """Run every source of the suite on its solvers, in the environment versions named (in the background)

     Every environment the suite's solvers use must be named (docs/plan-environment-versions.md, step 5):
    a suite
    run records exactly what it ran in, and is independent of the service release that started it.

    Args:
        name (str):
        environment_version (list[str]): The environment versions the suite runs in, required:
            environment@number (registry_env@2), environment@default, or default (every environment at
            its default). Stored with the run as numbers

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError | SuiteRunInfo]
    """

    kwargs = _get_kwargs(
        name=name,
        environment_version=environment_version,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    name: str,
    *,
    client: AuthenticatedClient | Client,
    environment_version: list[str],
) -> Any | HTTPValidationError | SuiteRunInfo | None:
    """Run every source of the suite on its solvers, in the environment versions named (in the background)

     Every environment the suite's solvers use must be named (docs/plan-environment-versions.md, step 5):
    a suite
    run records exactly what it ran in, and is independent of the service release that started it.

    Args:
        name (str):
        environment_version (list[str]): The environment versions the suite runs in, required:
            environment@number (registry_env@2), environment@default, or default (every environment at
            its default). Stored with the run as numbers

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError | SuiteRunInfo
    """

    return sync_detailed(
        name=name,
        client=client,
        environment_version=environment_version,
    ).parsed


async def asyncio_detailed(
    name: str,
    *,
    client: AuthenticatedClient | Client,
    environment_version: list[str],
) -> Response[Any | HTTPValidationError | SuiteRunInfo]:
    """Run every source of the suite on its solvers, in the environment versions named (in the background)

     Every environment the suite's solvers use must be named (docs/plan-environment-versions.md, step 5):
    a suite
    run records exactly what it ran in, and is independent of the service release that started it.

    Args:
        name (str):
        environment_version (list[str]): The environment versions the suite runs in, required:
            environment@number (registry_env@2), environment@default, or default (every environment at
            its default). Stored with the run as numbers

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError | SuiteRunInfo]
    """

    kwargs = _get_kwargs(
        name=name,
        environment_version=environment_version,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    name: str,
    *,
    client: AuthenticatedClient | Client,
    environment_version: list[str],
) -> Any | HTTPValidationError | SuiteRunInfo | None:
    """Run every source of the suite on its solvers, in the environment versions named (in the background)

     Every environment the suite's solvers use must be named (docs/plan-environment-versions.md, step 5):
    a suite
    run records exactly what it ran in, and is independent of the service release that started it.

    Args:
        name (str):
        environment_version (list[str]): The environment versions the suite runs in, required:
            environment@number (registry_env@2), environment@default, or default (every environment at
            its default). Stored with the run as numbers

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError | SuiteRunInfo
    """

    return (
        await asyncio_detailed(
            name=name,
            client=client,
            environment_version=environment_version,
        )
    ).parsed
