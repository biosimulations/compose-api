"""Windows owner-only ACL enforcement for non-secret concurrency state (loaded on Windows only)."""

from pathlib import Path
from typing import Any

from compose_api.cli.errors import StorageError


def _identity() -> Any:
    import win32api
    import win32con
    import win32security

    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        return win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    finally:
        token.Close()


def protect(path: Path) -> None:
    """Install a protected DACL containing only the current user, inherited by new children."""
    import win32con
    import win32security

    try:
        sid = _identity()
        acl = win32security.ACL()
        acl.AddAccessAllowedAceEx(
            win32security.ACL_REVISION,
            win32con.CONTAINER_INHERIT_ACE | win32con.OBJECT_INHERIT_ACE,
            win32con.FILE_ALL_ACCESS,
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
        sid = _identity()
        acl = descriptor.GetSecurityDescriptorDacl()
        valid = descriptor.GetSecurityDescriptorOwner() == sid and acl is not None and acl.GetAceCount() > 0
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
    """Atomic Credential Manager overwrite, without keyring's legacy shadow-copy migration."""
    import win32cred

    win32cred.CredWrite(
        {
            "Type": win32cred.CRED_TYPE_GENERIC,
            "TargetName": service,
            "UserName": account,
            "CredentialBlob": value,
            "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
            "Comment": "Compose API CLI session",
        },
        0,
    )
