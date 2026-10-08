"""Public auth profiles for the CLI. No secrets, no server settings, no credential store.

Precedence for each field is the command-line flag, then the environment, then the named profile in the user
config file, then the built-in profile. ``COMPOSE_API_TOKEN`` is not a profile field: a manual token is for one
invocation and is never stored or mixed into this tuple.

Importing this module does not read the config file, open a credential store, or import ``compose_api``.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import os
import re
import stat
import sys
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final
from urllib.parse import SplitResult, urlsplit

import platformdirs

APP_NAME = "compose-api"
DEFAULT_PROFILE = "production"
DEFAULT_SCOPES: Final = ("openid", "profile", "email", "offline_access")
DEFAULT_CALLBACK_PORTS: Final = (51111, 52111, 53111)
DEFAULT_LOGIN_DEADLINE = 180.0
DEFAULT_NETWORK_TIMEOUT = 10.0
MAX_CONFIG_BYTES = 64 * 1024

ENV_PROFILE = "COMPOSE_API_PROFILE"
ENV_URL = "COMPOSE_API_URL"
ENV_ISSUER = "COMPOSE_API_AUTH0_ISSUER"
ENV_CLIENT_ID = "COMPOSE_API_AUTH0_CLIENT_ID"
ENV_AUDIENCE = "COMPOSE_API_AUTH0_AUDIENCE"
ENV_SCOPES = "COMPOSE_API_AUTH0_SCOPES"
ENV_CALLBACK_PORTS = "COMPOSE_API_AUTH0_CALLBACK_PORTS"
ENV_LOGIN_DEADLINE = "COMPOSE_API_AUTH0_LOGIN_DEADLINE"
ENV_NETWORK_TIMEOUT = "COMPOSE_API_AUTH0_NETWORK_TIMEOUT"

# Public native-client identifiers from the compose-api Auth0 stack (pulumi stack output cli_profiles).
# A native client ID is not a secret. Callback ports match the stack's registered loopback URLs.
PRODUCTION_CLIENT_ID = "1FV43fysEjhTrYYRNaMEGvCteu4g2ay4"
LOCAL_CLIENT_ID = "Fp3QmULWNIhdutlBRVFm2HjPGapqdnKV"
AUTH0_ISSUER = "https://dev-bu7yo7484tyxu6a1.us.auth0.com/"

_RANK_DEFAULT = 0
_RANK_FILE = 1
_RANK_ENV = 2
_RANK_FLAG = 3

_PROFILE_FIELDS: Final = (
    "issuer",
    "client_id",
    "audience",
    "api_base_url",
    "scopes",
    "callback_ports",
    "login_deadline",
    "network_timeout",
)
_ENV_OF: Final = {
    "api_base_url": ENV_URL,
    "issuer": ENV_ISSUER,
    "client_id": ENV_CLIENT_ID,
    "audience": ENV_AUDIENCE,
    "scopes": ENV_SCOPES,
    "callback_ports": ENV_CALLBACK_PORTS,
    "login_deadline": ENV_LOGIN_DEADLINE,
    "network_timeout": ENV_NETWORK_TIMEOUT,
}
_KNOWN_AUTH0_ENV: Final = frozenset(name for name in _ENV_OF.values() if name.startswith("COMPOSE_API_AUTH0_")) | {
    ENV_PROFILE
}
_REQUIRED: Final = ("issuer", "client_id", "audience", "api_base_url")
_BINDING_FIELDS: Final = ("issuer", "client_id", "audience")
_SECRET_HINTS: Final = ("secret", "password", "passwd", "token", "credential", "private", "api_key", "apikey")
_FALLBACK: Final[Mapping[str, object]] = {
    "scopes": " ".join(DEFAULT_SCOPES),
    "callback_ports": ",".join(str(port) for port in DEFAULT_CALLBACK_PORTS),
    "login_deadline": DEFAULT_LOGIN_DEADLINE,
    "network_timeout": DEFAULT_NETWORK_TIMEOUT,
}
_BUILTINS: Final[Mapping[str, Mapping[str, str]]] = {
    "production": {
        "issuer": AUTH0_ISSUER,
        "client_id": PRODUCTION_CLIENT_ID,
        "audience": "https://api.compose.cam.uchc.edu",
        "api_base_url": "https://compose.cam.uchc.edu",
    },
    "local": {
        "issuer": AUTH0_ISSUER,
        "client_id": LOCAL_CLIENT_ID,
        "audience": "https://api.compose.local",
        "api_base_url": "https://api.compose-api-local",
    },
}

_PROFILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
_HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_CLIENT_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
_SCOPE = re.compile(r"[A-Za-z0-9_.:/-]{1,128}")
_JWT_SHAPE = re.compile(r"eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
_LOOPBACK_NAMES: Final = frozenset({"localhost"})


class ConfigError(Exception):
    """The public auth profile is missing or inconsistent. The message never includes a token."""


@dataclass(frozen=True, slots=True)
class AuthOverrides:
    """Command-line values only. Unset fields are None so the environment and profile can still apply."""

    profile: str | None = None
    api_base_url: str | None = None
    issuer: str | None = None
    client_id: str | None = None
    audience: str | None = None
    scopes: str | None = None
    callback_ports: str | None = None
    login_deadline: str | None = None
    network_timeout: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedAuth:
    """One validated profile. ``binding_key`` is what a stored session must match before it is reused."""

    name: str
    issuer: str
    client_id: str
    audience: str
    api_base_url: str
    scopes: frozenset[str]
    callback_ports: tuple[int, ...]
    login_deadline: float
    network_timeout: float
    sources: Mapping[str, str]

    def binding_material(self) -> tuple[str, str, str, str, str]:
        """Normalized issuer, client ID, audience, API URL (path included), and sorted scopes."""
        return (self.issuer, self.client_id, self.audience, self.api_base_url, " ".join(sorted(self.scopes)))

    def binding_key(self) -> str:
        payload = json.dumps(self.binding_material(), separators=(",", ":"))
        return hashlib.sha256(payload.encode("ascii")).hexdigest()

    def jwks_url(self) -> str:
        """JWKS for this profile's configured issuer. Never a token ``jku`` or ``iss`` claim."""
        return f"{self.issuer}.well-known/jwks.json"

    def callback_urls(self) -> tuple[str, ...]:
        return tuple(f"http://127.0.0.1:{port}/callback" for port in self.callback_ports)


