"""The `compose-api` command line.

Only argparse, the version string and the error types load before a command runs, so `--help` and `--version` work
offline and without configuration; each command imports what it needs when it runs. Nothing here imports
`compose_api.config`: that module loads the server's dotenv files, `$SECRET_ENV_FILE` included.

All commands resolve and validate their profile before contacting a server or opening a browser. Errors are
`CliError`s, printed as one escaped line (and a JSON object with --json); anything else is reported as an internal
error by type only, because a traceback can carry values that must not reach a terminal or a log.
"""

import argparse
import json
import math
import sys
from collections.abc import Callable, Sequence

from compose_api.cli.errors import CliError, ExitCode
from compose_api.version import __version__

PROG = "compose-api"

_EPILOG = """\
exit status:
  0    success
  1    the API or command reported a failure
  2    usage error
  3    sign-in required, or the session has expired
  4    the API refused the request (forbidden)
  5    network failure or rate limit
  6    configuration, credential storage or protocol error
  130  cancelled

Profiles come from COMPOSE_API_CLI_* environment variables and config.toml in the user config directory;
`compose-api config show` prints the effective values and where each came from.
"""

type Handler = Callable[[argparse.Namespace], int]
type Subcommands = argparse._SubParsersAction[argparse.ArgumentParser]


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        if getattr(args, "ephemeral_auth", True) is False and (args.device or args.no_browser):
            parser.error(
                "--device and --no-browser choose how --ephemeral-auth signs in, so they need --ephemeral-auth"
            )
    except SystemExit as exc:  # --help, --version and usage errors; argparse has already written the output
        return exc.code if isinstance(exc.code, int) else int(ExitCode.USAGE)
    # --profile and --json are accepted before or after the command, so neither has a parser-level default.
    args.profile = getattr(args, "profile", None)
    args.json = getattr(args, "json", False)

    handler: Handler = args.handler
    try:
        return handler(args)
    except CliError as exc:
        return _report(args, exc.category, exc.message, exc.exit_code)
    except KeyboardInterrupt:
        print(f"{PROG}: cancelled", file=sys.stderr)
        return int(ExitCode.CANCELLED)
    except Exception as exc:
        return _report(
            args, "internal", f"internal error ({type(exc).__name__}); this is a bug in {PROG}", ExitCode.FAILURE
        )


def _report(args: argparse.Namespace, category: str, message: str, code: ExitCode) -> int:
    from compose_api.cli.output import printable_lines

    print(f"{PROG}: error: {printable_lines(message)}", file=sys.stderr)
    if args.json:
        print(json.dumps({"error": {"category": category, "message": message, "exit_code": int(code)}}))
    return int(code)


def build_parser() -> argparse.ArgumentParser:
    # Global options live on every level of the tree. SUPPRESS keeps a subcommand from resetting a value given
    # before it, which is what a plain default would do.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--profile",
        metavar="NAME",
        default=argparse.SUPPRESS,
        help="profile to use: production (default), local, or one defined in config.toml",
    )
    common.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="write a machine-readable JSON object to stdout",
    )

    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Sign in to the Compose API and call it from the command line.",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[common],
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(title="commands", metavar="COMMAND", required=True)
    _add_config_commands(commands, common)
    _add_auth_commands(commands, common)
    _add_api_commands(commands, common)
    return parser


def _add_config_commands(commands: Subcommands, common: argparse.ArgumentParser) -> None:
    group = commands.add_parser("config", parents=[common], help="inspect the CLI configuration")
    subcommands = group.add_subparsers(title="commands", metavar="COMMAND", required=True)
    show = subcommands.add_parser(
        "show",
        parents=[common],
        help="print the effective profile and where each value came from",
        description="Print the effective public profile and the source of each value. Profiles hold no secrets.",
    )
    show.set_defaults(handler=_show_config)


def _add_auth_commands(commands: Subcommands, common: argparse.ArgumentParser) -> None:
    group = commands.add_parser("auth", parents=[common], help="sign up, sign in, check or end a session")
    subcommands = group.add_subparsers(title="commands", metavar="COMMAND", required=True)

    signup = subcommands.add_parser(
        "signup",
        parents=[common],
        help="create an account in the browser, then sign in",
        description="Open Auth0's hosted sign-up page. Passwords are entered there, never in this terminal.",
    )
    _add_provider_option(signup, default="email")
    _add_interaction_options(signup)
    signup.set_defaults(handler=_auth_signup)

    login = subcommands.add_parser(
        "login",
        parents=[common],
        help="sign in in the browser",
        description="Sign in through Auth0's hosted login page.",
    )
    _add_provider_option(login, default=None)
    _add_interaction_options(login)
    login.set_defaults(handler=_auth_login)

    status = subcommands.add_parser(
        "status",
        parents=[common],
        help="show the stored session",
        description="Show the stored session without contacting any server, unless --verify is given.",
    )
    status.add_argument("--verify", action="store_true", help="refresh if needed and confirm the identity with the API")
    status.set_defaults(handler=_auth_status)

    logout = subcommands.add_parser(
        "logout",
        parents=[common],
        help="revoke and erase the stored session",
        description="Revoke the refresh token with Auth0 and erase the local session.",
    )
    logout.add_argument("--local-only", action="store_true", help="erase the local session without contacting Auth0")
    logout.set_defaults(handler=_auth_logout)


