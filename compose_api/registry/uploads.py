"""Files in an upload that a simulator would unpickle. The address check (``validation.py``) sees only addresses.

pandas reads HDF5 through PyTables ("Loading pickled data received from untrusted sources can be unsafe",
``pandas/io/pytables.py``). In PyTables 3.11 the reads that unpickle are these:

- a column of Python objects (``atom.ObjectAtom.fromarray``): a VLArray whose ``PSEUDOATOM`` attribute is ``object``,
  which pandas writes for an ``object`` column, or, in a file of PyTables format 1.x, one whose ``FLAVOR`` is
  ``Object`` (``vlarray.py``);
- a scalar string attribute that ends in ``.``, and in format 1.x a ``FILTERS`` attribute after a rewrite
  (``attributeset.AttributeSet.__getattr__``).

A process that loads a submitted file with pandas, as vivarium-tyssue's EulerSolver loads its mesh through tyssue's
``load_datasets``, would run whatever such a pickle calls.

So an archive member that is HDF5, found by its signature under any name, is refused when any of these holds:

- it is a PyTables file older than format 2.0, which no current pandas writes;
- it holds an object column;
- it has an attribute that PyTables would unpickle and whose pickle can import or call something;
- the HDF5 library cannot read it through.

A pickle of plain data (``None``, numbers, strings, lists, dicts), which PyTables writes for some attributes, builds
only that data, so it is allowed.
"""

import io
import pickletools

import numpy as np

_SIGNATURE = b"\x89HDF\r\n\x1a\n"

# The opcodes through which unpickling imports or calls something; a pickle without them only builds plain data.
_CALLS = frozenset({
    "GLOBAL",
    "STACK_GLOBAL",
    "INST",
    "OBJ",
    "NEWOBJ",
    "NEWOBJ_EX",
    "REDUCE",
    "BUILD",
    "EXT1",
    "EXT2",
    "EXT4",
})


def is_hdf5(data: bytes) -> bool:
    """HDF5's signature where the library looks for it: at 0, then after a user block (512, 1024, 2048, ...)."""
    offset = 0
    while offset + len(_SIGNATURE) <= len(data):
        if data[offset : offset + len(_SIGNATURE)] == _SIGNATURE:
            return True
        offset = 512 if offset == 0 else offset * 2
    return False


def _plain_pickle(raw: bytes) -> bool:
    """Whether unpickling ``raw`` builds only plain data: a whole pickle with none of the opcodes that import or
    call. Anything ``pickletools`` cannot read to its end counts as not plain."""
    try:
        return not any(opcode.name in _CALLS for opcode, _, _ in pickletools.genops(raw))
    except ValueError:
        return False


def _unpickled_by_pytables(value: object) -> bytes | None:
    """The bytes PyTables would unpickle for an attribute with this value, or None: a scalar string ending in ``.``
    other than ``0.``. A string h5py reads as ``str`` is checked too, since PyTables may read it as bytes."""
    if isinstance(value, np.ndarray) and value.ndim == 0:
        value = value.item()
    if isinstance(value, str):
        value = value.encode("utf-8", "surrogateescape")
    if isinstance(value, bytes) and value.endswith(b".") and value not in (b"0", b"0."):
        return value
    return None


def _text(value: object) -> str:
    if isinstance(value, np.ndarray) and value.ndim == 0:
        value = value.item()
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)


def hdf5_hazards(data: bytes) -> list[str]:
    """Why a simulator reading this file with pandas would run code from it; empty for a file that is not HDF5, or
    one that holds only data."""
    if not is_hdf5(data):
        return []
    import h5py  # type: ignore[import-untyped]

    hazards: list[str] = []

    def check(name: str, node: object) -> None:
        if not isinstance(node, h5py.HLObject):  # the file, its groups, datasets and named types all are
            return
        where = name or "/"
        attributes = dict(node.attrs.items())
        if not name and "PYTABLES_FORMAT_VERSION" in attributes:
            version = _text(attributes["PYTABLES_FORMAT_VERSION"])
            major = version.partition(".")[0]
            if not (major.isdigit() and int(major) >= 2):
                hazards.append(f"/: a PyTables file of format {version!r}, older than 2.0")
        if isinstance(node, h5py.Dataset) and attributes.get("PSEUDOATOM") in (b"object", "object"):
            hazards.append(f"{where}: a column of Python objects, which pandas unpickles")
        for key, value in attributes.items():
            raw = _unpickled_by_pytables(value)
            if raw is not None and not _plain_pickle(raw):
                hazards.append(f"{where}: attribute {key!r} is a pickle that runs code when PyTables reads it")

    try:
        with h5py.File(io.BytesIO(data), "r") as hdf5:
            check("", hdf5)
            hdf5.visititems(check)
    except Exception as e:  # h5py raises many kinds on a damaged file; it is refused, not a server error
        return [f"HDF5 that cannot be read ({type(e).__name__}: {e})"]
    return hazards
