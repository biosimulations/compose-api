"""Check a submitted composite against the registry before it reaches the cluster (goal G6).

The container resolves process addresses itself, and will import any module it is told to, so this is the only
place a submission is checked. It reads every composite document in the upload -- in an OMEX archive, including
archives nested in a batch bundle -- and checks every process address against the manifest.
"""

import enum
import io
import json
import logging
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from compose_api.registry.manifest import HPC_MINIMUM_LEVEL, SERVICE_BUNDLE, Manifest, load_manifest
from compose_api.simulation.models import SimulationFileType

logger = logging.getLogger(__name__)

_DOCUMENT_SUFFIXES = (".pbg", ".json")
_NESTED_ARCHIVE_SUFFIX = ".omex"
# A bundle nests archives one level deep; anything deeper is not something a client produces.
_MAX_NESTING = 3


class AddressPolicy(enum.StrEnum):
    ENFORCE = "enforce"
    WARN = "warn"


class AddressViolation(BaseModel):
    document: str
    address: str
    reason: str
    # Rejected under every policy, because the container would do something unsafe with it.
    always_rejected: bool = False


class SubmissionRejectedError(Exception):
    def __init__(self, message: str, violations: list[AddressViolation] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.violations = violations or []


def _documents_in_archive(data: bytes, name: str, depth: int = 0) -> Iterator[tuple[str, Any]]:
    if depth > _MAX_NESTING:
        raise SubmissionRejectedError(f"{name}: archives are nested more than {_MAX_NESTING} deep")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise SubmissionRejectedError(f"{name} is not a valid OMEX (zip) archive") from e
    with archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            member_name = f"{name}/{member.filename}"
            lowered = member.filename.lower()
            if lowered.endswith(_DOCUMENT_SUFFIXES):
                yield member_name, _parse_document(archive.read(member), member_name)
            elif lowered.endswith(_NESTED_ARCHIVE_SUFFIX):
                yield from _documents_in_archive(archive.read(member), member_name, depth + 1)


def _parse_document(data: bytes, name: str) -> Any:
    try:
        return json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise SubmissionRejectedError(f"{name} is not a valid JSON composite document") from e


def _addresses(node: Any) -> Iterator[Any]:
    """Every process address in a document, in string or {protocol, data} form.

    A dict under an `address` key without a `protocol` is a type declaration, such as a quoted default, not an
    address the container will resolve, so it is not collected.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "address" and (isinstance(value, str) or (isinstance(value, dict) and "protocol" in value)):
                yield value
            else:
                yield from _addresses(value)
    elif isinstance(node, list):
        for item in node:
            yield from _addresses(item)


def _split_address(address: Any) -> tuple[str, str | None]:
    """(protocol, target) for an address in string or {protocol, data} form; a bare string defaults to `local`."""
    if isinstance(address, dict):
        target = address.get("data")
        return str(address.get("protocol")), target if isinstance(target, str) else None
    if ":" in address:
        protocol, target = address.split(":", 1)
        return protocol, target
    return "local", address


def _unsafe_reason(protocol: str, target: str | None) -> str | None:
    """Why the container would do something unsafe with this address, if it would."""
    if protocol != "local":
        return f"protocol `{protocol}` is not accepted; only `local` runs on the service"
    if target is None:
        return "address data must be a string naming a registered class"
    if target.startswith("!"):
        return "the `local:!` form imports arbitrary modules and is never accepted"
    return None


def _registry_reason(target: str, manifest: Manifest) -> str | None:
    """Why the registry does not allow this class on the service, if it does not."""
    module, _, class_name = target.rpartition(".")
    if not module or not class_name:
        return "short names are ambiguous across packages; use the qualified form `local:<module>.<Class>`"
    entry = manifest.entry_for_module(module)
    if entry is None:
        return f"module `{module}` is not provided by any registered simulator"
    if not entry.level.at_least(HPC_MINIMUM_LEVEL):
        return (
            f"registry entry `{entry.id}` is at level `{entry.level}`; the service runs `{HPC_MINIMUM_LEVEL}` or higher"
        )
    if SERVICE_BUNDLE not in entry.bundles:
        return f"registry entry `{entry.id}` is not installed in the service image `{SERVICE_BUNDLE}`"
    return None


def check_address(address: Any, document: str, manifest: Manifest) -> AddressViolation | None:
    protocol, target = _split_address(address)
    unsafe = _unsafe_reason(protocol, target)
    if unsafe is not None or target is None:
        reason = unsafe or "address data must be a string naming a registered class"
        return AddressViolation(document=document, address=str(address), reason=reason, always_rejected=True)
    refused = _registry_reason(target, manifest)
    if refused is not None:
        return AddressViolation(document=document, address=str(address), reason=refused)
    return None


def find_violations(path: Path, file_type: SimulationFileType, manifest: Manifest) -> list[AddressViolation]:
    """Check every address in a submitted file. Raises SubmissionRejectedError if the file cannot be read."""
    data = path.read_bytes()
    match file_type:
        case SimulationFileType.OMEX:
            documents = list(_documents_in_archive(data, path.name))
            if not documents:
                raise SubmissionRejectedError(f"{path.name} contains no composite document (.pbg or .json)")
        case SimulationFileType.PBG:
            documents = [(path.name, _parse_document(data, path.name))]
        case SimulationFileType.SBML:
            # A bare model carries no process addresses; the service chooses the simulator.
            return []
    return [
        violation
        for name, document in documents
        for address in _addresses(document)
        if (violation := check_address(address, name, manifest)) is not None
    ]


def validate_submission(path: Path, file_type: SimulationFileType, policy: AddressPolicy) -> list[AddressViolation]:
    """Raise SubmissionRejectedError if the submission may not run; return any violations tolerated under `warn`."""
    violations = find_violations(path, file_type, load_manifest())
    if not violations:
        return []
    blocking = violations if policy == AddressPolicy.ENFORCE else [v for v in violations if v.always_rejected]
    if blocking:
        raise SubmissionRejectedError("the composite names processes this service will not run", blocking)
    for v in violations:
        logger.warning("Accepted under address_policy=warn: %s in %s: %s", v.address, v.document, v.reason)
    return violations
