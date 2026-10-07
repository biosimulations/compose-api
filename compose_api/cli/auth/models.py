"""What a sign-in produces and what it carries while in flight.

Every token, code and verifier is a `SecretStr` or a `repr=False` field, so printing, logging or JSON-dumping one of
these objects shows a mask, never the credential. Only `issuer` and `subject` identify a person; email is not kept.
"""

import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Final, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, SecretStr

SESSION_SCHEMA_VERSION: Literal[1] = 1
# How long a browser or device sign-in may wait for the person; a shorter server expiry wins.
SIGN_IN_TIMEOUT_SECONDS: Final = 300.0

# Progress and instructions for the person signing in. Never given a token, code or verifier.
type Notify = Callable[[str], None]


class Provider(StrEnum):
    EMAIL = "email"
    GOOGLE = "google"


@dataclass(frozen=True)
class SignInRequest:
    """How a person asked to sign in. `provider` is a hint for the hosted page, not a guarantee."""

    signup: bool
    provider: Provider | None
    device: bool
    open_browser: bool
    persistent: bool


@dataclass(frozen=True)
class AuthTransaction:
    """One browser sign-in attempt. Lives in memory only and is never reused after its callback or deadline."""

    redirect_uri: str
    scopes: tuple[str, ...]
    state: str = field(repr=False, default_factory=lambda: secrets.token_urlsafe(32))
    nonce: str = field(repr=False, default_factory=lambda: secrets.token_urlsafe(32))
    # 64 base64url characters: inside RFC 7636's 43-128 range and alphabet.
    code_verifier: str = field(repr=False, default_factory=lambda: secrets.token_urlsafe(48))


class Identity(BaseModel):
    """Who signed in, as Auth0 and the API identify them. Never an email: two accounts can share one."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    issuer: str
    subject: str


class TokenGrant(BaseModel):
    """A token response that passed every check in `oauth.py`. Nothing unvalidated is ever stored in one."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    identity: Identity
    access_token: SecretStr
    access_token_expires_at: datetime  # the earlier of the JWT's exp and receipt + expires_in, UTC
    refresh_token: SecretStr | None
    scopes: tuple[str, ...]
    received_at: datetime


class SessionRecord(BaseModel):
    """A stored session, written and read as one whole record."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = SESSION_SCHEMA_VERSION
    binding_key: str
    identity: Identity
    access_token: SecretStr
    access_token_expires_at: AwareDatetime
    refresh_token: SecretStr | None
    scopes: tuple[str, ...]
    obtained_at: AwareDatetime
    generation: int = Field(default=0, ge=0, strict=True)
    api_verified_at: AwareDatetime | None = None  # None until the Compose API has confirmed this identity

    @classmethod
    def from_grant(cls, grant: TokenGrant, *, binding_key: str, generation: int = 0) -> "SessionRecord":
        return cls(
            binding_key=binding_key,
            identity=grant.identity,
            access_token=grant.access_token,
            access_token_expires_at=grant.access_token_expires_at,
            refresh_token=grant.refresh_token,
            scopes=grant.scopes,
            obtained_at=grant.received_at,
            generation=generation,
        )
