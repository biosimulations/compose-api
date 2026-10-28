"""A JSON value, for the few places that hold a document whose shape no model describes (an error's ``detail``, a
record printed as JSON). ``Any`` would turn the type checker off for everything that touches it."""

from typing import TypeAlias

JsonValue: TypeAlias = "bool | int | float | str | list[JsonValue] | dict[str, JsonValue] | None"
