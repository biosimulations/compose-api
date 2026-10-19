"""Browser sign-in: Authorization Code with PKCE through the system browser and a loopback callback (RFC 8252).

Passwords, MFA, email verification and Google consent all happen on Auth0's hosted pages in the person's own browser;
the CLI never sees them and never embeds a web view. The callback listener is bound before the browser opens, so a
taken port fails the command before anything else happens.
"""

from __future__ import annotations

import asyncio
import os
import sys
import webbrowser
from collections.abc import Callable
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


def _has_display() -> bool:
    """Whether a graphical browser can open: macOS and Windows always have a desktop; Linux needs X11 or Wayland."""
    return sys.platform in ("darwin", "win32") or bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _auto() -> tuple[SignInMethod, str]:
    """What `SignInMethod.AUTO` resolves to here, and why (the reason is printed when it picks the device code)."""
    if os.environ.get("CODESPACES"):
        # A codespace opened in a web browser cannot receive a callback on 127.0.0.1; one opened in desktop VS Code
        # could, but nothing tells the two apart, and the device code works in both.
        return SignInMethod.DEVICE, "this is a GitHub Codespace"
    if os.environ.get("BROWSER"):
        return SignInMethod.BROWSER, "$BROWSER is set"
    if os.environ.get("SSH_CONNECTION"):
        return SignInMethod.DEVICE, "this is an SSH session"
    if not _has_display():
        return SignInMethod.DEVICE, "this host has no display"
    return SignInMethod.BROWSER, "a browser can open here"


def resolve_method(requested: SignInMethod) -> SignInMethod:
    """What `SignInMethod.AUTO` means here: device over SSH, browser when a browser can plausibly open.

    `$BROWSER` wins over SSH and a missing display: VS Code Remote-SSH and WSL set it and forward the callback port,
    so the browser flow works there despite `SSH_CONNECTION` (`open_system_browser` hands the link to it). A GitHub
    Codespace is the exception and gets the device code. `SSH_CONNECTION` is the only remote signal on macOS and
    Windows, where there is no display variable. A host with no display cannot open a browser, so it gets the device
    code. An explicit choice is returned as it is.
    """
    return _auto()[0] if requested is SignInMethod.AUTO else requested


def auto_reason() -> str:
    """Why `SignInMethod.AUTO` resolves as it does here."""
    return _auto()[1]


def open_system_browser(url: str) -> bool:
    """Hand the URL to the desktop's browser, or to `$BROWSER` on a host without one; False when there is neither."""
    try:
        if _has_display():
            return webbrowser.open(url, new=1)
        if os.environ.get("BROWSER"):
            # A handler such as VS Code Remote-SSH's or wslview, and only that: webbrowser's other choices without a
            # display are text browsers, which would take over this terminal.
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
