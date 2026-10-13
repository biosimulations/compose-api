"""Real OS credential stores: macOS Keychain, Linux Secret Service, Windows Credential Manager.

Opt-in, because these write to the machine's actual store: set COMPOSE_API_TEST_OS_KEYRING=1. The record is synthetic,
stored under a random binding key that can never collide with a real session, and deleted in a `finally` even when an
assertion fails. The tests reach the real backend through `keyring.core`, past the suite's refusing default.

This module imports nothing from the server, so it also runs alone in a minimal environment (see docs/cli.md):
`python -m pytest --noconftest -o addopts= tests/cli/test_os_keyring.py`.
"""

import json
import os
import secrets
import time
from datetime import UTC, datetime, timedelta

import jwt
import keyring.core
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import SecretStr

from compose_api.cli.auth.models import Identity, SessionRecord
from compose_api.cli.auth.storage import SERVICE, KeyringCredentialStore
from compose_api.cli.errors import StorageError

WINDOWS_CREDENTIAL_BLOB_LIMIT = 2560  # bytes; the store writes UTF-16, so about 1280 characters
ISSUER = "https://dev-bu7yo7484tyxu6a1.us.auth0.com/"

opt_in = pytest.mark.skipif(
    os.environ.get("COMPOSE_API_TEST_OS_KEYRING") != "1",
    reason="writes to this machine's real credential store; set COMPOSE_API_TEST_OS_KEYRING=1 to run",
)


def realistic_session(binding_key: str) -> SessionRecord:
    """A session the size Auth0 issues for this tenant: a 2048-bit RS256 access token carrying the BioSim Roles
    Action's namespaced claims, and a refresh token of Auth0's usual rotating length (about 130 characters)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = int(time.time())
    claims = {
        "https://api.biosimulations.org/roles": ["user"],
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
    return json.dumps(payload, separators=(",", ":"))


def test_a_realistic_session_does_not_fit_a_windows_credential() -> None:
    """Measured, not assumed: why persistent sessions are not supported on Windows yet (docs/cli.md)."""
    raw = serialized(realistic_session("0" * 64))
    assert len(raw.encode("utf-16-le")) > WINDOWS_CREDENTIAL_BLOB_LIMIT
    assert len(raw.encode()) < WINDOWS_CREDENTIAL_BLOB_LIMIT, "it would fit if stored as UTF-8"


@opt_in
def test_the_platform_store_keeps_a_realistic_session_whole() -> None:
    backend = keyring.core.get_keyring()
    store = KeyringCredentialStore(backend)  # refuses anything but the three approved OS stores
    store.probe()
    binding = secrets.token_hex(32)
    record = realistic_session(binding)
    windows = type(backend).__module__ == "keyring.backends.Windows"
    try:
        if windows:
            with pytest.raises(StorageError, match="atomic item limit"):
                store.save(binding, record)
            assert store.load(binding) is None, "a refused record leaves nothing behind"
            return
        store.save(binding, record)
        assert store.load(binding) == record
        stored = backend.get_password(f"{SERVICE}.{binding}", binding)
        assert stored == serialized(record), "one item holds the whole record"
        assert binding in f"{SERVICE}.{binding}" and "@" not in f"{SERVICE}.{binding}", "no email in the item name"
    finally:
        store.delete(binding)
    assert store.load(binding) is None
    assert backend.get_password(f"{SERVICE}.{binding}", binding) is None


@opt_in
def test_the_platform_store_replaces_a_session_in_place() -> None:
    """A renewal overwrites the item; no second copy of a spent credential is left behind."""
    backend = keyring.core.get_keyring()
    store = KeyringCredentialStore(backend)
    binding = secrets.token_hex(32)
    small = realistic_session(binding).model_copy(
        update={"access_token": SecretStr("a" * 200), "refresh_token": SecretStr("first")}
    )
    successor = small.model_copy(update={"refresh_token": SecretStr("second"), "generation": 1})
    try:
        store.save(binding, small)
        store.save(binding, successor)
        loaded = store.load(binding)
        assert loaded is not None and loaded.refresh_token == SecretStr("second") and loaded.generation == 1
    finally:
        store.delete(binding)
    assert store.load(binding) is None
