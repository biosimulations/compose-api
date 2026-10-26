"""An environment's interfaces as `.pblang` header files: what an author imports (`import module.{Name};`) and what
the checker resolves a composite against. process-bigraph-lang's CLI prints them from the environment's manifest, in
its own environment (`settings.pblang_python`, as SED-ML translation does); the text is cached per manifest."""

import asyncio
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from compose_api.sedml.translator import pblang_python

# `headers <manifest> -o <dir>` writes one `<module>.pbl` per module
_HEADERS = (
    "import sys; from process_bigraph_lang.v2.langium import run_cli; "
    "run_cli('headers', sys.argv[1], '-o', sys.argv[2])"
)


class HeaderModule(BaseModel):
    module: str
    text: str = Field(description="The module's header file (`module …;` and one declaration per class)")


class EnvironmentHeaders(BaseModel):
    environment: str
    modules: list[HeaderModule]
    components: dict[str, str] = Field(description="Each class's declaration, by address")


_cache: dict[tuple[str, str], EnvironmentHeaders] = {}


async def _print_headers(components: list[dict[str, object]], schema_version: object) -> dict[str, str]:
    """`{module: text}` for a manifest of these components."""
    with tempfile.TemporaryDirectory() as tmp:
        manifest = Path(tmp) / "manifest.json"
        manifest.write_text(json.dumps({"schema_version": schema_version, "components": components}))
        out = Path(tmp) / "headers"
        out.mkdir()
        process = await asyncio.create_subprocess_exec(
            str(pblang_python()), "-c", _HEADERS, str(manifest), str(out),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )  # fmt: skip
        output, _ = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(f"process-bigraph-lang could not print the headers: {output.decode(errors='replace')}")
        return {f.stem: f.read_text() for f in sorted(out.glob("*.pbl"))}


def _declaration(text: str) -> str:
    """A one-class header file without its leading comment and `module` line."""
    lines = text.splitlines()
    start = next((i + 1 for i, line in enumerate(lines) if line.startswith("module ")), 0)
    return "\n".join(lines[start:]).strip() + "\n"


async def environment_headers(name: str, interfaces: dict[str, Any] | None) -> EnvironmentHeaders | None:
    """The environment's header files, from its version's read-back (``interfaces``, D8.4), or None without one."""
    if interfaces is None:
        return None
    raw = json.dumps(interfaces, sort_keys=True).encode()
    key = (name, hashlib.sha256(raw).hexdigest())
    if key in _cache:
        return _cache[key]
    manifest = interfaces
    components: list[dict[str, object]] = manifest.get("components", [])
    version = manifest.get("schema_version")
    modules = await _print_headers(components, version)
    # each class alone: a module of its own, so one run prints every declaration separately
    alone = [{**c, "module": f"c{i}"} for i, c in enumerate(components)]
    singles = await _print_headers(alone, version)
    headers = EnvironmentHeaders(
        environment=name,
        modules=[HeaderModule(module=m, text=t) for m, t in modules.items()],
        components={str(c["address"]): _declaration(singles[f"c{i}"]) for i, c in enumerate(components)},
    )
    _cache[key] = headers
    return headers
