"""Browser sign-in: Authorization Code with PKCE through the system browser and a loopback callback (RFC 8252).

Passwords, MFA, email verification and Google consent all happen on Auth0's hosted pages in the person's own browser;
the CLI never sees them and never embeds a web view. The callback listener is bound before the browser opens, so a
taken port fails the command before anything else happens.
"""

from __future__ import annotations

import asyncio
import os
import shlex
import sys
import webbrowser
from collections.abc import Callable
from pathlib import PurePosixPath, PureWindowsPath
from typing import TypeAlias

from compose_api_client.auth.callback import CallbackListener
from compose_api_client.auth.models import (
    SIGN_IN_TIMEOUT_SECONDS,
    AuthTransaction,
    Notify,
    Provider,
    SignInMethod,
    SignInRequest,
    TokenGrant,
)
from compose_api_client.auth.oauth import Auth0OAuthClient
from compose_api_client.ext.errors import AuthError, CliError, InteractionError, NetworkError, ProtocolError
from compose_api_client.profiles import requested_scopes

BrowserLauncher: TypeAlias = Callable[[str], bool]
# webbrowser's text browsers (`webbrowser.register_standard_browsers`): they would run in, and take over, this terminal.
CONSOLE_BROWSERS = frozenset({"www-browser", "links", "elinks", "lynx", "w3m"})


def _has_display() -> bool:
    """Whether a graphical browser can open: macOS and Windows always have a desktop; Linux needs X11 or Wayland."""
    return sys.platform in ("darwin", "win32") or bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _callback_forwarder() -> str | None:
    """Who carries the loopback callback back from the person's own browser when `$BROWSER` opens the link, if anyone.

    VS Code (Remote-SSH, Dev Containers) sets `$BROWSER` to a helper that opens the link on the person's computer, and
    forwards the ports this host listens on; WSL's `wslview` opens the Windows browser. An environment marker alone
    does not identify the handler: shell configuration can replace `$BROWSER` with a text browser or another command.
    Unknown commands, argument wrappers and fallback lists conservatively get the device code under `auto`.
    """
    browser = os.environ.get("BROWSER", "")
    if not browser or os.pathsep in browser:
        return None
    # webbrowser treats a value containing %s as a command line; otherwise it is a literal executable name/path.
    if "%s" in browser:
        try:
            command = shlex.split(browser)
        except ValueError:
            return None
        if len(command) != 2 or command[1] != "%s":
            return None
        browser = command[0]
    helpers = ((PurePosixPath(browser), "browser.sh"), (PureWindowsPath(browser), "browser.cmd"))
    vscode_helper = any(path.is_absolute() and path.parts[-3:] == ("bin", "helpers", name) for path, name in helpers)
    if vscode_helper and (os.environ.get("VSCODE_IPC_HOOK_CLI") or os.environ.get("TERM_PROGRAM") == "vscode"):
        return "VS Code"
    path = PurePosixPath(browser)
    if os.environ.get("WSL_DISTRO_NAME") and (browser == "wslview" or (path.is_absolute() and path.name == "wslview")):
        return "WSL"
    return None


def _console_browser() -> bool:
    """Whether any entry of `$BROWSER` runs one of webbrowser's text browsers, as a server's dotfiles often set it
    (`BROWSER=w3m`, `/usr/bin/lynx %s`)."""
    for entry in os.environ.get("BROWSER", "").split(os.pathsep):
        try:
            command = shlex.split(entry)
        except ValueError:
            continue
        if command and PurePosixPath(command[0]).name in CONSOLE_BROWSERS:
            return True
    return False


