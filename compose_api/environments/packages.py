"""How two versions' packages differ, from what each one's image installed (docs/plan-webapp-admin.md, step 3).

The read-back (``installed``, one ``name==version`` per line) is compared rather than the lock, because every version
has one: a composed version, an old shared one with no lock (registry_env@1) and a prebuilt image alike. Names compare
as PyPI compares them (PEP 503), the same as the webapp's version view (``webapp/app/utils/environments.ts``).
"""

import re

from compose_api.simulation.models import PackageChange


def normalize(name: str) -> str:
    """A PyPI name as PEP 503 compares it: case-insensitive, with runs of ``-``, ``_`` and ``.`` alike."""
    return re.sub(r"[-_.]+", "-", name).lower()


def installed_pins(text: str | None) -> dict[str, str]:
    """A version's installed packages, by normalized name."""
    pins = {}
    for line in (text or "").splitlines():
        name, separator, version = line.strip().partition("==")
        if name and separator:
            pins[normalize(name)] = version.strip()
    return pins


def package_changes(before: str | None, after: str | None) -> list[PackageChange]:
    """Each package added (``before`` None), removed (``after`` None) or at another version, by name."""
    old, new = installed_pins(before), installed_pins(after)
    return [
        PackageChange(name=n, before=old.get(n), after=new.get(n))
        for n in sorted(old.keys() | new.keys())
        if old.get(n) != new.get(n)
    ]
