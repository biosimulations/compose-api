import copy
import json
import os
import sys
from typing import Any

import yaml

from compose_api.api.main import app

# FastAPI >= 0.141 describes `UploadFile` fields as
#   {"type": "string", "contentMediaType": "application/octet-stream"}
# instead of the older {"type": "string", "format": "binary"}. The pinned client generator
# (openapi-python-client 0.29.1) only recognises `format: binary` as a file upload and would
# otherwise emit plain `str` parameters, breaking every upload endpoint in the generated client.
# Normalise back to `format: binary` until the generator learns the new form
# (https://github.com/openapi-generators/openapi-python-client/issues/1417).
_OCTET_STREAM = "application/octet-stream"


def _restore_binary_format(node: Any) -> None:
    if isinstance(node, dict):
        if node.get("type") == "string" and node.get("contentMediaType") == _OCTET_STREAM:
            del node["contentMediaType"]
            node["format"] = "binary"
        for value in node.values():
            _restore_binary_format(value)
    elif isinstance(node, list):
        for item in node:
            _restore_binary_format(item)


def main(argv: list[str] | None = None) -> None:
    """Write the spec to `compose_api/api/spec/`, or to the path given as the first argument
    (`make check-clients` writes a fresh copy elsewhere and compares)."""
    argv = sys.argv[1:] if argv is None else argv
    # app.openapi(), not get_openapi(): the app adds the optional bearer scheme in its override.
    # Deep-copied because the fix-up below mutates, and app.openapi() returns the served, cached dict.
    openapi_spec = copy.deepcopy(app.openapi())
    _restore_binary_format(openapi_spec)

    # Convert the JSON OpenAPI spec to YAML
    openapi_spec_yaml = yaml.dump(json.loads(json.dumps(openapi_spec)), sort_keys=False)

    current_directory = os.path.dirname(os.path.realpath(__file__))

    # Write the YAML OpenAPI spec to a file in subdirectory spec
    openapi_version = app.openapi_version.replace(".", "_")
    spec_fp = argv[0] if argv else f"{current_directory}/spec/openapi_{openapi_version}_generated.yaml"
    if os.path.exists(spec_fp):
        print("Spec exists, overwriting")
        os.remove(spec_fp)

    with open(spec_fp, "w") as f:
        f.write(openapi_spec_yaml)

    print("New OpenAPI spec for compose_api generated!")


if __name__ == "__main__":
    main()
