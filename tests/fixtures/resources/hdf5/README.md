# HDF5 fixtures for the upload guard

These files test `compose_api/registry/uploads.py`. They were written by pandas 3.1.1 and PyTables 3.11.1, the versions
vivarium-tyssue's composed environment resolves. Each pickle in them prints one line when it is unpickled, and does
nothing else.

| File | What PyTables does when it reads the file |
|---|---|
| `object_column.h5` | Unpickles an object column (`PSEUDOATOM=object`). |
| `pickled_attribute.h5` | Unpickles the `name` attribute of `/face/axis1`. |
| `old_format_object.h5` | Unpickles a column marked only `FLAVOR=Object`, because the file is format 1.6. |
| `plain_attribute.h5` | Reads `/face`'s `info` attribute back as a dict and calls nothing. |

The script that wrote them, run as `uv run --no-project --with pandas==3.1.1 --with tables==3.11.1 python make.py`:

```python
import builtins

import numpy as np
import pandas as pd
import tables


class Marker:
    def __reduce__(self):  # harmless when unpickled: print a line
        return (builtins.print, ("unpickled from an HDF5 upload",))


frame = pd.DataFrame({"x": [0.0, 1.0], "y": [2.0, 3.0]})

with pd.HDFStore("object_column.h5", mode="w", complevel=9, complib="zlib") as store:
    store.put("face", frame.assign(kind=pd.Series([Marker(), "healthy"], dtype=object)))

with pd.HDFStore("pickled_attribute.h5", mode="w") as store:
    store.put("face", frame)
with tables.open_file("pickled_attribute.h5", "a") as h5:
    h5.get_node("/face/axis1")._v_attrs.name = Marker()

with pd.HDFStore("plain_attribute.h5", mode="w") as store:
    store.put("face", frame)
with tables.open_file("plain_attribute.h5", "a") as h5:
    h5.get_node("/face")._v_attrs.info = {"source": "test", "cells": [1, 2]}

with tables.open_file("old_format_object.h5", "w") as h5:
    column = h5.create_vlarray("/", "column", tables.ObjectAtom(), expectedrows=1, filters=tables.Filters(9, "zlib"))
    column.append(Marker())
with tables.open_file("old_format_object.h5", "a") as h5:
    del h5.root.column._v_attrs.PSEUDOATOM
    h5.root.column._v_attrs.FLAVOR = np.bytes_(b"Object")
    h5.root._v_attrs.PYTABLES_FORMAT_VERSION = np.bytes_(b"1.6")
```
