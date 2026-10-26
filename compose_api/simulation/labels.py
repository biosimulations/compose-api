"""Labels, tags and descriptions on simulations (docs/plan-sedml.md, phase 0).

**Labels** say what a run is, so runs can be found and grouped: the service writes them, under the reserved keys
below, when it submits a run. **Tags** and a **description** are the submitter's, given at submission and not edited
afterwards (runs are anonymous). ``GET /simulations`` filters by both: ``label=key:value`` and ``tag=name``, each
repeatable, all of them required.
"""

import re

#: The keys the service writes, and what each holds. Submitters cannot set labels.
LABEL_KEYS: dict[str, str] = {
    "source": "where the document came from: upload, curated, biomodels, biosimulations",
    "environment": "the environment it ran in: registry_env, or a prebuilt simulator's name",
    "environment_version": "the version of that environment it ran in, e.g. registry_env@2",
    "solver": "the solver a SED-ML or curated run used (registry/solvers.yaml)",
    "model": "the BioModels entry, e.g. BIOMD0000000012",
    "project": "the biosimulations.org project",
    "sedml_task": "the SED-ML task the document was translated from",
    "comparison": "the comparison the run belongs to",
    "collection": "the suite the run belongs to",
    "suite_run": "the suite run it was part of",
    "compliance": "the compliance case it ran, <entry>/<case> (docs/plan-environment-composition.md, step 5)",
}

MAX_TAGS = 20
MAX_DESCRIPTION = 2000
_TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.:/+-]{0,63}$")
_LABEL_VALUE = re.compile(r"^[^\x00-\x1f]{1,200}$")


class LabelError(ValueError):
    """A tag, description or label filter the service does not accept; the message says why."""


def clean_tags(tags: list[str] | None) -> list[str]:
    """Tags as given, trimmed, without duplicates (first occurrence wins); ``LabelError`` for one that is not a tag."""
    cleaned: list[str] = []
    for raw in tags or []:
        tag = raw.strip()
        if not _TAG.match(tag):
            raise LabelError(
                f"tag {raw!r}: 1 to 64 characters, letters, digits, spaces and _ . : / + -, "
                "starting with a letter or digit"
            )
        if tag not in cleaned:
            cleaned.append(tag)
    if len(cleaned) > MAX_TAGS:
        raise LabelError(f"at most {MAX_TAGS} tags")
    return cleaned


def clean_description(description: str | None) -> str | None:
    text = (description or "").strip()
    if len(text) > MAX_DESCRIPTION:
        raise LabelError(f"the description is longer than {MAX_DESCRIPTION} characters")
    return text or None


def labels(**values: str | None) -> dict[str, str]:
    """Service labels from keyword arguments; ``None`` values are left out. Keys must be reserved ones."""
    unknown = sorted(set(values) - set(LABEL_KEYS))
    if unknown:
        raise ValueError(f"not a label key: {', '.join(unknown)}")
    return {k: v for k, v in values.items() if v is not None}


def parse_label_filters(filters: list[str] | None) -> dict[str, str]:
    """``key:value`` filters as a mapping; ``LabelError`` for a malformed one or an unknown key."""
    parsed: dict[str, str] = {}
    for raw in filters or []:
        key, sep, value = raw.partition(":")
        if not sep or not value or key not in LABEL_KEYS or not _LABEL_VALUE.match(value):
            raise LabelError(f"label filter {raw!r}: use key:value with a key among {', '.join(LABEL_KEYS)}")
        parsed[key] = value
    return parsed
