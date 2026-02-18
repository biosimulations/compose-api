#!/bin/bash

LIB_DIR="${LIB_DIR:-NOT_SET}"

if [ "$LIB_DIR" == "NOT_SET" ]; then
  echo "Need to specify where the clients will be generated."
  exit 1
fi


ROOT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && cd .. && pwd )"

#generatorCliImage=openapitools/openapi-generator-cli:v7.1.0

# make a clean ROOT_DIR without .. (hint, use dirname or something like that)
SPEC_DIR="${ROOT_DIR}/compose_api/api/spec"
LOCAL_VERSION="${ROOT_DIR}/compose_api/api/client" # Allows for easy testing

# Generate simdata-api client
# TODO: improve Python typing for Mypy
# TODO: make attributes dictionaries - easier to work with
PACKAGE="compose_api.api.client"

# use openapi-generator-cli if available, else use openapi-generator
#if command -v openapi-generator-cli &> /dev/null; then
#    OPENAPI_CMD="openapi-generator-cli"
#else
#    OPENAPI_CMD="openapi-generator"
#fi

#$OPENAPI_CMD generate -i "${SPEC_DIR}/openapi_3_1_0_generated.yaml" -g python -o "${LIB_DIR}" --additional-properties=packageName=${PACKAGE},generateSourceCodeOnly=true
# --config "${ROOT_DIR}/scripts/openapi-python-client.yaml"
echo "SPEC_DIR is ${SPEC_DIR}"
echo "LIB_DIR is ${LIB_DIR}"
for gen_dest in "$LOCAL_VERSION" "$LIB_DIR"; do
  openapi-python-client generate --path "${SPEC_DIR}/openapi_3_1_0_generated.yaml" --output-path "${gen_dest}" --meta none --fail-on-warning --overwrite
  if [ $? -ne 0 ]; then
      echo "Error: Failed to generate API client."
      exit 1
  fi
done
