"""Public CLI profiles: which API the CLI calls and which Auth0 tenant, audience and application it signs in with.

This is deliberately independent of `compose_api.config`. Importing that module loads the server's dotenv files,
`$SECRET_ENV_FILE` included, and the CLI must never read them. Nothing configured here is secret: a profile holds
public identifiers only, and a key or value that looks like a credential is rejected rather than carried along.

Profile selection is `--profile` > `COMPOSE_API_CLI_PROFILE` > `production`. Each setting then resolves from its
`COMPOSE_API_CLI_<NAME>` environment variable > `[profiles.<profile>]` in the user config file > the built-in default.
The config file lives in the platform's user config directory; the working directory is never consulted.
"""

import hashlib
import ipaddress
import json
import os
import re
import stat
import sys
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final
from urllib.parse import SplitResult, urlsplit

import platformdirs
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from compose_api.cli.errors import ConfigError

APP_NAME = "compose-api"
ENV_PREFIX = "COMPOSE_API_CLI_"
PROFILE_ENV = f"{ENV_PREFIX}PROFILE"
DEFAULT_PROFILE = "production"
DEFAULT_CALLBACK_PORT = 8400
MAX_CONFIG_BYTES = 64 * 1024

# OIDC scopes are policy, never user input. The API needs no custom scopes; offline_access is requested only for a
# session that will be kept in the OS credential store.
IDENTITY_SCOPES: Final = ("openid", "profile", "email")
OFFLINE_ACCESS_SCOPE: Final = "offline_access"

# Settings a profile may carry, in display order. `profile` itself is chosen, not configured, so it is not one.
PROFILE_FIELDS: Final = (
    "api_base_url",
    "auth0_domain",
    "auth0_audience",
    "auth0_client_id",
    "database_connection",
    "google_connection",
    "callback_port",
    "ca_bundle",
)
_ENV_FIELDS: Final = {f"{ENV_PREFIX}{name.upper()}": name for name in ("profile", *PROFILE_FIELDS)}

# Public values, kept in step with the deployments by tests/cli/test_config.py: production with ServerMode.PROD and
# kustomize/config/compose-api-rke/api.env, local with the compose-api-local overlay's ingress host and auth0.env.
# Neither has a client ID yet: the native applications' public IDs must be published before either can sign in.
BUILTIN_PROFILES: Final[Mapping[str, Mapping[str, str]]] = {
    "production": {
        "api_base_url": "https://compose.cam.uchc.edu",
        "auth0_domain": "dev-bu7yo7484tyxu6a1.us.auth0.com",
        "auth0_audience": "https://api.compose.cam.uchc.edu",
    },
    "local": {
        "api_base_url": "https://api.compose-api-local",
        "auth0_domain": "dev-bu7yo7484tyxu6a1.us.auth0.com",
        "auth0_audience": "https://api.compose.local",
    },
}

_PROFILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
_HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_CLIENT_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
# Auth0's own rule for connection names: letters, digits and inner hyphens, at most 128 characters.
_CONNECTION_NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,126}[A-Za-z0-9])?")
_AUDIENCE = re.compile(r"[\x21-\x7e]{1,600}")  # visible ASCII: no whitespace or control characters
_JWT_SHAPE = re.compile(r"eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]*\.[A-Za-z0-9_-]*")
_SECRET_HINTS: Final = ("secret", "password", "passwd", "token", "credential", "private", "api_key", "apikey")
_LOOPBACK_NAMES: Final = frozenset({"localhost"})


def default_config_path() -> Path:
    return Path(platformdirs.user_config_dir(APP_NAME, appauthor=False)) / "config.toml"


def requested_scopes(*, persistent: bool) -> tuple[str, ...]:
    return (*IDENTITY_SCOPES, OFFLINE_ACCESS_SCOPE) if persistent else IDENTITY_SCOPES


def canonical_api_base_url(raw: str) -> str:
    """The API origin as `scheme://host[:port]`, or ValueError.

    Case and a default port or trailing slash are normalised. Anything that changes where requests go or what they
    carry -- credentials, a path, a query, a fragment, percent-encoding, a non-canonical host -- is rejected instead.
    Plain HTTP is allowed only to a loopback host.
    """
    _require_plain_ascii(raw)
    if "\\" in raw or "%" in raw:
        raise ValueError("must not contain backslashes or percent-encoding")
    parts = _split_url(raw)
    scheme = parts.scheme.lower()
    if scheme not in ("https", "http"):
        raise ValueError("must be an https:// URL")
    if "@" in parts.netloc:
        raise ValueError("must not contain credentials")
    if "?" in raw or "#" in raw:
        raise ValueError("must not have a query or fragment")
    if not parts.hostname:
        raise ValueError("must include a host")
    if parts.path not in ("", "/"):
        raise ValueError("must be the server root, without a path")
    try:
        port = parts.port
    except ValueError:
        raise ValueError("has an invalid port")
    if port == 0:
        raise ValueError("has an invalid port")
    host, loopback = _canonical_host(parts.hostname, bracketed="[" in parts.netloc)
    if scheme == "http" and not loopback:
        raise ValueError("must use https unless it targets a loopback host")
    default_port = 443 if scheme == "https" else 80
    return f"{scheme}://{host}" if port in (None, default_port) else f"{scheme}://{host}:{port}"


