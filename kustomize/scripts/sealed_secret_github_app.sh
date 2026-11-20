#!/usr/bin/env bash

# This script creates the sealed secret holding the GitHub App's private key, which the API uses to read private
# repositories for lock and build Jobs (compose_api/environments/source_credentials.py). It takes 2 arguments: the
# namespace and the key file GitHub gave for the App, and an optional --cert <filename.pem> argument to specify the
# certificate file for kubeseal. The output goes in the overlay, listed in its kustomization's resources, and the App's
# id in kustomize/config/compose-api-rke/api.env as GITHUB_APP_ID. Delete the key file once it is sealed.
# Example: ./sealed_secret_github_app.sh [--cert filename.pem] compose-api-rke app.private-key.pem \
#            > ../overlays/compose-api-rke/secret-github-app.yaml

# Initialize variables
CERT_ARG=""

# Parse optional arguments
while [[ "$1" == --* ]]; do
  case "$1" in
    --cert)
      CERT_ARG="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

# Validate the number of positional arguments
if [ "$#" -ne 2 ]; then
    echo "Illegal number of parameters"
    echo "Usage: ./sealed_secret_github_app.sh [--cert <filename.pem>] <namespace> <private_key_file>"
    exit 1
fi

SECRET_NAME="github-app"
NAMESPACE=$1
KEY_FILE=$2

# Create the secret and seal it
kubectl create secret generic ${SECRET_NAME} --dry-run=client \
      --from-file=private-key.pem="${KEY_FILE}" \
      --namespace="${NAMESPACE}" -o yaml | kubeseal --format yaml ${CERT_ARG:+--cert=$CERT_ARG}
