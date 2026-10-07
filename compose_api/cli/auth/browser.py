"""Browser sign-in: Authorization Code with PKCE through the system browser and a loopback callback (RFC 8252).

Passwords, MFA, email verification and Google consent all happen on Auth0's hosted pages in the person's own browser;
the CLI never sees them and never embeds a web view. The callback listener is bound before the browser opens, so a
taken port fails the command before anything else happens.
"""

import asyncio
import os
import sys
import webbrowser
from collections.abc import Callable

from compose_api.cli.auth.callback import CallbackListener
from compose_api.cli.auth.models import (
    SIGN_IN_TIMEOUT_SECONDS,
    AuthTransaction,
    Notify,
    Provider,
    SignInRequest,
    TokenGrant,
)
from compose_api.cli.auth.oauth import Auth0OAuthClient
from compose_api.cli.config import requested_scopes
from compose_api.cli.errors import AuthError, CliError, InteractionError, NetworkError, ProtocolError

type BrowserLauncher = Callable[[str], bool]


def open_system_browser(url: str) -> bool:
    """Hand the URL to the desktop's browser; False when there is none to hand it to."""
    if sys.platform not in ("darwin", "win32") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return False  # with no display, webbrowser would start a text browser inside this terminal
    try:
        return webbrowser.open(url, new=1)
    except webbrowser.Error:
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
        if request.open_browser:
            if not await asyncio.to_thread(launcher, url):
                raise InteractionError(
                    "no browser could be opened. Run the command again with --no-browser to open the sign-in link"
                    " yourself on this computer, or with --device to sign in from another device"
                )
            notify(f"Continue in the browser window that just opened. Waiting up to {minutes} minutes.")
        else:
            notify(
                "Open this link in a browser on this computer to sign in. It works only for this command, so open"
                f" only a link you just printed yourself:\n\n  {url}\n\nWaiting up to {minutes} minutes. If your"
                " browser is on another computer, use --device instead."
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
