"""The caller's verified identity, without provisioning or resource authorization."""

from fastapi import APIRouter, Response
from pydantic import BaseModel

from compose_api.authentication import BEARER_SCHEME_NAME, RequiredPrincipal
from compose_api.common.gateway.models import RouterConfig

config = RouterConfig(router=APIRouter(), prefix="/auth", dependencies=[])


class CurrentPrincipalResponse(BaseModel):
    issuer: str
    subject: str
    audience: list[str]
    roles: list[str]
    scopes: list[str]
    permissions: list[str]


@config.router.get(
    "/me",
    operation_id="get-current-principal",
    response_model=CurrentPrincipalResponse,
    responses={401: {"description": "Missing or invalid bearer credentials"}},
    openapi_extra={"security": [{BEARER_SCHEME_NAME: []}]},
    tags=["Authentication"],
    summary="Get the authenticated caller's identity",
)
async def get_current_principal(principal: RequiredPrincipal, response: Response) -> CurrentPrincipalResponse:
    response.headers["Cache-Control"] = "no-store"
    return CurrentPrincipalResponse(
        issuer=principal.issuer,
        subject=principal.subject,
        audience=sorted(principal.audience),
        roles=sorted(principal.roles),
        scopes=sorted(principal.scopes),
        permissions=sorted(principal.permissions),
    )
