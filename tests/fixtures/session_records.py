"""Session records the size Auth0 issues, and the exact bytes the CLI stores for one.

Shared by the store tests that use a fake Credential Manager (tests/cli/test_storage.py) and the opt-in real-store
tests (tests/cli/test_os_keyring.py). This module imports nothing from the server, so the real-store tests still run
alone in a minimal environment (see that module's docstring).
"""

import json
import secrets
import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import jwt
from compose_api_client.auth.models import Identity, SessionRecord
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import SecretStr

ISSUER = "https://dev-bu7yo7484tyxu6a1.us.auth0.com/"
#: Roles and RBAC permissions well past what the tenant grants today (one role, no permissions): what a heavier
#: access token could carry if the BioSim tenant adds roles or enables "Add Permissions in the Access Token".
HEAVY_ROLES = ("user", "admin", "biosimulations-curator", "compose-admin", "vcell-user", "biosimulators-maintainer")
HEAVY_PERMISSIONS = tuple(
    f"{verb}:{noun}"
    for noun in ("simulations", "simulators", "datasets", "comparisons")
    for verb in ("read", "write", "delete", "share")
)


def realistic_session(
    binding_key: str, *, roles: Sequence[str] = ("user",), permissions: Sequence[str] = ()
) -> SessionRecord:
    """A session the size Auth0 issues for this tenant: a 2048-bit RS256 access token carrying the BioSim Roles
    Action's namespaced claims, and a refresh token of Auth0's usual rotating length (about 130 characters).

    `roles` fills the Action's roles claim, and `permissions` adds the `permissions` claim Auth0's RBAC writes when the
    API enables it (the server reads both, `compose_api/authentication.py`).
    """
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = int(time.time())
    claims: dict[str, object] = {
        "https://api.biosimulations.org/roles": list(roles),
        "https://api.biosimulations.org/email": "someone.with.a.long.name@university.example.edu",
        "https://api.biosimulations.org/email_verified": True,
        "iss": ISSUER,
        "sub": "google-oauth2|113192385619293300261",
        "aud": ["https://api.compose.cam.uchc.edu", f"{ISSUER}userinfo"],
        "iat": now,
        "exp": now + 86400,
        "scope": "openid profile email offline_access",
        "azp": "1FV43fysEjhTrYYRNaMEGvCteu4g2ay4",
    }
    if permissions:
        claims["permissions"] = list(permissions)
    access = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "k" * 26, "typ": "JWT"})
    now_utc = datetime.now(UTC)
    return SessionRecord(
        binding_key=binding_key,
        identity=Identity(issuer=ISSUER, subject=str(claims["sub"])),
        access_token=SecretStr(access),
        access_token_expires_at=now_utc + timedelta(days=1),
        refresh_token=SecretStr("v1." + secrets.token_urlsafe(98)),
        scopes=("openid", "profile", "email", "offline_access"),
        obtained_at=now_utc,
        api_verified_at=now_utc,
    )


def serialized(record: SessionRecord) -> str:
    """The record exactly as `KeyringCredentialStore.save` writes it."""
    payload = record.model_dump(mode="json")
    payload["access_token"] = record.access_token.get_secret_value()
    payload["refresh_token"] = None if record.refresh_token is None else record.refresh_token.get_secret_value()
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=True)


def with_parity(record: SessionRecord, parity: int) -> SessionRecord:
    """`record`, one refresh-token character longer if that makes its stored length even (0) or odd (1)."""
    if len(serialized(record)) % 2 == parity or record.refresh_token is None:
        return record
    return record.model_copy(update={"refresh_token": SecretStr(record.refresh_token.get_secret_value() + "x")})


def with_size(record: SessionRecord, size: int) -> SessionRecord:
    """`record`, its refresh token lengthened so that the stored record is exactly `size` bytes."""
    assert record.refresh_token is not None
    grow = size - len(serialized(record))
    assert grow >= 0, "a realistic session is smaller than the sizes these tests pin"
    return record.model_copy(update={"refresh_token": SecretStr(record.refresh_token.get_secret_value() + "x" * grow)})
