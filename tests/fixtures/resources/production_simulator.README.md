# `production_simulator.def`

A verbatim Apptainer definition taken from the **live deployment** at
`https://compose.cam.uchc.edu/core/simulator/list` on 2026-09-12, simulator version
`database_id=34`, recorded there with `container_def_hash = b3352156bfe3a538219a202037486a80`.

It is used by `tests/simulation/test_simulation.py::test_build_simulator` so that the build
path is exercised against something a deployment really produced, rather than something a
test invented.

**Why this one.** Of the 37 versions published at the time, it is the smallest: it declares
no conda and no PyPI dependencies, so it clones and installs a single package rather than
solving a conda environment. Measured on the containerised cluster it builds in about 70
seconds to a 594 MB image, and the result runs, with `bsew` importable inside it. The
newest versions build the full copasi/tellurium/readdy/micromamba stack, which is minutes
and 1.3 GB, and is not something to put on every pull request.

**Do not reformat it.** `get_singularity_hash` is an md5 over these exact bytes, and the
test asserts that hash still equals the value the deployment recorded. Any edit, including
whitespace, breaks that assertion -- which is the point: it is what makes this a fixture
copied from production rather than a file that merely looks like one.

**Refreshing it.** Fetch the list again and pick a small definition:

```bash
curl -s https://compose.cam.uchc.edu/core/simulator/list \
  | python3 -c "import json,sys; vs=json.load(sys.stdin)['versions']; \
      v=min(vs, key=lambda x: len(x['container_def']['representation'])); \
      print(v['database_id'], v['container_def_hash']); \
      open('production_simulator.def','w').write(v['container_def']['representation'])"
```

Then update the hash in `PRODUCTION_SIMULATOR_DEF_HASH` and the identifiers above.
