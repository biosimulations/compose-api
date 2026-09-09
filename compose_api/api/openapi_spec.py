import json
import os
from typing import Any

import yaml
from fastapi.openapi.utils import get_openapi

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


def main() -> None:
    openapi_spec = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version=app.openapi_version,
        description=app.description,
        routes=app.routes,
        servers=app.servers,
    )
    _restore_binary_format(openapi_spec)

    # Convert the JSON OpenAPI spec to YAML
    openapi_spec_yaml = yaml.dump(json.loads(json.dumps(openapi_spec)), sort_keys=False)

    current_directory = os.path.dirname(os.path.realpath(__file__))

    # Write the YAML OpenAPI spec to a file in subdirectory spec
    openapi_version = app.openapi_version.replace(".", "_")
    spec_fp = f"{current_directory}/spec/openapi_{openapi_version}_generated.yaml"
    if os.path.exists(spec_fp):
        print("Spec exists, overwriting")
        os.remove(spec_fp)

    with open(spec_fp, "w") as f:
        f.write(openapi_spec_yaml)

    print("New OpenAPI spec for compose_api generated!")


if __name__ == "__main__":
    main()