def default_config_path() -> Path:
    return Path(platformdirs.user_config_dir(APP_NAME, appauthor=False)) / "config.toml"


def resolve_auth_profile(
    overrides: AuthOverrides | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    config_path: Path | None = None,
) -> ResolvedAuth:
    """Resolve and validate one profile. Raises ConfigError before any network call or credential store."""
    chosen = overrides or AuthOverrides()
    env = os.environ if environ is None else environ
    path = default_config_path() if config_path is None else config_path
    _reject_unknown_auth_env(env)
    name, name_source = _select_profile(chosen, env)
    profiles = _read_profiles(path)
    if name not in _BUILTINS and name not in profiles:
        raise ConfigError(
            f"profile {name!r} ({name_source}) is not built in ({', '.join(_BUILTINS)}) and is not defined as"
            f" [profiles.{name}] in {path}"
        )
    table = profiles.get(name, {})
    builtin = _BUILTINS.get(name, {})
    flags = _flag_values(chosen)
    picked = {field: _pick(field, flags, env, table, builtin, name) for field in _PROFILE_FIELDS}
    _reject_tokens(picked)
    fields = _normalize(picked)
    _reject_split_api(fields.api_base_url, _paired_api_url(table, builtin), picked)
    sources = MappingProxyType({"profile": name_source, **{field: item[2] for field, item in picked.items()}})
    return ResolvedAuth(
        name=name,
        issuer=fields.issuer,
        client_id=fields.client_id,
        audience=fields.audience,
        api_base_url=fields.api_base_url,
        scopes=fields.scopes,
        callback_ports=fields.callback_ports,
        login_deadline=fields.login_deadline,
        network_timeout=fields.network_timeout,
        sources=sources,
    )


@dataclass(frozen=True, slots=True)
class _Fields:
    issuer: str
    client_id: str
    audience: str
    api_base_url: str
    scopes: frozenset[str]
    callback_ports: tuple[int, ...]
    login_deadline: float
    network_timeout: float


def canonical_api_base_url(raw: str) -> str:
    """``scheme://host[:port][/path]``. The path prefix is kept, so it distinguishes stored sessions.

    Host case and a default port are normalized. Lookalike hosts are not folded together: ``compose.example`` and
    ``compose.example.evil`` stay different, and short or padded IP forms are rejected rather than rewritten.
    """
    parsed = _parse_url(raw, http_loopback_only=True)
    if parsed.scheme == "http" and not parsed.loopback:
        raise ConfigError("api_base_url must use https unless it targets a loopback host")
    return _render_url(parsed)


def canonical_issuer(raw: str) -> str:
    """The issuer URL, always ``https://host/``. JWKS and discovery are derived from this, not from a token."""
    parsed = _parse_url(raw, http_loopback_only=False)
    if parsed.scheme != "https":
        raise ConfigError("issuer must be an https URL")
    if parsed.path:
        raise ConfigError("issuer must not have a path, query, or fragment")
    return f"https://{parsed.authority}/"


