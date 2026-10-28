from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.body_run_sedml import BodyRunSedml
from ...models.http_validation_error import HTTPValidationError
from ...models.sedml_run_error import SedmlRunError
from ...models.sedml_run_result import SedmlRunResult
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    body: BodyRunSedml,
    solvers: list[str] | None | Unset = UNSET,
    task: list[str] | None | Unset = UNSET,
    tags: list[str] | None | Unset = UNSET,
    description: None | str | Unset = UNSET,
    rel_tol: float | Unset = 0.0001,
    abs_tol_min: float | Unset = 0.001,
    abs_tol_scale: float | Unset = 1e-05,
    environment_version: list[str] | None | Unset = UNSET,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

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

    params["rel_tol"] = rel_tol

    params["abs_tol_min"] = abs_tol_min

    params["abs_tol_scale"] = abs_tol_scale

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
        "url": "/sedml/run",
        "params": params,
    }

    _kwargs["files"] = body.to_multipart()

    headers["Content-Type"] = "multipart/form-data; boundary=+++"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | SedmlRunError | SedmlRunResult | None:
    if response.status_code == 200:
        response_200 = SedmlRunResult.from_dict(response.json())

        return response_200

    if response.status_code == 400:
        response_400 = SedmlRunError.from_dict(response.json())

        return response_400

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[HTTPValidationError | SedmlRunError | SedmlRunResult]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: BodyRunSedml,
    solvers: list[str] | None | Unset = UNSET,
    task: list[str] | None | Unset = UNSET,
    tags: list[str] | None | Unset = UNSET,
    description: None | str | Unset = UNSET,
    rel_tol: float | Unset = 0.0001,
    abs_tol_min: float | Unset = 0.001,
    abs_tol_scale: float | Unset = 1e-05,
    environment_version: list[str] | None | Unset = UNSET,
) -> Response[HTTPValidationError | SedmlRunError | SedmlRunResult]:
    """Run each task of a SED-ML archive on several solvers, one run per solver, grouped by a comparison

    Args:
        solvers (list[str] | None | Unset): Solvers to run (registry/solvers.yaml); all when
            omitted
        task (list[str] | None | Unset): Only these SED-ML task ids; all when omitted
        tags (list[str] | None | Unset): Tags for every run
        description (None | str | Unset):
        rel_tol (float | Unset):  Default: 0.0001.
        abs_tol_min (float | Unset):  Default: 0.001.
        abs_tol_scale (float | Unset):  Default: 1e-05.
        environment_version (list[str] | None | Unset): Environment versions to run in:
            environment@number (registry_env@2) or environment@default, repeatable; an environment not
            named runs at its default
        body (BodyRunSedml):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | SedmlRunError | SedmlRunResult]
    """

    kwargs = _get_kwargs(
        body=body,
        solvers=solvers,
        task=task,
        tags=tags,
        description=description,
        rel_tol=rel_tol,
        abs_tol_min=abs_tol_min,
        abs_tol_scale=abs_tol_scale,
        environment_version=environment_version,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient | Client,
    body: BodyRunSedml,
    solvers: list[str] | None | Unset = UNSET,
    task: list[str] | None | Unset = UNSET,
    tags: list[str] | None | Unset = UNSET,
    description: None | str | Unset = UNSET,
    rel_tol: float | Unset = 0.0001,
    abs_tol_min: float | Unset = 0.001,
    abs_tol_scale: float | Unset = 1e-05,
    environment_version: list[str] | None | Unset = UNSET,
) -> HTTPValidationError | SedmlRunError | SedmlRunResult | None:
    """Run each task of a SED-ML archive on several solvers, one run per solver, grouped by a comparison

    Args:
        solvers (list[str] | None | Unset): Solvers to run (registry/solvers.yaml); all when
            omitted
        task (list[str] | None | Unset): Only these SED-ML task ids; all when omitted
        tags (list[str] | None | Unset): Tags for every run
        description (None | str | Unset):
        rel_tol (float | Unset):  Default: 0.0001.
        abs_tol_min (float | Unset):  Default: 0.001.
        abs_tol_scale (float | Unset):  Default: 1e-05.
        environment_version (list[str] | None | Unset): Environment versions to run in:
            environment@number (registry_env@2) or environment@default, repeatable; an environment not
            named runs at its default
        body (BodyRunSedml):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | SedmlRunError | SedmlRunResult
    """

    return sync_detailed(
        client=client,
        body=body,
        solvers=solvers,
        task=task,
        tags=tags,
        description=description,
        rel_tol=rel_tol,
        abs_tol_min=abs_tol_min,
        abs_tol_scale=abs_tol_scale,
        environment_version=environment_version,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: BodyRunSedml,
    solvers: list[str] | None | Unset = UNSET,
    task: list[str] | None | Unset = UNSET,
    tags: list[str] | None | Unset = UNSET,
    description: None | str | Unset = UNSET,
    rel_tol: float | Unset = 0.0001,
    abs_tol_min: float | Unset = 0.001,
    abs_tol_scale: float | Unset = 1e-05,
    environment_version: list[str] | None | Unset = UNSET,
) -> Response[HTTPValidationError | SedmlRunError | SedmlRunResult]:
    """Run each task of a SED-ML archive on several solvers, one run per solver, grouped by a comparison

    Args:
        solvers (list[str] | None | Unset): Solvers to run (registry/solvers.yaml); all when
            omitted
        task (list[str] | None | Unset): Only these SED-ML task ids; all when omitted
        tags (list[str] | None | Unset): Tags for every run
        description (None | str | Unset):
        rel_tol (float | Unset):  Default: 0.0001.
        abs_tol_min (float | Unset):  Default: 0.001.
        abs_tol_scale (float | Unset):  Default: 1e-05.
        environment_version (list[str] | None | Unset): Environment versions to run in:
            environment@number (registry_env@2) or environment@default, repeatable; an environment not
            named runs at its default
        body (BodyRunSedml):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | SedmlRunError | SedmlRunResult]
    """

    kwargs = _get_kwargs(
        body=body,
        solvers=solvers,
        task=task,
        tags=tags,
        description=description,
        rel_tol=rel_tol,
        abs_tol_min=abs_tol_min,
        abs_tol_scale=abs_tol_scale,
        environment_version=environment_version,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    body: BodyRunSedml,
    solvers: list[str] | None | Unset = UNSET,
    task: list[str] | None | Unset = UNSET,
    tags: list[str] | None | Unset = UNSET,
    description: None | str | Unset = UNSET,
    rel_tol: float | Unset = 0.0001,
    abs_tol_min: float | Unset = 0.001,
    abs_tol_scale: float | Unset = 1e-05,
    environment_version: list[str] | None | Unset = UNSET,
) -> HTTPValidationError | SedmlRunError | SedmlRunResult | None:
    """Run each task of a SED-ML archive on several solvers, one run per solver, grouped by a comparison

    Args:
        solvers (list[str] | None | Unset): Solvers to run (registry/solvers.yaml); all when
            omitted
        task (list[str] | None | Unset): Only these SED-ML task ids; all when omitted
        tags (list[str] | None | Unset): Tags for every run
        description (None | str | Unset):
        rel_tol (float | Unset):  Default: 0.0001.
        abs_tol_min (float | Unset):  Default: 0.001.
        abs_tol_scale (float | Unset):  Default: 1e-05.
        environment_version (list[str] | None | Unset): Environment versions to run in:
            environment@number (registry_env@2) or environment@default, repeatable; an environment not
            named runs at its default
        body (BodyRunSedml):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | SedmlRunError | SedmlRunResult
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
            solvers=solvers,
            task=task,
            tags=tags,
            description=description,
            rel_tol=rel_tol,
            abs_tol_min=abs_tol_min,
            abs_tol_scale=abs_tol_scale,
            environment_version=environment_version,
        )
    ).parsed
