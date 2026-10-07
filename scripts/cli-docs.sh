#!/usr/bin/env bash
# Rewrite the generated command reference at the end of a CLI doc (docs/cli.md): everything after the
# "BEGIN generated reference" marker is replaced by typer's output for the compose-api command.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
doc="$1"
marker='<!-- BEGIN generated reference'
ref="$(mktemp)"
trap 'rm -f "${ref}"' EXIT
uv run --project "${ROOT_DIR}" typer compose_api_client.cli.commands utils docs --name compose-api \
  --title "Command reference" --output "${ref}" >/dev/null
# typer escapes apostrophes as HTML entities; Markdown does not need that.
sed -i.bak "s/&#x27;/'/g" "${ref}" && rm -f "${ref}.bak"
head="$(mktemp)"
trap 'rm -f "${ref}" "${head}"' EXIT
awk -v m="${marker}" '{ print } index($0, m) == 1 { exit }' "${doc}" > "${head}"
{ cat "${head}"; echo; cat "${ref}"; } > "${doc}"
