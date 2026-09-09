"""Verify the citations in the CIP design review against the pinned checkouts.

Read-only. Two checks:

1. Every backticked ``path:line`` (or ``path:line-line``) whose path resolves into one of the two library
   checkouts exists, and the file has at least that many lines. For anchors listed in ``SYMBOLS`` the named
   symbol must also appear within three lines of the cited line.
2. Every blockquoted line in §1 of the review, and every ``**Grant said.**`` quote in §4, is a verbatim
   substring of the grant text after light normalization (markdown escapes, curly quotes, dashes, whitespace).

Usage: ``python docs/cip/check_citations.py`` from the compose-api root. Exit status 1 on any failure.
"""

from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ROOT.parent
REVIEW = ROOT / "docs" / "cip" / "CIP-design-review.md"
GLOSSARY = ROOT / "docs" / "cip" / "GLOSSARY.md"
GRANT = [
    ROOT / "docs" / "grant" / "trd3" / "TR&D3 - Research Strategy.md",
    ROOT / "docs" / "grant" / "trd3" / "TR&D3 - Specific Aims.md",
]

REPOS = {
    "process_bigraph/": WORKSPACE / "process-bigraph",
    "tests.py": WORKSPACE / "process-bigraph",
    "bigraph_schema/": WORKSPACE / "bigraph-schema",
}

# Anchors whose symbol must be within 3 lines of the cited line. (file, line) -> symbol
SYMBOLS: dict[tuple[str, int], str] = {
    ("process_bigraph/composite.py", 401): "class Open",
    ("process_bigraph/composite.py", 570): "class Step",
    ("process_bigraph/composite.py", 777): "class Process",
    ("process_bigraph/composite.py", 1252): "class Composite",
    ("process_bigraph/composite.py", 1259): "config_schema",
    ("process_bigraph/composite.py", 2599): "def run(",
    ("process_bigraph/composite.py", 2631): "def _run_inner(",
    ("process_bigraph/composite.py", 3128): "def apply_updates(",
    ("process_bigraph/composite.py", 3064): "def finalize(",
    ("process_bigraph/composite.py", 2752): "def _require_ground_document(",
    ("process_bigraph/composite.py", 2320): "def build_step_network(",
    ("process_bigraph/composite.py", 2481): "def trigger_steps(",
    ("process_bigraph/composite.py", 2512): "def run_steps(",
    ("process_bigraph/composite.py", 801): "def calculate_timestep(",
    ("process_bigraph/composite.py", 804): "def update(",
    ("process_bigraph/composite.py", 762): "def update(",
    ("process_bigraph/composite.py", 621): "def triggers(",
    ("process_bigraph/composite.py", 634): "def scatter_port(",
    ("process_bigraph/composite.py", 402): "METHOD_COMMANDS",
    ("process_bigraph/composite.py", 3384): "def update(",
    ("process_bigraph/composite.py", 1784): "def _realize_structural_subtrees(",
    ("process_bigraph/composite.py", 1852): "def _apply_structural_events(",
    ("process_bigraph/emitter.py", 518): "class Emitter",
    ("process_bigraph/emitter.py", 422): "def gather_emitter_results(",
    ("process_bigraph/templates.py", 122): "def is_ground_document(",
    ("process_bigraph/scheduling.py", 307): "def build_step_network(",
    ("process_bigraph/scheduling.py", 478): "def determine_steps(",
    ("process_bigraph/scheduling.py", 257): "def empty_front(",
    ("process_bigraph/artifacts.py", 106): "def _address(",
    ("process_bigraph/types/process.py", 46): "interval",
    ("process_bigraph/protocols/rest.py", 46): "class RestProcess",
    ("process_bigraph/protocols/git.py", 83): "_ADDRESS_RE",
    ("process_bigraph/protocols/git.py", 475): "class GitRemoteProcess",
    ("bigraph_schema/edge.py", 100): "def initialize(",
    ("bigraph_schema/edge.py", 104): "def initial_state(",
    ("bigraph_schema/edge.py", 113): "def inputs(",
    ("bigraph_schema/edge.py", 122): "def outputs(",
    ("bigraph_schema/edge.py", 144): "def interface(",
    ("bigraph_schema/contract.py", 52): "class Amendment",
    ("bigraph_schema/contract.py", 89): "class ProcessContract",
    ("bigraph_schema/contract.py", 207): "def amend(",
    ("bigraph_schema/core.py", 523): "def access(",
    ("bigraph_schema/core.py", 1143): "def _resolve_wire_paths(",
    ("bigraph_schema/core.py", 1214): "def _compute_unit_scale(",
    ("bigraph_schema/core.py", 248): "def register_translator(",
    ("bigraph_schema/core.py", 281): "def cross(",
    ("bigraph_schema/schema.py", 15): "def normalize_address(",
    ("bigraph_schema/schema.py", 55): "class Node",
    ("bigraph_schema/schema.py", 100): "class Number",
    ("bigraph_schema/schema.py", 279): "class Path",
    ("bigraph_schema/schema.py", 283): "class Wires",
    ("bigraph_schema/schema.py", 300): "class Link",
    ("bigraph_schema/schema.py", 550): "class Quantity",
    ("bigraph_schema/schema.py", 630): "class Site",
    ("bigraph_schema/protocols.py", 46): "def local_lookup(",
    ("bigraph_schema/protocols.py", 120): "def unresolvable_addresses(",
    ("bigraph_schema/protocols.py", 142): "def assert_portable_addresses(",
    ("bigraph_schema/methods/realize.py", 605): "def realize_link(",
    ("bigraph_schema/methods/realize.py", 566): "def port_merges(",
    ("bigraph_schema/methods/realize.py", 552): "def load_protocol(",
    ("bigraph_schema/assembly.py", 57): "def interfaces(",
    ("bigraph_schema/assembly.py", 764): "def contract_admits(",
    ("bigraph_schema/assembly.py", 786): "def face_conforms(",
    ("bigraph_schema/assembly.py", 967): "def fill_sites(",
    ("bigraph_schema/translator.py", 51): "class Translator",
    ("bigraph_schema/units.py", 50): "def render_units_type(",
    ("bigraph_schema/parse.py", 249): "def visit_expression(",
    ("tests.py", 70): "def test_process(",
    ("tests.py", 85): "def test_composite(",
    ("tests.py", 131): "def test_infer(",
    ("tests.py", 152): "def test_step_initialization(",
    ("tests.py", 186): "def test_dependencies(",
    ("tests.py", 252): "def test_dependency_cycle(",
    ("tests.py", 451): "def test_nested_wires(",
    ("tests.py", 540): "def test_grow_divide(",
    ("tests.py", 752): "def test_star_update(",
    ("tests.py", 819): "def test_update_removal(",
    ("tests.py", 1533): "def test_dynamic_structure(",
    ("tests.py", 2317): "def test_parallel_processes_matches_serial(",
    ("tests.py", 2625): "def test_rest_server_initialize_inputs_outputs_update(",
    ("tests.py", 3292): "def test_the_results_handle_is_a_reference_not_the_data(",
    ("tests.py", 3668): "def test_unfilled_required_site_is_rejected(",
    ("tests.py", 5910): "def test_version_matches_pyproject(",
}