def canonical_auth0_domain(raw: str) -> str:
    """The tenant's bare DNS host, lower-cased, or ValueError. The issuer is derived from it, never configured."""
    _require_plain_ascii(raw)
    if "/" in raw or "\\" in raw:
        raise ValueError("must be a bare host such as tenant.us.auth0.com, without a scheme or path")
    if ":" in raw:
        raise ValueError("must not include a port")
    host = raw.lower()
    labels = host.split(".")
    if len(labels) < 2 or not _valid_dns_name(labels):
        raise ValueError("must be a DNS host name such as tenant.us.auth0.com")
    return host


class CliSettings(BaseModel):
    """One resolved, validated profile. Every field is public; `binding_key` names the session it may use."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    profile: str
    api_base_url: str
    auth0_domain: str
    auth0_audience: str
    auth0_client_id: str | None = None
    database_connection: str | None = None
    google_connection: str | None = None
    callback_port: int = DEFAULT_CALLBACK_PORT
    ca_bundle: Path | None = None

    @field_validator("profile")
    @classmethod
    def _check_profile(cls, value: str) -> str:
        return _check_profile_name(value)

    @field_validator("api_base_url")
    @classmethod
    def _check_api_base_url(cls, value: str) -> str:
        return canonical_api_base_url(value)

    @field_validator("auth0_domain")
    @classmethod
    def _check_auth0_domain(cls, value: str) -> str:
        return canonical_auth0_domain(value)

    @field_validator("auth0_audience")
    @classmethod
    def _check_audience(cls, value: str) -> str:
        # Kept byte for byte: it must equal the API identifier exactly, so it is checked but never normalised.
        if not _AUDIENCE.fullmatch(value):
            raise ValueError("must be the exact API identifier, without whitespace or control characters")
        return value

    @field_validator("auth0_client_id")
    @classmethod
    def _check_client_id(cls, value: str | None) -> str | None:
        if value is not None and not _CLIENT_ID.fullmatch(value):
            raise ValueError("must be the native application's public Client ID (letters, digits, '-' and '_')")
        return value

    @field_validator("database_connection", "google_connection")
    @classmethod
    def _check_connection(cls, value: str | None) -> str | None:
        if value is not None and not _CONNECTION_NAME.fullmatch(value):
            raise ValueError("must be an Auth0 connection name (letters, digits and inner hyphens)")
        return value

    @field_validator("callback_port")
    @classmethod
    def _check_callback_port(cls, value: int) -> int:
        if not 1024 <= value <= 65535:
            raise ValueError("must be an unprivileged port (1024-65535) registered as a callback with Auth0")
        return value

    @field_validator("ca_bundle")
    @classmethod
    def _check_ca_bundle(cls, value: Path | None) -> Path | None:
        if value is None:
            return None
        path = value.expanduser()
        if not path.is_absolute():
            raise ValueError("must be an absolute path; the working directory is never consulted")
        if not path.is_file():
            raise ValueError("must name an existing CA certificate file")
        return path

    @property
    def issuer(self) -> str:
        return f"https://{self.auth0_domain}/"

    @property
    def redirect_uri(self) -> str:
        return f"http://127.0.0.1:{self.callback_port}/callback"

    def require_client_id(self) -> str:
        """The public Client ID, or a ConfigError saying where to set it. Every sign-in path needs it."""
        if self.auth0_client_id is None:
            raise ConfigError(
                f"auth0_client_id is not set for profile {self.profile!r}, so this profile cannot sign in: set"
                f" {ENV_PREFIX}AUTH0_CLIENT_ID or add auth0_client_id to [profiles.{self.profile}] in the CLI"
                " config file (`compose-api config show` prints its path)"
            )
        return self.auth0_client_id

    def binding_key(self, *, persistent: bool) -> str:
        """A stable digest of everything a stored session is bound to.

        Two profiles share a session only if they agree on issuer, client, audience, API origin and scopes.
        Changing any of them selects a different, empty session, so a token is never sent to an origin or audience
        it was not obtained for.
        """
        material = {
            "v": 1,
            "issuer": self.issuer,
            "client_id": self.require_client_id(),
            "audience": self.auth0_audience,
            "api_base_url": self.api_base_url,
            "scopes": sorted(set(requested_scopes(persistent=persistent))),
        }
        canonical = json.dumps(material, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True)
class LoadedSettings:
    """Validated settings plus where each value came from, for `config show`."""

    settings: CliSettings
    sources: Mapping[str, str]
    config_path: Path
    config_found: bool

    def public_view(self) -> dict[str, Any]:
        """Every setting with its provenance. Safe to print: profiles cannot hold secrets."""
        settings = self.settings
        values: dict[str, Any] = {}
        for name in PROFILE_FIELDS:
            value = getattr(settings, name)
            values[name] = {"value": str(value) if isinstance(value, Path) else value, "source": self.sources[name]}
        return {
            "profile": {"value": settings.profile, "source": self.sources["profile"]},
            "config_file": {"path": str(self.config_path), "found": self.config_found},
            "settings": values,
            "derived": {"issuer": settings.issuer, "redirect_uri": settings.redirect_uri},
        }


def load_cli_settings(
    profile: str | None = None, *, environ: Mapping[str, str] | None = None, config_path: Path | None = None
) -> LoadedSettings:
    """Resolve and validate one profile. Raises ConfigError before anything touches the network or a browser."""
    environ = os.environ if environ is None else environ
    config_path = default_config_path() if config_path is None else config_path
    env_values = _environment_values(environ)
    name, profile_source = _select_profile(profile, env_values)

    profiles = _read_profiles(config_path)
    table = profiles.get(name) if profiles is not None else None
    if table is None and name not in BUILTIN_PROFILES:
        raise ConfigError(
            f"profile {name!r} ({profile_source}) is not built in ({', '.join(BUILTIN_PROFILES)}) and is not"
            f" defined as [profiles.{name}] in {config_path}"
        )

    values, sources = _resolve_values(name, env_values, table or {})
    sources["profile"] = profile_source
    for field, value in values.items():
        if isinstance(value, str) and _JWT_SHAPE.fullmatch(value):
            raise ConfigError(
                f"{field} ({sources[field]}) looks like a token; tokens never belong in CLI configuration"
            )
    try:
        settings = CliSettings.model_validate({"profile": name, **values})
    except ValidationError as exc:
        raise ConfigError(_describe_validation_error(exc, sources, name, config_path))

    for field in PROFILE_FIELDS:
        sources.setdefault(field, "unset" if getattr(settings, field) is None else "default")
    return LoadedSettings(
        settings=settings, sources=sources, config_path=config_path, config_found=profiles is not None
    )


def _select_profile(flag: str | None, env_values: Mapping[str, str]) -> tuple[str, str]:
    """The profile name and where it came from: --profile, then COMPOSE_API_CLI_PROFILE, then the default."""
    if flag is not None:
        name, source = flag, "--profile"
    elif "profile" in env_values:
        name, source = env_values["profile"], f"env {PROFILE_ENV}"
    else:
        name, source = DEFAULT_PROFILE, "default"
    try:
        return _check_profile_name(name), source
    except ValueError as exc:
        raise ConfigError(f"profile ({source}) {exc}")


def _resolve_values(
    name: str, env_values: Mapping[str, str], table: Mapping[str, object]
) -> tuple[dict[str, object], dict[str, str]]:
    """Each setting that has a value, from the environment, then the profile's table, then the built-in default."""
    builtin = BUILTIN_PROFILES.get(name, {})
    values: dict[str, object] = {}
    sources: dict[str, str] = {}
    for field in PROFILE_FIELDS:
        if field in env_values:
            values[field], sources[field] = env_values[field], f"env {ENV_PREFIX}{field.upper()}"
        elif field in table:
            values[field], sources[field] = table[field], f"file [profiles.{name}]"
        elif field in builtin:
            values[field], sources[field] = builtin[field], "default"
    return values, sources


