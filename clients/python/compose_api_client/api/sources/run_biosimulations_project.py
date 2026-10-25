from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...models.sedml_run_result import SedmlRunResult
from ...types import UNSET, Response, Unset


def _get_kwargs(
    project_id: str,
    *,
    solvers: list[str] | None | Unset = UNSET,
    task: list[str] | None | Unset = UNSET,
    tags: list[str] | None | Unset = UNSET,
    description: None | str | Unset = UNSET,
    environment_version: list[str] | None | Unset = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_solvers: list[str] | None | Unset
    if isinstance(solvers, Unset):
        json_solvers = UNSET
    elif isinstance(solvers, list):
        json_solvers = solvers

    else:
        json_solvers = solvers
    params["solvers"] = json_solvers

    json_task: list[str] | None | Unset
    if isinstance(task, Unset):
        json_task = UNSET
    elif isinstance(task, list):
        json_task = task

    else:
        json_task = task
    params["task"] = json_task

    json_tags: list[str] | None | Unset
    if isinstance(tags, Unset):
        json_tags = UNSET
    elif isinstance(tags, list):
        json_tags = tags

    else:
        json_tags = tags
    params["tags"] = json_tags

    json_description: None | str | Unset
    if isinstance(description, Unset):
        json_description = UNSET
    else:
        json_description = description
    params["description"] = json_description

    json_environment_version: list[str] | None | Unset
    if isinstance(environment_version, Unset):
        json_environment_version = UNSET
    elif isinstance(environment_version, list):
        json_environment_version = environment_version

    else:
        json_environment_version = environment_version
    params["environment_version"] = json_environment_version

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/sources/biosimulations/{project_id}/run".format(
            project_id=quote(str(project_id), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Any | HTTPValidationError | SedmlRunResult | None:
    if response.status_code == 200:
        response_200 = SedmlRunResult.from_dict(response.json())

        return response_200

    if response.status_code == 404:
        response_404 = cast(Any, None)
        return response_404

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
) -> Response[Any | HTTPValidationError | SedmlRunResult]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    project_id: str,
    *,
    client: AuthenticatedClient | Client,
    solvers: list[str] | None | Unset = UNSET,
    task: list[str] | None | Unset = UNSET,
    tags: list[str] | None | Unset = UNSET,
    description: None | str | Unset = UNSET,
    environment_version: list[str] | None | Unset = UNSET,
) -> Response[Any | HTTPValidationError | SedmlRunResult]:
    """Run a project's SED-ML on several solvers, its original results as the reference

    Args:
        project_id (str):
        solvers (list[str] | None | Unset): Solvers to run (registry/solvers.yaml); all when
            omitted
        task (list[str] | None | Unset): Only these SED-ML task ids; all when omitted
        tags (list[str] | None | Unset): Tags for every run
        description (None | str | Unset):
        environment_version (list[str] | None | Unset): Environment versions to run in:
            environment@number (registry_env@2) or environment@default, repeatable; an environment not
            named runs at its default

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError | SedmlRunResult]
    """

    kwargs = _get_kwargs(
        project_id=project_id,
        solvers=solvers,
        task=task,
        tags=tags,
        description=description,
        environment_version=environment_version,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    project_id: str,
    *,
    client: AuthenticatedClient | Client,
    solvers: list[str] | None | Unset = UNSET,
    task: list[str] | None | Unset = UNSET,
    tags: list[str] | None | Unset = UNSET,
    description: None | str | Unset = UNSET,
    environment_version: list[str] | None | Unset = UNSET,
) -> Any | HTTPValidationError | SedmlRunResult | None:
    """Run a project's SED-ML on several solvers, its original results as the reference

    Args:
        project_id (str):
        solvers (list[str] | None | Unset): Solvers to run (registry/solvers.yaml); all when
            omitted
        task (list[str] | None | Unset): Only these SED-ML task ids; all when omitted
        tags (list[str] | None | Unset): Tags for every run
        description (None | str | Unset):
        environment_version (list[str] | None | Unset): Environment versions to run in:
            environment@number (registry_env@2) or environment@default, repeatable; an environment not
            named runs at its default

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError | SedmlRunResult
    """

    return sync_detailed(
        project_id=project_id,
        client=client,
        solvers=solvers,
        task=task,
        tags=tags,
        description=description,
        environment_version=environment_version,
    ).parsed


async def asyncio_detailed(
    project_id: str,
    *,
    client: AuthenticatedClient | Client,
    solvers: list[str] | None | Unset = UNSET,
    task: list[str] | None | Unset = UNSET,
    tags: list[str] | None | Unset = UNSET,
    description: None | str | Unset = UNSET,
    environment_version: list[str] | None | Unset = UNSET,
) -> Response[Any | HTTPValidationError | SedmlRunResult]:
    """Run a project's SED-ML on several solvers, its original results as the reference

    Args:
        project_id (str):
        solvers (list[str] | None | Unset): Solvers to run (registry/solvers.yaml); all when
            omitted
        task (list[str] | None | Unset): Only these SED-ML task ids; all when omitted
        tags (list[str] | None | Unset): Tags for every run
        description (None | str | Unset):
        environment_version (list[str] | None | Unset): Environment versions to run in:
            environment@number (registry_env@2) or environment@default, repeatable; an environment not
            named runs at its default

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError | SedmlRunResult]
    """

    kwargs = _get_kwargs(
        project_id=project_id,
        solvers=solvers,
        task=task,
        tags=tags,
        description=description,
        environment_version=environment_version,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    project_id: str,
    *,
    client: AuthenticatedClient | Client,
    solvers: list[str] | None | Unset = UNSET,
    task: list[str] | None | Unset = UNSET,
    tags: list[str] | None | Unset = UNSET,
    description: None | str | Unset = UNSET,
    environment_version: list[str] | None | Unset = UNSET,
) -> Any | HTTPValidationError | SedmlRunResult | None:
    """Run a project's SED-ML on several solvers, its original results as the reference

    Args:
        project_id (str):
        solvers (list[str] | None | Unset): Solvers to run (registry/solvers.yaml); all when
            omitted
        task (list[str] | None | Unset): Only these SED-ML task ids; all when omitted
        tags (list[str] | None | Unset): Tags for every run
        description (None | str | Unset):
        environment_version (list[str] | None | Unset): Environment versions to run in:
            environment@number (registry_env@2) or environment@default, repeatable; an environment not
            named runs at its default

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError | SedmlRunResult
    """

    return (
        await asyncio_detailed(
            project_id=project_id,
            client=client,
            solvers=solvers,
            task=task,
            tags=tags,
            description=description,
            environment_version=environment_version,
        )
    ).parsed