@dataclass(frozen=True, slots=True)
class _Url:
    scheme: str
    authority: str
    path: str
    loopback: bool


def _parse_url(raw: str, *, http_loopback_only: bool) -> _Url:
    _require_plain(raw, "url")
    if "\\" in raw or "%" in raw:
        raise ConfigError("url must not contain backslashes or percent-encoding")
    if "@" in raw:
        raise ConfigError("url must not contain credentials")
    if "?" in raw or "#" in raw:
        raise ConfigError("url must not have a query or fragment")
    parts = _split_url(raw)
    scheme = parts.scheme.lower()
    if scheme not in ("https", "http"):
        raise ConfigError("url must be https, or http to a loopback host")
    if not http_loopback_only and scheme != "https":
        raise ConfigError("issuer must be an https URL")
    host, loopback = _canonical_host(parts)
    path = _canonical_path(parts.path)
    port = _port(parts, scheme)
    default_port = 443 if scheme == "https" else 80
    authority = host if port in (None, default_port) else f"{host}:{port}"
    return _Url(scheme=scheme, authority=authority, path=path, loopback=loopback)


def _render_url(parsed: _Url) -> str:
    return f"{parsed.scheme}://{parsed.authority}{parsed.path}"


def _split_url(raw: str) -> SplitResult:
    try:
        return urlsplit(raw)
    except ValueError:
        raise ConfigError("url is not a valid URL") from None


def _port(parts: SplitResult, scheme: str) -> int | None:
    try:
        port = parts.port
    except ValueError:
        raise ConfigError("url has an invalid port") from None
    if port == 0:
        raise ConfigError("url has an invalid port")
    return port if port is not None else (443 if scheme == "https" else None)


def _canonical_host(parts: SplitResult) -> tuple[str, bool]:
    host = parts.hostname or ""
    if not host:
        raise ConfigError("url must include a host")
    if host.endswith("."):
        raise ConfigError("url host must not have a trailing dot")
    if "[" in parts.netloc or ":" in host:
        return _ipv6_host(host)
    ipv4 = _ipv4_host(host)
    if ipv4 is not None:
        address = ipaddress.IPv4Address(ipv4)
        return str(address), address.is_loopback
    labels = host.lower().split(".")
    if not _dns_labels(labels):
        raise ConfigError("url host must be a DNS name or a canonical IP address")
    return ".".join(labels), ".".join(labels) in _LOOPBACK_NAMES


def _ipv6_host(host: str) -> tuple[str, bool]:
    try:
        address = ipaddress.IPv6Address(host)
    except ValueError:
        raise ConfigError("url has an invalid IPv6 address") from None
    return f"[{address.compressed}]", address.is_loopback


def _ipv4_host(host: str) -> str | None:
    parts = host.split(".")
    if len(parts) != 4 or not all(part.isdigit() for part in parts):
        return None
    numbers: list[str] = []
    for part in parts:
        if part != "0" and part.startswith("0"):
            raise ConfigError("url must not use leading zeros in an IPv4 address")
        number = int(part)
        if number > 255:
            raise ConfigError("url has an invalid IPv4 address")
        numbers.append(str(number))
    return ".".join(numbers)


def _dns_labels(labels: list[str]) -> bool:
    return (
        len(".".join(labels)) <= 253
        and all(_HOST_LABEL.fullmatch(label) for label in labels)
        and not labels[-1].isdigit()
    )


def _canonical_path(path: str) -> str:
    if path in ("", "/"):
        return ""
    if path.endswith("/"):
        path = path[:-1]
    segments = path.split("/")
    if segments[0] != "" or any(part in ("", ".", "..") for part in segments[1:]):
        raise ConfigError("url path must not contain empty, '.' or '..' segments")
    return "/" + "/".join(segments[1:])


def _require_plain(raw: str, field: str) -> None:
    if not raw.isascii() or any(char.isspace() or not char.isprintable() for char in raw):
        raise ConfigError(f"{field} must be printable ASCII, with an internationalised host in xn-- form")


def _select_profile(overrides: AuthOverrides, env: Mapping[str, str]) -> tuple[str, str]:
    flag = (overrides.profile or "").strip()
    if flag:
        return _profile_name(flag), "flag"
    raw = env.get(ENV_PROFILE, "").strip()
    if raw:
        return _profile_name(raw), f"env {ENV_PROFILE}"
    return DEFAULT_PROFILE, "default"


