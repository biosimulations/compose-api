"""Stand-ins for what fetching a private repository's source talks to (docs/plan-private-repo-usage.md, C): the GitHub
App's two requests, and the Kubernetes API the Jobs and their Secrets are created through. They show what is asked
for. That GitHub and the cluster accept it is proven live in the plan's P5: its pre-flight mints a token, and v2ecoli's
first mash-up on production exercises the Secret (the Role's `create`, its owner reference, the pod mounting it)."""

import copy
import datetime
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from compose_api.config import override_settings
from compose_api.environments import source_credentials

APP_ID = "424242"
INSTALLATION = 7777
# what a Job's Secret, and nothing else the service makes, holds
TOKEN = "ghs_SENTINELcomposeapitest00000000000000"  # noqa: S105 -- a sentinel, not a credential
JOB_UID = "4f1c2d6e-0000-4000-8000-000000000001"


@dataclass
class FakeGitHub:
    """GitHub, as the App sees it: every request must carry the App's JWT, signed with its key; the installation is
    found for a repository it is installed on; a token is minted for what is asked, each request's body kept."""

    key: rsa.RSAPrivateKey
    installed: dict[str, set[str]]
    lifetime: datetime.timedelta = datetime.timedelta(hours=1)  # GitHub's, for an installation token
    available: bool = True
    malformed: bool = False  # answers a token request with something that is not a token
    minted: list[dict[str, Any]] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        if not self.available:
            return httpx.Response(503, json={"message": "Service Unavailable"})
        claims = jwt.decode(
            request.headers["authorization"].removeprefix("Bearer "),
            self.key.public_key(),
            algorithms=["RS256"],
            options={"require": ["iat", "exp", "iss"]},
        )
        assert claims["iss"] == APP_ID and claims["exp"] - claims["iat"] <= 600  # GitHub refuses a longer one
        parts = request.url.path.strip("/").split("/")
        if request.method == "GET" and len(parts) == 4 and parts[0] == "repos" and parts[3] == "installation":
            if parts[2] in self.installed.get(parts[1], set()):
                return httpx.Response(200, json={"id": INSTALLATION, "account": {"login": parts[1]}})
            return httpx.Response(404, json={"message": "Not Found"})
        if request.method == "POST" and request.url.path == f"/app/installations/{INSTALLATION}/access_tokens":
            self.minted.append(json.loads(request.content))
            if self.malformed:
                return httpx.Response(201, json={"message": "unexpected"})
            expires_at = datetime.datetime.now(datetime.UTC).replace(microsecond=0) + self.lifetime
            return httpx.Response(
                201, json={"token": TOKEN, "expires_at": expires_at.isoformat().replace("+00:00", "Z")}
            )
        return httpx.Response(404, json={"message": "Not Found"})


@pytest.fixture
def fake_github(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeGitHub]:
    """This deployment's GitHub App, installed on vivarium-collective's v2ecoli and viva-basic-processes, its key on
    disk where the API reads it, and no token cached by another test."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path = tmp_path / "github-app.pem"
    path.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    github = FakeGitHub(key, {"vivarium-collective": {"v2ecoli", "viva-basic-processes"}})
    monkeypatch.setattr(source_credentials, "transport", httpx.MockTransport(github.handle))
    monkeypatch.setattr(source_credentials, "_tokens", {})
    with override_settings(github_app_id=APP_ID, github_app_key_file=str(path)):
        yield github


class RecordingBuilds:
    """The Kubernetes side of `build_k8s.K8sBuilds`, recorded in order: each Job (created with ``JOB_UID``), Secret and
    deletion. Every Job completes, its one container printing ``log``; ``refuse_secrets`` makes creating a Secret fail
    as the API server would refuse it."""

    def __init__(self, log: str = "", refuse_secrets: bool = False) -> None:
        self.log = log
        self.refuse_secrets = refuse_secrets
        self.calls: list[tuple[str, Any]] = []

    def create(self, job: Any) -> Any:
        self.calls.append(("job", job))
        created = copy.deepcopy(job)
        created.metadata.uid = JOB_UID
        return created

    def create_secret(self, secret: Any) -> None:
        if self.refuse_secrets:
            from kubernetes.client.exceptions import ApiException

            raise ApiException(status=403, reason="Forbidden")
        self.calls.append(("secret", secret))

    def delete(self, name: str) -> None:
        self.calls.append(("delete", name))

    def state(self, name: str) -> tuple[str, str]:
        return "completed", ""

    def container_log(self, name: str, container: str) -> str:
        return self.log

    def of(self, kind: str) -> list[Any]:
        return [value for k, value in self.calls if k == kind]


def serialized(value: Any) -> str:
    """A Kubernetes object as the API server receives it."""
    from kubernetes.client import ApiClient

    return json.dumps(ApiClient().sanitize_for_serialization(value))  # type: ignore[no-untyped-call]
