import datetime
from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.list_simulations_status_type_0 import ListSimulationsStatusType0
from ...models.simulation_page import SimulationPage
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    status: ListSimulationsStatusType0 | None | Unset = UNSET,
    simulator: None | str | Unset = UNSET,
    since: datetime.datetime | None | Unset = UNSET,
    label: list[str] | None | Unset = UNSET,
    tag: list[str] | None | Unset = UNSET,
    limit: int | Unset = 50,
    offset: int | Unset = 0,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_status: None | str | Unset
    if isinstance(status, Unset):
        json_status = UNSET
    elif isinstance(status, ListSimulationsStatusType0):
        json_status = status.value
    else:
        json_status = status
    params["status"] = json_status

    json_simulator: None | str | Unset
    if isinstance(simulator, Unset):
        json_simulator = UNSET
    else:
        json_simulator = simulator
    params["simulator"] = json_simulator

    json_since: None | str | Unset
    if isinstance(since, Unset):
        json_since = UNSET
    elif isinstance(since, datetime.datetime):
        json_since = since.isoformat()
    else:
        json_since = since
    params["since"] = json_since

    json_label: list[str] | None | Unset
    if isinstance(label, Unset):
        json_label = UNSET
    elif isinstance(label, list):
        json_label = label

    else:
        json_label = label
    params["label"] = json_label

    json_tag: list[str] | None | Unset
    if isinstance(tag, Unset):
        json_tag = UNSET
    elif isinstance(tag, list):
        json_tag = tag

    else:
        json_tag = tag
    params["tag"] = json_tag

    params["limit"] = limit

    params["offset"] = offset

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/simulations",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | SimulationPage | None:
    if response.status_code == 200:
        response_200 = SimulationPage.from_dict(response.json())

        return response_200

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[HTTPValidationError | SimulationPage]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    status: ListSimulationsStatusType0 | None | Unset = UNSET,
    simulator: None | str | Unset = UNSET,
    since: datetime.datetime | None | Unset = UNSET,
    label: list[str] | None | Unset = UNSET,
    tag: list[str] | None | Unset = UNSET,
    limit: int | Unset = 50,
    offset: int | Unset = 0,
) -> Response[HTTPValidationError | SimulationPage]:
    """List simulations, newest first, each with its latest SLURM job

    Args:
        status (ListSimulationsStatusType0 | None | Unset): Only simulations in this state
        simulator (None | str | Unset): Only this prebuilt simulator (by name), or container
            definitions with this hash prefix
        since (datetime.datetime | None | Unset): Only simulations created at or after this time
        label (list[str] | None | Unset): Only simulations with this label, as key:value;
            repeatable, all must match. Keys: source, environment, environment_version, solver, model,
            project, sedml_task, comparison, collection, suite_run, compliance
        tag (list[str] | None | Unset): Only simulations with this tag; repeatable, all must match
        limit (int | Unset):  Default: 50.
        offset (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | SimulationPage]
    """

    kwargs = _get_kwargs(
        status=status,
        simulator=simulator,
        since=since,
        label=label,
        tag=tag,
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
    status: ListSimulationsStatusType0 | None | Unset = UNSET,
    simulator: None | str | Unset = UNSET,
    since: datetime.datetime | None | Unset = UNSET,
    label: list[str] | None | Unset = UNSET,
    tag: list[str] | None | Unset = UNSET,
    limit: int | Unset = 50,
    offset: int | Unset = 0,
) -> HTTPValidationError | SimulationPage | None:
    """List simulations, newest first, each with its latest SLURM job

    Args:
        status (ListSimulationsStatusType0 | None | Unset): Only simulations in this state
        simulator (None | str | Unset): Only this prebuilt simulator (by name), or container
            definitions with this hash prefix
        since (datetime.datetime | None | Unset): Only simulations created at or after this time
        label (list[str] | None | Unset): Only simulations with this label, as key:value;
            repeatable, all must match. Keys: source, environment, environment_version, solver, model,
            project, sedml_task, comparison, collection, suite_run, compliance
        tag (list[str] | None | Unset): Only simulations with this tag; repeatable, all must match
        limit (int | Unset):  Default: 50.
        offset (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | SimulationPage
    """

    return sync_detailed(
        client=client,
        status=status,
        simulator=simulator,
        since=since,
        label=label,
        tag=tag,
        limit=limit,
        offset=offset,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    status: ListSimulationsStatusType0 | None | Unset = UNSET,
    simulator: None | str | Unset = UNSET,
    since: datetime.datetime | None | Unset = UNSET,
    label: list[str] | None | Unset = UNSET,
    tag: list[str] | None | Unset = UNSET,
    limit: int | Unset = 50,
    offset: int | Unset = 0,
) -> Response[HTTPValidationError | SimulationPage]:
    """List simulations, newest first, each with its latest SLURM job

    Args:
        status (ListSimulationsStatusType0 | None | Unset): Only simulations in this state
        simulator (None | str | Unset): Only this prebuilt simulator (by name), or container
            definitions with this hash prefix
        since (datetime.datetime | None | Unset): Only simulations created at or after this time
        label (list[str] | None | Unset): Only simulations with this label, as key:value;
            repeatable, all must match. Keys: source, environment, environment_version, solver, model,
            project, sedml_task, comparison, collection, suite_run, compliance
        tag (list[str] | None | Unset): Only simulations with this tag; repeatable, all must match
        limit (int | Unset):  Default: 50.
        offset (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | SimulationPage]
    """

    kwargs = _get_kwargs(
        status=status,
        simulator=simulator,
        since=since,
        label=label,
        tag=tag,
        limit=limit,
        offset=offset,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    status: ListSimulationsStatusType0 | None | Unset = UNSET,
    simulator: None | str | Unset = UNSET,
    since: datetime.datetime | None | Unset = UNSET,
    label: list[str] | None | Unset = UNSET,
    tag: list[str] | None | Unset = UNSET,
    limit: int | Unset = 50,
    offset: int | Unset = 0,
) -> HTTPValidationError | SimulationPage | None:
    """List simulations, newest first, each with its latest SLURM job

    Args:
        status (ListSimulationsStatusType0 | None | Unset): Only simulations in this state
        simulator (None | str | Unset): Only this prebuilt simulator (by name), or container
            definitions with this hash prefix
        since (datetime.datetime | None | Unset): Only simulations created at or after this time
        label (list[str] | None | Unset): Only simulations with this label, as key:value;
            repeatable, all must match. Keys: source, environment, environment_version, solver, model,
            project, sedml_task, comparison, collection, suite_run, compliance
        tag (list[str] | None | Unset): Only simulations with this tag; repeatable, all must match
        limit (int | Unset):  Default: 50.
        offset (int | Unset):  Default: 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | SimulationPage
    """

    return (
        await asyncio_detailed(
            client=client,
            status=status,
            simulator=simulator,
            since=since,
            label=label,
            tag=tag,
            limit=limit,
            offset=offset,
        )
    ).parsed
