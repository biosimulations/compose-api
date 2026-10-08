"""The caller's verified identity, without provisioning or resource authorization."""

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from compose_api.authentication import (
    BEARER_SCHEME_NAME,
    RequiredPrincipal,
    get_optional_principal,
)
from compose_api.common.gateway.models import RouterConfig

config = RouterConfig(router=APIRouter(), prefix="/auth", dependencies=[Depends(get_optional_principal)])


class AuthMeResponse(BaseModel):
    """What the service verified about the bearer token: identity, audience, scopes, permissions and roles.

    No bearer credential and no unnecessary personal data (no email, no profile): the access token authorizes
    API calls, and this endpoint only echoes what the service verified in it.
    """

    issuer: str
    subject: str
    audience: list[str]
    roles: list[str]
    scopes: list[str]
    permissions: list[str]


@config.router.get(
    "/me",
    operation_id="get-auth-me",
    response_model=AuthMeResponse,
    responses={401: {"description": "Missing or invalid bearer credentials"}},
    openapi_extra={"security": [{BEARER_SCHEME_NAME: []}]},
    tags=["Authentication"],
    summary="Get the authenticated caller's identity",
)
async def get_auth_me(principal: RequiredPrincipal, response: Response) -> AuthMeResponse:
    response.headers["Cache-Control"] = "no-store"
    return AuthMeResponse(
        issuer=principal.issuer,
        subject=principal.subject,
        audience=sorted(principal.audience),
        roles=sorted(principal.roles),
        scopes=sorted(principal.scopes),
        permissions=sorted(principal.permissions),
    )
