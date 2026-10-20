"""Windows owner-only ACL enforcement for non-secret concurrency state, and the session's Credential Manager item
(loaded on Windows only)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from compose_api_client.ext.errors import StorageError

TOKEN_QUERY = 0x0008
OBJECT_INHERIT_ACE = 0x1
CONTAINER_INHERIT_ACE = 0x2
FILE_ALL_ACCESS = 0x001F01FF
ERROR_NOT_FOUND = 1168


def _principals() -> tuple[Any, tuple[Any, ...]]:
    import win32api
    import win32security

    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), TOKEN_QUERY)
    try:
        user = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
        owner = win32security.GetTokenInformation(token, win32security.TokenOwner)
        return user, (user, owner)
    finally:
        token.Close()


def protect(path: Path) -> None:
    """Install a protected DACL containing only the current user, inherited by new children."""
    import win32security

    try:
        sid, _ = _principals()
        acl = win32security.ACL()
        acl.AddAccessAllowedAceEx(
            win32security.ACL_REVISION,
            CONTAINER_INHERIT_ACE | OBJECT_INHERIT_ACE,
            FILE_ALL_ACCESS,
            sid,
        )
        win32security.SetNamedSecurityInfo(
            str(path),
            win32security.SE_FILE_OBJECT,
            win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
            None,
            None,
            acl,
            None,
        )
        validate(path)
    except Exception:
        raise StorageError("Cannot install private Windows session-state ACL") from None


def validate(path: Path) -> None:
    import win32security

    try:
        descriptor = win32security.GetNamedSecurityInfo(
            str(path),
            win32security.SE_FILE_OBJECT,
            win32security.OWNER_SECURITY_INFORMATION | win32security.DACL_SECURITY_INFORMATION,
        )
        sid, owners = _principals()
        acl = descriptor.GetSecurityDescriptorDacl()
        valid = descriptor.GetSecurityDescriptorOwner() in owners and acl is not None and acl.GetAceCount() > 0
        if valid:
            for index in range(acl.GetAceCount()):
                ace = acl.GetAce(index)
                if ace[0][0] != win32security.ACCESS_ALLOWED_ACE_TYPE or ace[2] != sid:
                    valid = False
                    break
    except Exception:
        raise StorageError("Cannot verify Windows session-state ACL") from None
    if not valid:
        raise StorageError("Windows session state must be owned and accessible only by the current user")


def replace(source: str, target: Path) -> None:
    import win32file

    try:
        # MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH
        win32file.MoveFileEx(source, str(target), 0x1 | 0x8)
    except Exception:
        raise StorageError("Cannot durably replace Windows session metadata") from None


def write_credential(service: str, account: str, value: str) -> None:
    """Atomic Credential Manager overwrite, without keyring's legacy shadow-copy migration.

    The item holds `value`'s UTF-8 bytes. pywin32 writes a blob only from a `str`, as UTF-16, which would double a
    session past the item's 2560 bytes (#320), so it is handed the `str` whose UTF-16-LE code units are those bytes;
    an odd length gains a NUL. `value` must be ASCII without NUL, as compact JSON is: then every code unit lies between
    0x0001 and 0x7F7F, never NUL or a surrogate, and pywin32 stores it unchanged.
    """
    import win32cred

    data = value.encode("ascii")
    if b"\0" in data:
        raise ValueError("a credential value cannot contain NUL")
    if len(data) % 2:
        data += b"\0"
    win32cred.CredWrite(
        {
            "Type": win32cred.CRED_TYPE_GENERIC,
            "TargetName": service,
            "UserName": account,
            "CredentialBlob": data.decode("utf-16-le"),
            "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
            "Comment": "Compose API CLI session",
        },
        0,
    )


def read_credential(service: str, account: str) -> str | None:
    """What `write_credential` stored for `account`, or None.

    Not keyring's `get_password`: it decodes a blob as UTF-16 first and tries UTF-8 only when that fails, and an
    even-length ASCII blob decodes as UTF-16 without failing, into other characters.
    """
    import pywintypes
    import win32cred

    try:
        credential = win32cred.CredRead(Type=win32cred.CRED_TYPE_GENERIC, TargetName=service)
    except pywintypes.error as error:
        if error.winerror == ERROR_NOT_FOUND:
            return None
        raise
    if credential["UserName"] != account:
        return None  # not this account's item, as keyring treats it
    blob: bytes = credential["CredentialBlob"]
    # Undecodable bytes survive as lone surrogates, which the store refuses as an invalid encoding.
    return blob.removesuffix(b"\0").decode("utf-8", "surrogateescape")
