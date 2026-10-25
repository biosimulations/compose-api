"""A shared environment version's Apptainer definition (docs/plan-environment-versions.md, V2, step 3).

compose-api owns this template, which used to be pbest's (``generate_container_def_file``). The layout and the
runscript are pbest's, so the image runs jobs exactly as before (runtime contract 1, V6): a micromamba environment at
``/micromamba_env/runtime_env`` and ``/runtime/pbest/main.py`` from the pbest release cloned at ``/runtime``. What
changes is how packages arrive: conda-forge first (Python and the conda libraries), then every PyPI package from the
version's lock, exactly, with ``--no-deps``. The lock is in the definition, so the definition's hash, the simulator's
identity, changes exactly when the lock does.
"""

from pbest.utils.input_types import ContainerizationEngine, ContainerizationFileRepr

from compose_api.environments.lock import PBEST_REPOSITORY, PYTHON_VERSION, Lock, SharedSpec

ENV_PATH = "/micromamba_env/runtime_env"
RUNTIME_CONTRACT = 1  # the runscript below; a change to it is a new contract

_TEMPLATE = """\
Bootstrap: docker
From: astral/uv:python{python}-bookworm-slim
Stage: spython-base

%post

apt update
apt upgrade -y
apt install -y git curl bzip2

# the runtime: pbest's entry point, which the runscript runs
git clone --branch {pbest} {pbest_repository}.git /runtime

mkdir -p /usr/local/bin
cd /usr/local/bin
curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xvj bin/micromamba --strip-components=1
cd /
mkdir /micromamba_env
micromamba create -p {env} -c conda-forge python={python} {conda}--yes

# every PyPI package, transitive ones included, exactly as locked
cat > /runtime/environment.lock <<'COMPOSE_API_LOCK'
{lock}COMPOSE_API_LOCK
uv pip install --python {env}/bin/python --no-deps -r /runtime/environment.lock

%runscript
cd /
exec micromamba run -p {env} python3 /runtime/pbest/main.py "$@"
%startscript
cd /
exec micromamba run -p {env} python3 /runtime/pbest/main.py "$@"
"""


def shared_definition(spec: SharedSpec, lock: Lock) -> ContainerizationFileRepr:
    """The definition of a shared version made from ``spec`` and resolved as ``lock``."""
    if spec.pbest is None:
        raise ValueError("a shared environment needs the pbest release its runtime comes from")
    text = lock.text if lock.text.endswith("\n") else lock.text + "\n"
    conda = "".join(f"{package} " for package in spec.conda())
    representation = _TEMPLATE.format(
        python=PYTHON_VERSION, pbest=spec.pbest, pbest_repository=PBEST_REPOSITORY, env=ENV_PATH, conda=conda, lock=text
    )
    return ContainerizationFileRepr(
        representation=representation, containerization_engine=ContainerizationEngine.APPTAINER
    )
