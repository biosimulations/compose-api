"""Writes small.fenics, the results bundle the web UI's bundle reader is tested against (docs/plan-viewers.md F2).

Run from a viva-pde-particle checkout's pixi env (it has SpatialBundleWriter and vcell-fenics):
    cd ../viva-pde-particle && pixi run -e compose python ../compose-api/webapp/test/fixtures/make_fixture.py
"""

import shutil
from pathlib import Path

import numpy as np
from viva_pde_particle.grid import CartesianGrid
from viva_pde_particle.viz3d import SpatialBundleWriter, grid_domain

OUT = Path(__file__).with_name("small.fenics")
shutil.rmtree(OUT, ignore_errors=True)
g = CartesianGrid((0, 0, 0), (2, 2, 2), (5, 5, 5))
x, y, z = g.node_coordinates()
r2 = (x - 1) ** 2 + (y - 1) ** 2 + (z - 1) ** 2
vol = grid_domain("cell", g)
w = SpatialBundleWriter(OUT, source="compose-api webapp fixture")
w.add_domain(vol, ["u"])
w.add_particles(["A"])
w.open()
for k, t in enumerate([0.0, 0.5, 1.0]):
    field = np.exp(-r2) * (1 + k)  # row k: values (1 + k) * exp(-r^2), so stats are easy to check
    xyz = np.array([[1.0, 1.0, 1.0]] * (k + 1)) + 0.1 * k
    w.write(t, {("cell", "u"): field.ravel()[vol.node_index]}, particles={"A": xyz})
w.finalize()
print(OUT)