def _profile_name(name: str) -> str:
    if not _PROFILE_NAME.fullmatch(name):
        raise ConfigError("profile must be 1-64 letters, digits, '-' or '_', starting with a letter or digit")
    return name


def _flag_values(overrides: AuthOverrides) -> dict[str, str]:
    raw = {
        "profile": overrides.profile,
        "api_base_url": overrides.api_base_url,
        "issuer": overrides.issuer,
        "client_id": overrides.client_id,
        "audience": overrides.audience,
        "scopes": overrides.scopes,
        "callback_ports": overrides.callback_ports,
        "login_deadline": overrides.login_deadline,
        "network_timeout": overrides.network_timeout,
    }
    return {key: value.strip() for key, value in raw.items() if isinstance(value, str) and value.strip()}


def _pick(
    field: str,
    flags: Mapping[str, str],
    env: Mapping[str, str],
    table: Mapping[str, object],
    builtin: Mapping[str, str],
    profile: str,
) -> tuple[object, int, str]:
    if field in flags:
        return flags[field], _RANK_FLAG, "flag"
    env_name = _ENV_OF[field]
    env_value = env.get(env_name, "").strip()
    if env_value:
        return env_value, _RANK_ENV, f"env {env_name}"
    if field in table:
        return table[field], _RANK_FILE, f"file [profiles.{profile}]"
    if field in builtin:
        return builtin[field], _RANK_DEFAULT, "default"
    if field in _FALLBACK:
        return _FALLBACK[field], _RANK_DEFAULT, "default"
    raise ConfigError(
        f"{field} is not set for profile {profile!r}: set {_ENV_OF[field]} or add it to [profiles.{profile}]"
    )


def _reject_unknown_auth_env(env: Mapping[str, str]) -> None:
    unknown = sorted(name for name in env if name.startswith("COMPOSE_API_AUTH0_") and name not in _KNOWN_AUTH0_ENV)
    if unknown:
        raise ConfigError(f"unknown environment variable {unknown[0]!r}")


def _reject_tokens(picked: Mapping[str, tuple[object, int, str]]) -> None:
    for field, (value, _rank, source) in picked.items():
        if isinstance(value, str) and _JWT_SHAPE.fullmatch(value.strip()):
            raise ConfigError(f"{field} ({source}) looks like a token; tokens never belong in CLI configuration")


def _normalize(picked: Mapping[str, tuple[object, int, str]]) -> _Fields:
    return _Fields(
        issuer=canonical_issuer(_text(picked, "issuer")),
        client_id=_client_id(_text(picked, "client_id"), picked["client_id"][2]),
        audience=_audience(_text(picked, "audience")),
        api_base_url=canonical_api_base_url(_text(picked, "api_base_url")),
        scopes=_scopes(picked["scopes"][0], picked["scopes"][2]),
        callback_ports=_ports(picked["callback_ports"][0], picked["callback_ports"][2]),
        login_deadline=_seconds(picked["login_deadline"][0], "login_deadline"),
        network_timeout=_seconds(picked["network_timeout"][0], "network_timeout"),
    )


def _text(picked: Mapping[str, tuple[object, int, str]], field: str) -> str:
    value = picked[field][0]
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field} ({picked[field][2]}) must be a string")
    return value.strip()


def _client_id(value: str, source: str) -> str:
    if not _CLIENT_ID.fullmatch(value):
        raise ConfigError(f"client_id ({source}) must be the native application's public client ID")
    return value


def _audience(value: str) -> str:
    _require_plain(value, "audience")
    if "@" in value or not value:
        raise ConfigError("audience must be the API identifier, without credentials or whitespace")
    return value


def _scopes(value: object, source: str) -> frozenset[str]:
    if isinstance(value, str):
        tokens = [part for part in re.split(r"[\s,]+", value.strip()) if part]
    elif isinstance(value, list):
        tokens = [part.strip() for part in value if isinstance(part, str) and part.strip()]
        if len(tokens) != len(value):
            raise ConfigError(f"scopes ({source}) must be a list of strings")
    else:
        raise ConfigError(f"scopes ({source}) must be a list of strings")
    if not tokens or any(_SCOPE.fullmatch(token) is None for token in tokens):
        raise ConfigError(f"scopes ({source}) must be OIDC scope tokens")
    return frozenset(tokens)