def _environment_values(environ: Mapping[str, str]) -> dict[str, str]:
    """`COMPOSE_API_CLI_*` variables by field name. An empty variable counts as unset; an unknown one is an error."""
    values: dict[str, str] = {}
    for name, value in environ.items():
        if not name.startswith(ENV_PREFIX):
            continue
        field = _ENV_FIELDS.get(name)
        if field is None:
            raise ConfigError(_unknown_setting(name, "in the environment", known=_ENV_FIELDS))
        if value:
            values[field] = value
    return values


def _read_profiles(path: Path) -> dict[str, dict[str, object]] | None:
    """The `[profiles.*]` tables from the config file, or None when there is no file.

    Every table's keys are checked, not only the selected profile's, so a secret pasted anywhere is refused.
    """
    document = _read_config_document(path)
    if document is None:
        return None
    for key in document:
        if key != "profiles":
            raise ConfigError(_unknown_setting(key, f"at the top level of {path}", known=["profiles"]))
    profiles = document.get("profiles", {})
    if not isinstance(profiles, dict):
        raise ConfigError(f"profiles in {path} must be a table of [profiles.<name>] tables")
    for name, table in profiles.items():
        try:
            _check_profile_name(name)
        except ValueError as exc:
            raise ConfigError(f"a [profiles.*] table name in {path} {exc}")
        if not isinstance(table, dict):
            raise ConfigError(f"profiles.{name} in {path} must be a table")
        for key in table:
            if key not in PROFILE_FIELDS:
                raise ConfigError(_unknown_setting(key, f"in [profiles.{name}] of {path}", known=PROFILE_FIELDS))
    return profiles


