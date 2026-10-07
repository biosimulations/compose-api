#!/usr/bin/env bash
# Generate the Python client from the committed OpenAPI spec (docs/plan-cli.md, step A).
#
#   scripts/generate-api-client.sh            # regenerate clients/python/compose_api_client in place
#   scripts/generate-api-client.sh OUT_DIR    # generate into OUT_DIR instead (make check-clients)
#   LIB_DIR=../compose-api-client/compose_api_client scripts/generate-api-client.sh
#                                             # also write the external 0.2.x repository pbest pins
#
# The output must be the same on every machine, or the drift check in `make check-clients` cannot work. So the
# generator's own post-hooks are off (they run whatever `ruff` is on PATH, with its defaults), and the script formats
# the result itself with this repository's locked ruff and its pyproject settings.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SPEC="${ROOT_DIR}/compose_api/api/spec/openapi_3_1_0_generated.yaml"
CONFIG="${ROOT_DIR}/scripts/openapi-python-client.yaml"
DEST="${1:-${ROOT_DIR}/clients/python/compose_api_client}"

generate() {
  local out="$1" work
  # Generate and format in a scratch directory, then copy into place. Formatting in place would be skipped: the
  # repository's ruff `exclude` covers compose_api/api/client when ruff walks a directory. The pre-commit hooks pass
  # the files by name, so they do format the committed client, with the repository's settings, which is why the
  # same settings are named here (`--config`): `make check` and `make check-clients` then agree on every byte.
  work="$(mktemp -d)"
  trap 'rm -rf "${work}"' RETURN
  uv run --project "${ROOT_DIR}" openapi-python-client generate --path "${SPEC}" --config "${CONFIG}" \
    --output-path "${work}/client" --meta none --fail-on-warning --overwrite
  uv run --project "${ROOT_DIR}" ruff check --config "${ROOT_DIR}/pyproject.toml" --quiet --fix --select I,F401 \
    "${work}/client"
  uv run --project "${ROOT_DIR}" ruff format --config "${ROOT_DIR}/pyproject.toml" --quiet "${work}/client"
  rm -rf "${work}/client/.ruff_cache"
  touch "${work}/client/py.typed"  # the generated code is typed (PEP 561), so type checkers use it
  # Hand-written code inside the package is carried over, not deleted with the old generated tree: ext/ (the
  # application layer and CLI, docs/plan-cli.md) and utils/ (the 0.2.0 helper pbest uses).
  for keep in ext utils; do
    if [ -d "${out}/${keep}" ]; then cp -R "${out}/${keep}" "${work}/client/${keep}"; fi
  done
  rm -rf "${out}"
  mkdir -p "$(dirname "${out}")"
  cp -R "${work}/client" "${out}"
}

generate "${DEST}"
if [ -n "${LIB_DIR:-}" ]; then
  generate "${LIB_DIR}"
fi