ANCHOR_RE = re.compile(r"`((?:process_bigraph/|bigraph_schema/|tests\.py)[^`:]*):(\d+)(?:-(\d+))?")
FILE_LINE_CACHE: dict[Path, list[str]] = {}


def lines_of(path: Path) -> list[str]:
    if path not in FILE_LINE_CACHE:
        FILE_LINE_CACHE[path] = path.read_text(errors="replace").splitlines()
    return FILE_LINE_CACHE[path]


def resolve(rel: str) -> Path | None:
    for prefix, repo in REPOS.items():
        if rel.startswith(prefix):
            return repo / rel
    return None


def check_anchors(doc: Path) -> list[str]:
    failures: list[str] = []
    seen: set[tuple[str, int]] = set()
    text = doc.read_text()
    for m in ANCHOR_RE.finditer(text):
        rel, start = m.group(1), int(m.group(2))
        end = int(m.group(3)) if m.group(3) else start
        key = (rel, start)
        if key in seen:
            continue
        seen.add(key)
        path = resolve(rel)
        if path is None or not path.exists():
            failures.append(f"{doc.name}: {rel}:{start} -> file not found")
            continue
        n = len(lines_of(path))
        if end > n:
            failures.append(f"{doc.name}: {rel}:{start}-{end} beyond EOF ({n} lines)")
            continue
        symbol = SYMBOLS.get(key)
        if symbol:
            window = "\n".join(lines_of(path)[max(0, start - 4) : start + 3])
            if symbol not in window:
                failures.append(f"{doc.name}: {rel}:{start} expected '{symbol}' within ±3 lines")
    return failures


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("\\", "")
    # Curly quotes and dashes, written as escapes so the linter does not flag ambiguous characters.
    for src, dst in (
        ("\u2019", "'"),  # right single quotation mark
        ("\u2018", "'"),  # left single quotation mark
        ("\u201c", '"'),  # left double quotation mark
        ("\u201d", '"'),  # right double quotation mark
        ("\u2013", "-"),  # en dash
        ("\u2014", "-"),  # em dash
        ("''", '"'),
    ):
        s = s.replace(src, dst)
    s = re.sub(r"[*_]+", "", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


def grant_quotes(review: str) -> list[str]:
    quotes: list[str] = []
    # §1 blockquotes: consecutive "> " lines form one quote.
    section1 = review.split("## 1. What the grant proposed", 1)[1].split("## 2. What exists today", 1)[0]
    block: list[str] = []
    for line in section1.splitlines():
        if line.startswith("> "):
            block.append(line[2:])
        elif block:
            quotes.append(" ".join(block))
            block = []
    if block:
        quotes.append(" ".join(block))
    # §4 "Grant said." quotes: every double-quoted span longer than 30 characters.
    section4 = review.split("## 4. Decisions", 1)[1]
    for para in re.findall(r"\*\*Grant said\.\*\*(.+?)(?:\n\n)", section4, flags=re.S):
        for span in re.findall(r'"([^"]{30,})"', para):
            quotes.append(span)
    return quotes


def check_quotes(review_path: Path) -> list[str]:
    corpus = normalize(" ".join(p.read_text() for p in GRANT if p.exists()))
    failures: list[str] = []
    for q in grant_quotes(review_path.read_text()):
        nq = normalize(q)
        # Allow an elision marker in the middle of a quote.
        parts = [p.strip() for p in nq.split("…") if p.strip()]
        for part in parts:
            if part not in corpus:
                failures.append(f"quote not verbatim in grant text: {part[:90]}...")
    return failures


def main() -> int:
    failures: list[str] = []
    for doc in (REVIEW, GLOSSARY):
        failures += check_anchors(doc)
    if all(p.exists() for p in GRANT):
        failures += check_quotes(REVIEW)
    else:
        print("grant text not present; skipping quote check")
    if failures:
        print("\n".join(failures))
        print(f"\n{len(failures)} failure(s)")
        return 1
    anchors = len(set(ANCHOR_RE.findall(REVIEW.read_text()) + ANCHOR_RE.findall(GLOSSARY.read_text())))
    print(f"ok: {anchors} distinct anchors resolved; grant quotes verbatim")
    return 0


if __name__ == "__main__":
    sys.exit(main())