def _read_config_document(path: Path) -> dict[str, Any] | None:
    try:
        info = path.stat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc.strerror}")
    if not stat.S_ISREG(info.st_mode):
        raise ConfigError(f"{path} is not a regular file")
    # The file decides where sign-in sends a browser and where tokens go, so only its owner may change it.
    if sys.platform != "win32" and info.st_uid != os.getuid():
        raise ConfigError(f"{path} must be owned by the current user")
    if sys.platform != "win32" and info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise ConfigError(f"{path} must not be writable by group or others (chmod go-w)")
    if info.st_size > MAX_CONFIG_BYTES:
        raise ConfigError(f"{path} is larger than {MAX_CONFIG_BYTES} bytes")
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc.strerror}")
    except UnicodeDecodeError:
        raise ConfigError(f"{path} is not UTF-8 text")
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}")


def _unknown_setting(key: str, where: str, *, known: Iterable[str]) -> str:
    # repr() keeps a hostile key from writing control characters to the terminal.
    if any(hint in key.lower() for hint in _SECRET_HINTS):
        return f"{key!r} {where} looks like a secret; the CLI never reads secrets from its configuration, remove it"
    return f"unknown setting {key!r} {where}; expected one of: {', '.join(known)}"


def _describe_validation_error(exc: ValidationError, sources: Mapping[str, str], profile: str, path: Path) -> str:
    """Each problem by field and source. Pydantic's input echo is left out: a value is never repeated back."""
    problems: list[str] = []
    for error in exc.errors(include_url=False, include_input=False, include_context=False):
        field = str(error["loc"][0]) if error["loc"] else "profile"
        if error["type"] == "missing":
            problems.append(
                f"{field} is not set for profile {profile!r}: set {ENV_PREFIX}{field.upper()} or add it to"
                f" [profiles.{profile}] in {path}"
            )
        else:
            problems.append(f"{field} ({sources.get(field, 'default')}) {error['msg'].removeprefix('Value error, ')}")
    return "invalid CLI configuration:\n  " + "\n  ".join(problems)


def _check_profile_name(name: str) -> str:
    if not _PROFILE_NAME.fullmatch(name):
        raise ValueError("must be 1-64 letters, digits, '-' or '_', starting with a letter or digit")
    return name


def _require_plain_ascii(raw: str) -> None:
    if not raw.isascii():
        raise ValueError("must be ASCII; write an internationalised host in its xn-- form")
    if any(char.isspace() or not char.isprintable() for char in raw):
        raise ValueError("must not contain whitespace or control characters")


def _split_url(raw: str) -> SplitResult:
    try:
        return urlsplit(raw)
    except ValueError:
        raise ValueError("is not a valid URL")


def _canonical_host(host: str, *, bracketed: bool) -> tuple[str, bool]:
    """A canonical host for a URL and whether it is loopback. `host` is urlsplit's lower-cased, unbracketed form."""
    if bracketed or ":" in host:
        try:
            address = ipaddress.IPv6Address(host)
        except ValueError:
            raise ValueError("has an invalid IPv6 address")
        return f"[{address.compressed}]", address.is_loopback
    try:
        ipv4 = ipaddress.IPv4Address(host)
    except ValueError:
        pass
    else:
        return str(ipv4), ipv4.is_loopback
    if not _valid_dns_name(host.split(".")):
        raise ValueError("must have a canonical host name (letters, digits, inner hyphens; no trailing dot)")
    return host, host in _LOOPBACK_NAMES


def _valid_dns_name(labels: list[str]) -> bool:
    # An all-numeric last label is an IP address in a form (127.1, 0x7f.0.0.1, 010.0.0.1) that resolvers disagree on.
    return (
        len(".".join(labels)) <= 253
        and all(_HOST_LABEL.fullmatch(label) for label in labels)
        and not labels[-1].isdigit()
    )
