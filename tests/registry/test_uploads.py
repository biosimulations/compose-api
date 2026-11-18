"""Files in an upload that a simulator would unpickle (registry/uploads.py).

The fixtures in tests/fixtures/resources/hdf5/ were written by pandas 3.1.1 and PyTables 3.11.1 (its README has the
script). Each pickle in them prints one line when it is unpickled. Reading object_column.h5, pickled_attribute.h5 or
old_format_object.h5 with PyTables, which is what pandas does (``pd.HDFStore(path)[key]``, as in tyssue's
``load_datasets``), runs that pickle. plain_attribute.h5 holds a dict that PyTables pickled into an attribute; it
reads back as that dict.
"""

import pickle
from pathlib import Path

import h5py  # type: ignore[import-untyped]
import pytest

from compose_api.environments.compliance import COMPLIANCE_DIR
from compose_api.registry.uploads import hdf5_hazards, is_hdf5

HDF5 = Path(__file__).parent.parent / "fixtures" / "resources" / "hdf5"
TISSUE_MESH = COMPLIANCE_DIR / "vivarium-tyssue" / "sheet-relaxation" / "test_square.hf5"


@pytest.mark.parametrize(
    ("name", "hazard"),
    [
        ("object_column.h5", "face/block1_values: a column of Python objects"),
        ("pickled_attribute.h5", "face/axis1: attribute 'name' is a pickle that runs code"),
        # format 1.x marks an object column by FLAVOR alone, and rewrites FILTERS before unpickling it
        ("old_format_object.h5", "/: a PyTables file of format '1.6', older than 2.0"),
    ],
)
def test_a_file_pandas_would_run_code_from_is_a_hazard(name: str, hazard: str) -> None:
    (found,) = hdf5_hazards((HDF5 / name).read_bytes())
    assert found.startswith(hazard)


@pytest.mark.parametrize("path", [HDF5 / "plain_attribute.h5", TISSUE_MESH], ids=["plain-attribute", "tissue-mesh"])
def test_a_file_of_data_is_not(path: Path) -> None:
    assert hdf5_hazards(path.read_bytes()) == []


def test_a_hazard_after_a_user_block_is_found() -> None:
    """The HDF5 library looks for its signature at 512, 1024, ... too, so a check at offset 0 alone would miss it."""
    data = bytes(512) + (HDF5 / "object_column.h5").read_bytes()
    assert not data.startswith(b"\x89HDF") and is_hdf5(data)
    (found,) = hdf5_hazards(data)
    assert "a column of Python objects" in found


def test_a_pickle_in_a_variable_length_string_attribute_is_found(tmp_path: Path) -> None:
    """PyTables reads a variable-length ASCII string as bytes, and unpickles it when it ends in "."."""
    path = tmp_path / "mesh.h5"
    with h5py.File(path, "w") as hdf5:
        hdf5["x"] = [1.0]
        hdf5["x"].attrs.create("name", pickle.dumps(print, 0).decode(), dtype=h5py.string_dtype("ascii"))
        hdf5["x"].attrs.create("units", pickle.dumps(["um", None], 0).decode(), dtype=h5py.string_dtype("ascii"))
    (found,) = hdf5_hazards(path.read_bytes())
    assert found == "x: attribute 'name' is a pickle that runs code when PyTables reads it"


@pytest.mark.parametrize(("offset", "byte"), [(2380, 214), (6097, 43), (53, 124)])
def test_a_damaged_file_is_refused_whatever_h5py_raises(offset: int, byte: int) -> None:
    """These bytes made h5py raise RuntimeError, KeyError and OverflowError: refused, not a server error."""
    data = bytearray((HDF5 / "plain_attribute.h5").read_bytes())
    data[offset] = byte
    (found,) = hdf5_hazards(bytes(data))
    assert found.startswith("HDF5 that cannot be read")


def test_other_files_are_not_read() -> None:
    assert hdf5_hazards(b'{"state": {}}') == []