def _ports(value: object, source: str) -> tuple[int, ...]:
    parts: list[object]
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",") if part.strip()]
    elif isinstance(value, list):
        parts = list(value)
    else:
        raise ConfigError(f"callback_ports ({source}) must be a list of ports")
    ports: list[int] = []
    for part in parts:
        if isinstance(part, bool) or not isinstance(part, (int, str)):
            raise ConfigError(f"callback_ports ({source}) must be a list of ports")
        try:
            port = int(part)
        except ValueError:
            raise ConfigError(f"callback_ports ({source}) must be a list of ports") from None
        if not 1024 <= port <= 65535:
            raise ConfigError(f"callback_ports ({source}) must be unprivileged ports (1024-65535)")
        ports.append(port)
    if not ports or len(ports) != len(set(ports)):
        raise ConfigError(f"callback_ports ({source}) must list at least one distinct port")
    return tuple(ports)


def _seconds(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ConfigError(f"{field} must be a positive number of seconds")
    try:
        number = float(value)
    except ValueError:
        raise ConfigError(f"{field} must be a positive number of seconds") from None
    if not math.isfinite(number) or number <= 0:
        raise ConfigError(f"{field} must be a positive finite number of seconds")
    return number


def _paired_api_url(table: Mapping[str, object], builtin: Mapping[str, str]) -> str | None:
    raw = table.get("api_base_url", builtin.get("api_base_url"))
    if not isinstance(raw, str) or not raw.strip():
        return None
    return canonical_api_base_url(raw.strip())


def _reject_split_api(
    api_base_url: str,
    paired_url: str | None,
    picked: Mapping[str, tuple[object, int, str]],
) -> None:
    if api_base_url == paired_url:
        return
    url_rank = picked["api_base_url"][1]
    inherited = [field for field in _BINDING_FIELDS if picked[field][1] < url_rank]
    if not inherited:
        return
    detail = ", ".join(f"{field} ({picked[field][2]})" for field in inherited)
    other = paired_url or "unset"
    raise ConfigError(
        f"api_base_url ({picked['api_base_url'][2]}) selects {api_base_url}, which is not {other};"
        f" {detail} would be reused for that other API. Override the issuer, client ID, and audience together"
        " with the URL, or select the profile that already matches it."
    )


def _read_profiles(path: Path) -> dict[str, dict[str, object]]:
    document = _read_document(path)
    if document is None:
        return {}
    for key in document:
        if key != "profiles":
            raise ConfigError(_unknown_key(str(key), f"at the top level of {path}", known=["profiles"]))
    profiles = document.get("profiles", {})
    if not isinstance(profiles, dict):
        raise ConfigError(f"profiles in {path} must be a table of [profiles.<name>] tables")
    checked: dict[str, dict[str, object]] = {}
    for name, table in profiles.items():
        profile = _profile_name(str(name))
        if not isinstance(table, dict):
            raise ConfigError(f"profiles.{profile} in {path} must be a table")
        for key, value in table.items():
            if key not in _PROFILE_FIELDS:
                raise ConfigError(_unknown_key(str(key), f"in [profiles.{profile}] of {path}", known=_PROFILE_FIELDS))
            if isinstance(value, str) and _JWT_SHAPE.fullmatch(value.strip()):
                raise ConfigError(f"{key} in [profiles.{profile}] looks like a token; remove it")
        checked[profile] = dict(table)
    return checked


def _read_document(path: Path) -> dict[str, object] | None:
    info = _config_stat(path)
    if info is None:
        return None
    _require_private_file(path, info)
    return _parse_config(path)


def _config_stat(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc.strerror}") from exc


def _require_private_file(path: Path, info: os.stat_result) -> None:
    if stat.S_ISLNK(info.st_mode):
        raise ConfigError(f"{path} must not be a symlink")
    if not stat.S_ISREG(info.st_mode):
        raise ConfigError(f"{path} is not a regular file")
    if sys.platform != "win32" and info.st_uid != os.getuid():
        raise ConfigError(f"{path} must be owned by the current user")
    if sys.platform != "win32" and info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise ConfigError(f"{path} must not be writable by group or others")
    if info.st_size > MAX_CONFIG_BYTES:
        raise ConfigError(f"{path} is larger than {MAX_CONFIG_BYTES} bytes")


def _parse_config(path: Path) -> dict[str, object]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc.strerror}") from exc
    except UnicodeDecodeError:
        raise ConfigError(f"{path} is not UTF-8 text") from None
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from exc
    if not isinstance(document, dict):
        raise ConfigError(f"{path} must be a TOML table")
    return document


def _unknown_key(key: str, where: str, *, known: Iterable[str]) -> str:
    names = ", ".join(known)
    if any(hint in key.lower() for hint in _SECRET_HINTS):
        return f"{key!r} {where} looks like a secret; the CLI never reads secrets from its configuration, remove it"
    return f"unknown setting {key!r} {where}; expected one of: {names}"
