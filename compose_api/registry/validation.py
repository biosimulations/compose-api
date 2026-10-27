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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from compose_api.registry.manifest import HPC_MINIMUM_LEVEL, SERVICE_BUNDLE, Manifest, RegistryEntry, load_manifest
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


@dataclass(frozen=True)
class Standing:
    """What the version a run will use says about its components (docs/plan-environment-composition.md, step 5c):
    its members (a composed version's entries; None for another, whose bundle decides), each entry's computed level
    there (tested, failed, pending, untested), and the components a generic check refused there, with why."""

    label: str
    members: frozenset[str] | None = None
    levels: dict[str, str] = field(default_factory=dict)
    refused: dict[str, str] = field(default_factory=dict)


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


def _registry_reason(
    target: str, manifest: Manifest, standing: Standing | None = None, environment: str = SERVICE_BUNDLE
) -> str | None:
    """Why the registry does not allow this class on the service, if it does not. With the ``standing`` of the version
    the run will use, that version decides first: a component a generic check refused there is refused alone; an
    entry that failed its cases there is refused, one that passed them is accepted; otherwise the manifest's level
    stands (an entry with no cases yet, or whose cases are still running)."""
    module, _, class_name = target.rpartition(".")
    if not module or not class_name:
        return "short names are ambiguous across packages; use the qualified form `local:<module>.<Class>`"
    entry = manifest.entry_for_module(module)
    if entry is None:
        return f"module `{module}` is not provided by any registered simulator"
    if entry.kind == "core":
        return _core_reason(entry, standing, environment)
    return _component_reason(entry, target, standing, environment)


def _level_reason(entry: RegistryEntry) -> str | None:
    if not entry.level.at_least(HPC_MINIMUM_LEVEL):
        return (
            f"registry entry `{entry.id}` is at level `{entry.level}`; the service runs `{HPC_MINIMUM_LEVEL}` or higher"
        )
    return None


def _component_reason(entry: RegistryEntry, target: str, standing: Standing | None, environment: str) -> str | None:
    """Why a component's (or library's) class is not allowed in the version the run will use, if it is not."""
    if standing is not None:
        if target in standing.refused:
            return f"`{target}` is refused in {standing.label}: {standing.refused[target]}"
        if standing.members is not None and entry.id not in standing.members:
            return f"registry entry `{entry.id}` is not part of {standing.label}"
        level = standing.levels.get(entry.id)
        if level == "failed":
            return f"registry entry `{entry.id}` failed its compliance cases in {standing.label}"
        if level == "tested":
            return None
    level_reason = _level_reason(entry)
    if level_reason is not None:
        return level_reason
    # the environment the run will use provides it (D7.10): a composed version's members decide above; otherwise its
    # bundle does
    if (standing is None or standing.members is None) and environment not in entry.bundles:
        return f"registry entry `{entry.id}` is not installed in the environment `{environment}`"
    return None


def _core_reason(entry: RegistryEntry, standing: Standing | None, environment: str) -> str | None:
    """Why a core entry's class is not allowed here, if it is not: every composed version installs the core (a
    standing with members), and a prebuilt image provides it when its environment is among the entry's bundles."""
    level_reason = _level_reason(entry)
    if level_reason is not None:
        return level_reason
    if (standing is not None and standing.members is not None) or environment in entry.bundles:
        return None
    where = standing.label if standing is not None else f"the environment `{environment}`"
    return f"registry entry `{entry.id}` is provided by composed versions, and {where} is not one"


def check_address(
    address: Any,
    document: str,
    manifest: Manifest,
    standing: Standing | None = None,
    environment: str = SERVICE_BUNDLE,
) -> AddressViolation | None:
    protocol, target = _split_address(address)
    unsafe = _unsafe_reason(protocol, target)
    if unsafe is not None or target is None:
        reason = unsafe or "address data must be a string naming a registered class"
        return AddressViolation(document=document, address=str(address), reason=reason, always_rejected=True)
    refused = _registry_reason(target, manifest, standing, environment)
    if refused is not None:
        return AddressViolation(document=document, address=str(address), reason=refused)
    return None


def _documents(path: Path, file_type: SimulationFileType) -> list[tuple[str, Any]]:
    """Every composite document in a submitted file, by name. Raises SubmissionRejectedError if it cannot be read."""
    data = path.read_bytes()
    match file_type:
        case SimulationFileType.OMEX:
            documents = list(_documents_in_archive(data, path.name))
            if not documents:
                raise SubmissionRejectedError(f"{path.name} contains no composite document (.pbg or .json)")
            return documents
        case SimulationFileType.PBG:
            return [(path.name, _parse_document(data, path.name))]
        case SimulationFileType.SBML:
            # A bare model carries no process addresses; the service chooses the simulator.
            return []


def class_targets(path: Path, file_type: SimulationFileType) -> list[str]:
    """The `<module>.<Class>` every safe `local:` address in a submitted file names, which is what an environment is
    inferred from (docs/plan-environment-composition.md, D7.2); the unsafe forms are `check_address`'s to refuse."""
    targets = []
    for _, document in _documents(path, file_type):
        for address in _addresses(document):
            protocol, target = _split_address(address)
            if _unsafe_reason(protocol, target) is None and target is not None:
                targets.append(target)
    return targets


def find_violations(
    path: Path,
    file_type: SimulationFileType,
    manifest: Manifest,
    standing: Standing | None = None,
    environment: str = SERVICE_BUNDLE,
) -> list[AddressViolation]:
    """Check every address in a submitted file against what ``environment`` provides. Raises SubmissionRejectedError
    if the file cannot be read."""
    return [
        violation
        for name, document in _documents(path, file_type)
        for address in _addresses(document)
        if (violation := check_address(address, name, manifest, standing, environment)) is not None
    ]


def validate_submission(
    path: Path,
    file_type: SimulationFileType,
    policy: AddressPolicy,
    *,
    registry: bool = True,
    standing: Standing | None = None,
    environment: str = SERVICE_BUNDLE,
) -> list[AddressViolation]:
    """Raise SubmissionRejectedError if the submission may not run; return any violations tolerated under `warn`.

    ``standing`` is what the version the run will use says about its components (step 5c; ``admission.standing``).

    `registry=False` is for a prebuilt simulator's image, which brings processes this registry does not describe:
    only the addresses the container would do something unsafe with (`local:!`, any other protocol) are refused.
    """
    violations = find_violations(path, file_type, load_manifest(), standing, environment)
    if not registry:
        violations = [v for v in violations if v.always_rejected]
    if not violations:
        return []
    blocking = violations if policy == AddressPolicy.ENFORCE else [v for v in violations if v.always_rejected]
    if blocking:
        raise SubmissionRejectedError("the composite names processes this service will not run", blocking)
    for v in violations:
        logger.warning("Accepted under address_policy=warn: %s in %s: %s", v.address, v.document, v.reason)
    return violations
