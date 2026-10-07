"""Output for the CLI: a rich table (or panel) on a terminal, JSON otherwise. Results go to stdout; progress and
errors go to stderr, so ``compose-api ... --output json | jq`` always sees clean JSON."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable, Sequence
from enum import StrEnum
from typing import Any

from rich.console import Console
from rich.table import Table
from rich.tree import Tree

out = Console()
err = Console(stderr=True)


class Output(StrEnum):
    AUTO = "auto"
    TABLE = "table"
    JSON = "json"


def resolve(fmt: Output) -> Output:
    if fmt is Output.AUTO:
        return Output.TABLE if sys.stdout.isatty() else Output.JSON
    return fmt


def plain(value: Any) -> Any:
    """A JSON-ready value: attrs models through ``to_dict()``, lists and dicts recursively."""
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    return value


def emit(fmt: Output, data: Any, columns: Sequence[str] | None = None, title: str | None = None) -> None:
    """Print ``data`` (a record or a list of records) as JSON, or as a table of ``columns`` (all keys of a record
    when omitted)."""
    data = plain(data)
    if resolve(fmt) is Output.JSON:
        sys.stdout.write(json.dumps(data, indent=2, default=str) + "\n")
        return
    rows: list[dict[str, Any]] = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
    if not rows and not isinstance(data, list):
        out.print(data)
        return
    if isinstance(data, dict) and columns is None:  # one record: a two-column key/value table
        table = Table(title=title, show_header=False)
        table.add_column(style="bold")
        table.add_column()
        for k, v in data.items():
            table.add_row(k, _cell(v))
        out.print(table)
        return
    cols = list(columns or (rows[0].keys() if rows else []))
    table = Table(title=title)
    for c in cols:
        table.add_column(c)
    for r in rows:
        table.add_row(*(_cell(r.get(c)) for c in cols))
    out.print(table)


def _cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, default=str)
    return str(v)


def lines(items: Iterable[str]) -> None:
    for i in items:
        out.print(i)


def event_line(fmt: Output, event: dict[str, Any]) -> None:
    """One event: a JSON line, or ``ts  level  source  event  payload`` on a terminal."""
    if resolve(fmt) is Output.JSON:
        sys.stdout.write(json.dumps(event, default=str) + "\n")
        sys.stdout.flush()
        return
    level = str(event.get("level") or "info")
    style = {"error": "red", "warning": "yellow", "debug": "dim"}.get(level, "")
    payload = json.dumps(event.get("payload") or {}, default=str, separators=(",", ":"))
    text = f"{event.get('ts', '')}  {level:<7}  {event.get('source', ''):<14}  {event.get('event', '')}  {payload}"
    out.print(text, style=style, markup=False, highlight=False, soft_wrap=True)


def span_tree(roots: list[dict[str, Any]]) -> None:
    """The trace as an indented tree: each span with its status and duration, then its own events."""
    tree = Tree("trace", hide_root=True)

    def add(parent: Tree, node: dict[str, Any]) -> None:
        span = node["span"]
        duration = span.get("duration_s")
        status = span.get("status") or "open"
        label = f"[bold]{span['name']}[/bold]  {status}" + (f"  {duration:.3f} s" if duration is not None else "")
        if span.get("error"):
            label += f"  [red]{span['error']}[/red]"
        branch = parent.add(label)
        for event in node.get("events") or []:
            branch.add(f"[dim]{event.get('ts', '')}[/dim]  {event.get('event', '')}")
        for child in node.get("children") or []:
            add(branch, child)

    for root in roots:
        add(tree, root)
    out.print(tree)
