"""The loopback listener that receives the browser's redirect back from Auth0 (RFC 8252 §7.3).

It binds 127.0.0.1 only, and only for one sign-in. It accepts exactly one well-formed `GET /callback` carrying the
expected state and answers every request with a fixed page: nothing from a request is echoed, logged or reflected.
A request that is malformed, misdirected or carries the wrong state is refused without consuming the transaction, so
a stray or hostile request cannot end a sign-in that is still waiting for the real redirect.
"""

import asyncio
import hmac
import re
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Final, Self
from urllib.parse import parse_qsl

from compose_api.cli.errors import AuthError, InteractionError

CALLBACK_PATH: Final = "/callback"
MAX_REQUEST_HEAD_BYTES: Final = 8 * 1024
CONNECTION_TIMEOUT_SECONDS: Final = 10.0
MAX_QUERY_FIELDS: Final = 16

_ERROR_CODE = re.compile(r"[a-z0-9_]{1,64}")
_AUTHORIZATION_CODE = re.compile(r"[\x21-\x7e]{1,2048}")


@dataclass(frozen=True)
class CallbackResult:
    """What Auth0 sent back: a code, or an error code (from a fixed alphabet, never its description)."""

    code: str | None = field(default=None, repr=False)
    error: str | None = None


def _page(message: str) -> bytes:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>compose-api</title></head>'
        f"<body><p>{message}</p></body></html>"
    ).encode()


_SIGNED_IN = _page("Signed in. You can close this tab and return to the terminal.")
_NOT_SIGNED_IN = _page("Sign-in did not complete. Return to the terminal for details.")
_REFUSED = _page("This address only completes a compose-api sign-in started from a terminal. Nothing was done.")
_HEADERS = (
    "Content-Type: text/html; charset=utf-8\r\n"
    "Cache-Control: no-store\r\n"
    "Pragma: no-cache\r\n"
    "Content-Security-Policy: default-src 'none'; frame-ancestors 'none'; form-action 'none'\r\n"
    "Referrer-Policy: no-referrer\r\n"
    "X-Content-Type-Options: nosniff\r\n"
    "Connection: close\r\n"
)


class CallbackListener:
    """Bind on entry, before any browser opens; unbind on exit. `wait` returns the one accepted callback."""

    def __init__(self, port: int, *, state: str, issuer: str) -> None:
        self.port = port
        self._state = state.encode()
        self._issuer = issuer
        self._host = f"127.0.0.1:{port}"
        self._server: asyncio.Server | None = None
        self._result: asyncio.Future[CallbackResult] | None = None

    async def __aenter__(self) -> Self:
        self._result = asyncio.get_running_loop().create_future()
        try:
            self._server = await asyncio.start_server(
                self._handle, host="127.0.0.1", port=self.port, limit=MAX_REQUEST_HEAD_BYTES
            )
        except OSError:
            raise InteractionError(
                f"cannot listen on 127.0.0.1:{self.port} for the sign-in callback; something else is probably using"
                " that port. Auth0 only returns to the callback port registered for this application, so the CLI"
                " will not pick another: free the port, or sign in from another device with --device"
            )
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.close()

    async def close(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.close()
            server.close_clients()
            await server.wait_closed()
        if self._result is not None and not self._result.done():
            self._result.cancel()

    async def wait(self, timeout: float) -> CallbackResult:
        if self._result is None:
            raise RuntimeError("the listener is not running")
        try:
            async with asyncio.timeout(timeout):
                return await self._result
        except TimeoutError:
            raise AuthError(
                f"sign-in did not finish within {round(timeout / 60)} minutes, so nothing was saved; run the command"
                " again"
            )

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            try:
                async with asyncio.timeout(CONNECTION_TIMEOUT_SECONDS):
                    head = await reader.readuntil(b"\r\n\r\n")
            except asyncio.LimitOverrunError:
                await _respond(writer, HTTPStatus.REQUEST_HEADER_FIELDS_TOO_LARGE, _REFUSED)
                return
            except (asyncio.IncompleteReadError, TimeoutError):
                return
            status, result = self._evaluate(head)
            page = _REFUSED if result is None else _SIGNED_IN if result.code is not None else _NOT_SIGNED_IN
            # Answer first: settling the result lets the sign-in close the listener, which would cut this reply off.
            await _respond(writer, status, page)
            if result is not None and self._result is not None and not self._result.done():
                self._result.set_result(result)
        except ConnectionError:
            pass
        finally:
            writer.close()

    def _evaluate(self, head: bytes) -> tuple[HTTPStatus, CallbackResult | None]:
        """Judge one request head. Returns the status to answer with and, only for the real callback, its result."""
        request = _parse_request_head(head)
        if isinstance(request, HTTPStatus):
            return request, None
        method, target, hosts = request
        if hosts != [self._host]:
            return HTTPStatus.BAD_REQUEST, None
        if method != "GET":
            return HTTPStatus.METHOD_NOT_ALLOWED, None
        if not target.startswith("/") or "#" in target:
            return HTTPStatus.BAD_REQUEST, None
        path, _, query = target.partition("?")
        if path != CALLBACK_PATH:
            return HTTPStatus.NOT_FOUND, None
        result = self._callback_result(query)
        return (HTTPStatus.BAD_REQUEST, None) if result is None else (HTTPStatus.OK, result)

    def _callback_result(self, query: str) -> CallbackResult | None:
        try:
            pairs = parse_qsl(query, keep_blank_values=True, strict_parsing=True, max_num_fields=MAX_QUERY_FIELDS)
        except ValueError:
            return None
        params = dict(pairs)
        if len(params) != len(pairs):  # a repeated parameter is ambiguous, so it is refused outright
            return None
        state = params.get("state")
        if state is None or not hmac.compare_digest(state.encode(), self._state):
            return None
        if "iss" in params and params["iss"] != self._issuer:  # RFC 9207, when the tenant sends it
            return None
        if "error" in params:
            if "code" in params:
                return None
            error = params["error"]
            return CallbackResult(error=error if _ERROR_CODE.fullmatch(error) else "unrecognised_error")
        code = params.get("code")
        if code is None or not _AUTHORIZATION_CODE.fullmatch(code):
            return None
        return CallbackResult(code=code)


def _parse_request_head(head: bytes) -> tuple[str, str, list[str]] | HTTPStatus:
    """Method, request target and Host values of a request head, or the status refusing it."""
    try:
        request_line, *header_lines = head.decode("ascii").split("\r\n")
    except UnicodeDecodeError:
        return HTTPStatus.BAD_REQUEST
    parts = request_line.split(" ")
    if len(parts) != 3 or parts[2] not in ("HTTP/1.1", "HTTP/1.0"):
        return HTTPStatus.BAD_REQUEST
    hosts: list[str] = []
    for line in header_lines:
        if not line:
            continue
        name, separator, value = line.partition(":")
        if not separator or not name or name != name.strip():  # also refuses obsolete line folding
            return HTTPStatus.BAD_REQUEST
        if name.lower() == "host":
            hosts.append(value.strip())
    return parts[0], parts[1], hosts


async def _respond(writer: asyncio.StreamWriter, status: HTTPStatus, page: bytes) -> None:
    head = f"HTTP/1.1 {status.value} {status.phrase}\r\n{_HEADERS}Content-Length: {len(page)}\r\n\r\n"
    writer.write(head.encode() + page)
    await writer.drain()