def _add_api_commands(commands: Subcommands, common: argparse.ArgumentParser) -> None:
    simulators = commands.add_parser("simulators", parents=[common], help="simulator catalog")
    simulator_commands = simulators.add_subparsers(title="commands", metavar="COMMAND", required=True)
    list_simulators = simulator_commands.add_parser("list", parents=[common], help="list the available simulators")
    _add_ephemeral_auth_options(list_simulators)
    list_simulators.set_defaults(handler=_simulators_list)

    simulations = commands.add_parser("simulations", parents=[common], help="submit simulations and check on them")
    simulation_commands = simulations.add_subparsers(title="commands", metavar="COMMAND", required=True)

    status = simulation_commands.add_parser("status", parents=[common], help="show a simulation's status")
    status.add_argument("simulation_id", metavar="ID", type=_positive_int, help="the simulation's numeric ID")
    _add_ephemeral_auth_options(status)
    status.set_defaults(handler=_simulations_status)

    submit = simulation_commands.add_parser(
        "submit",
        parents=[common],
        help="submit an OMEX archive",
        description="Submit an existing OMEX archive. Prints the server's reference to the run; it does not wait.",
    )
    submit.add_argument("file", metavar="FILE", help="the .omex archive to upload")
    submit.add_argument(
        "--interval-time", metavar="N", type=_positive_float, help="output interval passed to the simulation"
    )
    submit.add_argument("--batch", action="store_true", help="submit as a batch job")
    _add_ephemeral_auth_options(submit)
    submit.set_defaults(handler=_simulations_submit)


def _add_provider_option(parser: argparse.ArgumentParser, *, default: str | None) -> None:
    parser.add_argument(
        "--provider",
        choices=("email", "google"),
        default=default,
        help="identity provider to start with; with --device the choice is made on the hosted page instead",
    )


def _add_interaction_options(parser: argparse.ArgumentParser) -> None:
    how = parser.add_mutually_exclusive_group()
    how.add_argument("--device", action="store_true", help="sign in on another device (for SSH and headless use)")
    how.add_argument(
        "--no-browser", action="store_true", help="print the sign-in URL to open on this machine instead of opening it"
    )


def _add_ephemeral_auth_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--ephemeral-auth",
        action="store_true",
        help="sign in for this command only, keeping credentials in memory (for hosts without a credential store)",
    )
    _add_interaction_options(parser)


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a whole number")
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def _positive_float(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a number")
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("must be a positive, finite number")
    return value


def _show_config(args: argparse.Namespace) -> int:
    from compose_api.cli.config import load_cli_settings

    loaded = load_cli_settings(args.profile)
    view = loaded.public_view()
    if args.json:
        print(json.dumps(view, indent=2))
    else:
        profile, config_file = view["profile"], view["config_file"]
        rows = [
            ("profile", profile["value"], profile["source"]),
            ("config file", config_file["path"], "found" if config_file["found"] else "not found"),
            *((name, entry["value"], entry["source"]) for name, entry in view["settings"].items()),
            *((name, value, "derived") for name, value in view["derived"].items()),
        ]
        width = max(len(name) for name, _, _ in rows)
        for name, value, source in rows:
            print(f"{name:<{width}}  {'-' if value is None else value}  ({source})")
    if loaded.settings.auth0_client_id is None:
        print(
            f"{PROG}: note: auth0_client_id is not set, so profile {loaded.settings.profile!r} cannot sign in yet",
            file=sys.stderr,
        )
    return int(ExitCode.OK)


def _auth_signup(args: argparse.Namespace) -> int:
    from compose_api.cli.commands.auth import signup

    return signup(args)


def _auth_login(args: argparse.Namespace) -> int:
    from compose_api.cli.commands.auth import login

    return login(args)


def _auth_status(args: argparse.Namespace) -> int:
    from compose_api.cli.commands.auth import status

    return status(args)


def _auth_logout(args: argparse.Namespace) -> int:
    from compose_api.cli.commands.auth import logout

    return logout(args)


def _simulators_list(args: argparse.Namespace) -> int:
    from compose_api.cli.commands.api import list_simulators

    return list_simulators(args)


def _simulations_status(args: argparse.Namespace) -> int:
    from compose_api.cli.commands.api import simulation_status

    return simulation_status(args)


def _simulations_submit(args: argparse.Namespace) -> int:
    from compose_api.cli.commands.api import submit_simulation

    return submit_simulation(args)