def auto_method(callback_port: int) -> tuple[SignInMethod, str | None]:
    """What `SignInMethod.AUTO` means here, and what to tell the person about that choice: why, and how to choose
    another way. There is nothing to tell for the ordinary case, the browser on this computer's desktop.

    A GitHub Codespace gets the device code. Otherwise a desktop gets the browser, unless this is an SSH session
    (`SSH_CONNECTION`, the only remote signal on macOS and Windows, where there is no display variable). Over SSH or
    without a display, the browser still works through a `$BROWSER` that VS Code or WSL set, since they forward the
    callback port (`open_system_browser` hands the link to it); anything else gets the device code.
    """
    if os.environ.get("CODESPACES"):
        # A codespace opened in a web browser cannot receive a callback on 127.0.0.1; one opened in desktop VS Code
        # could, but nothing tells the two apart, and the device code works in both.
        return SignInMethod.DEVICE, (
            "Signing in with a device code, since this is a GitHub Codespace. In a codespace opened in desktop VS"
            " Code, --method browser works too."
        )
    ssh = bool(os.environ.get("SSH_CONNECTION"))
    if not ssh and _has_display():
        return SignInMethod.BROWSER, None
    forwarder = _callback_forwarder()
    if forwarder is not None:
        return SignInMethod.BROWSER, (
            f"Opening the sign-in page through $BROWSER, since {forwarder} forwards the callback port. If the browser"
            " cannot return to this machine after you sign in, run again with --method device."
        )
    if ssh:
        # --method browser would open a browser on this host's own screen, if it has one, not the person's.
        return SignInMethod.DEVICE, (
            "Signing in with a device code, since this is an SSH session. To use the browser on your own computer"
            f" instead, forward the callback port (ssh -L {callback_port}:127.0.0.1:{callback_port}) and run again"
            " with --method url."
        )
    return SignInMethod.DEVICE, (
        "Signing in with a device code, since this host has no display. To open the sign-in link yourself in a"
        f" browser that can reach port {callback_port} here, run again with --method url."
    )


def open_system_browser(url: str) -> bool:
    """Hand the URL to the desktop's browser, or to `$BROWSER` on a host without one; False when there is neither.

    Without a display, a `$BROWSER` that names a text browser counts as none: it would take over this terminal, and
    the sign-in would not go on until it exited. `auto` never gets here with one, since it trusts only VS Code's and
    WSL's handlers (`_callback_forwarder`); an explicit `--method browser` does.
    """
    try:
        if _has_display():
            return webbrowser.open(url, new=1)
        if os.environ.get("BROWSER") and not _console_browser():
            # $BROWSER alone, such as VS Code Remote-SSH's helper or wslview: webbrowser's other choices without a
            # display are text browsers too.
            return webbrowser.get().open(url, new=1)
    except webbrowser.Error:
        return False
    return False


async def browser_sign_in(
    client: Auth0OAuthClient,
    request: SignInRequest,
    *,
    connection: str | None,
    launcher: BrowserLauncher,
    notify: Notify,
    timeout: float = SIGN_IN_TIMEOUT_SECONDS,
) -> TokenGrant:
    settings = client.settings
    transaction = AuthTransaction(
        redirect_uri=settings.redirect_uri, scopes=requested_scopes(persistent=request.persistent)
    )
    async with CallbackListener(settings.callback_port, state=transaction.state, issuer=settings.issuer) as listener:
        url = await client.authorization_url(
            transaction,
            connection=connection,
            # Sign-up always shows the hosted page, even over an existing browser session; the sign-up form itself
            # applies only to email accounts, since a first Google sign-in is what creates a Google account.
            screen_hint="signup" if request.signup and request.provider is not Provider.GOOGLE else None,
            prompt="login" if request.signup else None,
        )
        minutes = round(timeout / 60)
        if request.method is not SignInMethod.URL:
            if not await asyncio.to_thread(launcher, url):
                raise InteractionError(
                    "no browser could be opened. Run the command again with --method url to open the sign-in link"
                    " yourself on this computer, or with --method device to sign in from another device"
                )
            notify(f"Continue in the browser window that just opened. Waiting up to {minutes} minutes.")
        else:
            notify(
                "Open this link in a browser on this computer to sign in. It works only for this command, so open"
                f" only a link you just printed yourself:\n\n  {url}\n\nWaiting up to {minutes} minutes. If your"
                " browser is on another computer, use --method device instead."
            )
        result = await listener.wait(timeout)
    if result.error is not None:
        raise _authorization_error(result.error)
    if result.code is None:
        raise ProtocolError("the sign-in callback carried no code")
    return await client.exchange_code(transaction, result.code)


def _authorization_error(error: str) -> CliError:
    if error == "access_denied":
        return AuthError("sign-in was cancelled or refused in the browser; nothing was saved")
    if error in ("login_required", "consent_required", "interaction_required", "account_selection_required"):
        return AuthError(f"sign-in did not complete in the browser ({error}); nothing was saved, run the command again")
    if error in ("server_error", "temporarily_unavailable"):
        return NetworkError(f"Auth0 could not complete the sign-in ({error}); try again shortly")
    return ProtocolError(
        f"Auth0 refused to start the sign-in ({error}); check the profile's auth0_client_id, callback_port and"
        " connection names"
    )
