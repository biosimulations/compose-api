from http import HTTPStatus
from typing import Any

import httpx

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.body_preview_sedml import BodyPreviewSedml
from ...models.http_validation_error import HTTPValidationError
from ...models.sedml_preview import SedmlPreview
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    body: BodyPreviewSedml,
    solvers: list[str] | None | Unset = UNSET,
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

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/sedml/preview",
        "params": params,
    }

    _kwargs["files"] = body.to_multipart()

    headers["Content-Type"] = "multipart/form-data; boundary=+++"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> HTTPValidationError | SedmlPreview | None:
    if response.status_code == 200:
        response_200 = SedmlPreview.from_dict(response.json())

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
) -> Response[HTTPValidationError | SedmlPreview]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: BodyPreviewSedml,
    solvers: list[str] | None | Unset = UNSET,
) -> Response[HTTPValidationError | SedmlPreview]:
    """Translate a SED-ML archive without running it: its tasks, and what each solver would run or why not

    Args:
        solvers (list[str] | None | Unset): Solvers to run (registry/solvers.yaml); all when
            omitted
        body (BodyPreviewSedml):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | SedmlPreview]
    """

    kwargs = _get_kwargs(
        body=body,
        solvers=solvers,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient | Client,
    body: BodyPreviewSedml,
    solvers: list[str] | None | Unset = UNSET,
) -> HTTPValidationError | SedmlPreview | None:
    """Translate a SED-ML archive without running it: its tasks, and what each solver would run or why not

    Args:
        solvers (list[str] | None | Unset): Solvers to run (registry/solvers.yaml); all when
            omitted
        body (BodyPreviewSedml):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | SedmlPreview
    """

    return sync_detailed(
        client=client,
        body=body,
        solvers=solvers,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: BodyPreviewSedml,
    solvers: list[str] | None | Unset = UNSET,
) -> Response[HTTPValidationError | SedmlPreview]:
    """Translate a SED-ML archive without running it: its tasks, and what each solver would run or why not

    Args:
        solvers (list[str] | None | Unset): Solvers to run (registry/solvers.yaml); all when
            omitted
        body (BodyPreviewSedml):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | SedmlPreview]
    """

    kwargs = _get_kwargs(
        body=body,
        solvers=solvers,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    body: BodyPreviewSedml,
    solvers: list[str] | None | Unset = UNSET,
) -> HTTPValidationError | SedmlPreview | None:
    """Translate a SED-ML archive without running it: its tasks, and what each solver would run or why not

    Args:
        solvers (list[str] | None | Unset): Solvers to run (registry/solvers.yaml); all when
            omitted
        body (BodyPreviewSedml):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | SedmlPreview
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
            solvers=solvers,
        )
    ).parsed
