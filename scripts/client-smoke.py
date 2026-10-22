"""Exercise an installed compose-api-client wheel on the Python running this script (CI runs it on the 3.11 floor).

`compose-api --help` never reaches the code that depends on the Python version: preparing private session state
(`FileState`, which checks every ancestor for links) and closing the sign-in listener while a connection is still
open. mypy's 3.11 pass in `make check` catches such calls statically; this runs them.

Run it outside the repository, with the wheel installed in a clean environment and `python -I`, so the installed
package is the one imported.
"""

import asyncio
import socket
import sys
import tempfile
from pathlib import Path

from compose_api_client.auth.callback import CallbackListener
from compose_api_client.auth.state import FileState, SessionState


def private_state() -> None:
    with tempfile.TemporaryDirectory() as directory:
        state = FileState("0" * 64, Path(directory) / "sessions")
        state.write(SessionState(generation=1))
        if state.read().generation != 1:
            raise SystemExit("private session state did not read back what was written")


async def listener_closes_with_an_idle_connection() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    async with CallbackListener(port, state="smoke-state", issuer="https://smoke.example/") as listener:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        await asyncio.sleep(0.2)  # let the listener accept it
        await asyncio.wait_for(listener.close(), 3)  # not the 10 s an idle connection is otherwise allowed
        if await asyncio.wait_for(reader.read(), 3) != b"":
            raise SystemExit("the sign-in listener answered a connection it should have dropped")
        writer.close()


def main() -> None:
    private_state()
    asyncio.run(listener_closes_with_an_idle_connection())
    print(f"compose-api-client smoke test passed on Python {sys.version.split()[0]}")


if __name__ == "__main__":
    main()
