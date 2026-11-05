#!/usr/bin/env bash
# Deploy guard: what Flux applies from main must be exactly what a release tag says.
#
# Flux deploys kustomize/overlays/compose-api-rke from main within a minute of a merge (CLAUDE.md, "Deploys are
# GitOps"). This check keeps every deployed state interpretable as a release. At the commit being checked:
#
#   1. the API image's newTag in the overlay equals the version in pyproject.toml, compose_api/version.py and
#      clients/python/pyproject.toml (tag.sh bumps them together);
#   2. the tag newTag exists and is an ancestor of the commit;
#   3. nothing Flux applies (the overlay, kustomize/config/compose-api-rke, kustomize/base) differs from that tag;
#   4. the image ghcr.io/biosimulations/compose-api:<newTag> has been pushed.
#
# A change that touches none of those passes at once and deploys nothing. A release PR passes once its tag is
# pushed on the PR's head commit and the image is built, so the check waits for both (DEPLOY_GUARD_WAIT seconds,
# default 1200): push the tag right after opening the PR.
#
# Usage: scripts/deploy-guard.sh            (in a clone with tags; CI fetches them)
set -euo pipefail

OVERLAY=kustomize/overlays/compose-api-rke
SURFACE=("$OVERLAY" kustomize/config/compose-api-rke kustomize/base)
IMAGE=biosimulations/compose-api
WAIT=${DEPLOY_GUARD_WAIT:-1200}
POLL=30

fail() {
    echo "deploy-guard: $*" >&2
    exit 1
}

# The newTag on the line after the API image's name (the overlay also pins mongo's).
new_tag=$(awk -v img="ghcr.io/$IMAGE" '$0 ~ "name: " img "$" {getline; print $2; exit}' "$OVERLAY/kustomization.yaml")
[ -n "$new_tag" ] || fail "no newTag for ghcr.io/$IMAGE in $OVERLAY/kustomization.yaml"
echo "deploy-guard: the overlay deploys ghcr.io/$IMAGE:$new_tag"

version() { grep -m1 -E "$2" "$1" | sed -E 's/.*["'"'"']([^"'"'"']+)["'"'"'].*/\1/'; }
for spec in "pyproject.toml|^version" "clients/python/pyproject.toml|^version" "compose_api/version.py|^__version__"; do
    file=${spec%%|*}
    found=$(version "$file" "${spec#*|}")
    [ "$found" = "$new_tag" ] || fail "$file says $found but the overlay deploys $new_tag; release with make tag"
done

image_pushed() {
    local token
    token=$(curl -fsS "https://ghcr.io/token?scope=repository:$IMAGE:pull" | sed -E 's/.*"token":"([^"]+)".*/\1/') || return 1
    curl -fsS -o /dev/null -H "Authorization: Bearer $token" \
        -H "Accept: application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.v2+json" \
        "https://ghcr.io/v2/$IMAGE/manifests/$new_tag"
}

deadline=$((SECONDS + WAIT))
while :; do
    git fetch --quiet --force origin "refs/tags/$new_tag:refs/tags/$new_tag" 2>/dev/null || true
    if git rev-parse -q --verify "refs/tags/$new_tag^{commit}" >/dev/null; then
        if image_pushed; then
            break
        fi
        waiting="the image ghcr.io/$IMAGE:$new_tag"
    else
        waiting="the tag $new_tag"
    fi
    if [ "$SECONDS" -ge "$deadline" ]; then
        fail "gave up waiting for $waiting. Push the tag on the release PR's head commit (git tag -a $new_tag;" \
            "git push origin $new_tag), let build-containers.yml finish, then re-run this check."
    fi
    echo "deploy-guard: waiting for $waiting ..."
    sleep "$POLL"
done

git merge-base --is-ancestor "refs/tags/$new_tag" HEAD ||
    fail "tag $new_tag is not an ancestor of this commit: tag the release PR's head commit, not another branch"

changed=$(git diff --name-only "refs/tags/$new_tag" HEAD -- "${SURFACE[@]}")
if [ -n "$changed" ]; then
    echo "$changed" | sed 's/^/  /' >&2
    fail "these files Flux applies differ from tag $new_tag, so merging would deploy an untagged state;" \
        "make the change in a release (make tag) and push the tag on its head commit"
fi

echo "deploy-guard: ok, what main would deploy is exactly release $new_tag"
