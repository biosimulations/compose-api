# ruff: noqa: E501  (the job script's JSON lines are longer than Python's)
"""The sbatch script for one simulation run, as a pure function so its text can be tested.

Besides running the simulator, the script makes the run observable (docs/plan-observability.md O2, O3):

- **It records the job itself** in ``events/job.jsonl``: a ``job`` span that every other span of the run hangs from,
  ``job.start``, and ``job.end`` with the exit code. They're written from an ``EXIT`` trap, so a failure that
  ``set -e`` turns into an early exit is recorded too, and SIGTERM (a time limit, ``scancel``) exits through it.
- **It announces the files the run left** (O5): after the run, success or failure, one ``artifact.written`` event per
  file under ``output/`` and for ``results.zip``, with its size and sha256. ``output/`` is kept.
- **It hands the trace context to the simulator** through an env file: ``PBG_TRACEPARENT`` and friends. A simulator
  built on process-bigraph >= 1.8.5 writes its events to ``events/engine-{source}.jsonl``: one file per engine
  process with releases that expand ``{source}`` (process-bigraph#229), one literally named file with older ones; the
  ingester reads every ``*.jsonl``. Any other simulator ignores the variables.
- **Its SLURM log is a dataset** (``job.out`` in the experiment directory, kind ``log``), announced without a size or
  checksum because SLURM keeps writing it after the trap.

Every line is one JSON object in process-bigraph's event schema (v1), so one ingester reads both files.
"""

from dataclasses import dataclass

from compose_api.observability.identity import job_span_id, trace_id_from_correlation

_TEMPLATE = r"""#!/bin/bash
#SBATCH --job-name=@@JOB_NAME@@
#SBATCH --time=30:00
#SBATCH --cpus-per-task @@CPUS@@
#SBATCH --mem=@@MEM@@
#SBATCH --partition=@@PARTITION@@
#SBATCH --qos=@@QOS@@
#SBATCH --output=@@LOG_FILE@@
@@NODELIST@@
set -e

EXPERIMENT=@@EXPERIMENT_DIR@@
EVENTS="$EXPERIMENT/events"
mkdir -p "$EXPERIMENT/output" "$EVENTS"

# The run's trace (docs/plan-observability.md O2, O3).
TRACE_ID=@@TRACE_ID@@
JOB_SPAN=@@JOB_SPAN@@
JOB_SOURCE="job-${SLURM_JOB_ID:-0}"
JOB_SEQ=0
now_ts() { local t; t=$(date -u +%Y-%m-%dT%H:%M:%S.%N); echo "${t:0:23}Z"; }  # milliseconds, any date(1) with %N
JOB_START_TS=$(now_ts)
JOB_START_S=$(date +%s.%N)
emit() {  # emit EVENT LEVEL PAYLOAD_JSON
    JOB_SEQ=$((JOB_SEQ + 1))
    printf '{"v":1,"ts":"%s","seq":%d,"source":"%s","component":"compose_api.job","event":"%s","level":"%s","trace_id":"%s","span_id":"%s","parent_span_id":null,"payload":%s}\n' \
        "$(now_ts)" "$JOB_SEQ" "$JOB_SOURCE" "$1" "$2" "$TRACE_ID" "$JOB_SPAN" "$3" >> "$EVENTS/job.jsonl" || true
}
JOB_ATTRS="{\"slurm_job_id\":\"${SLURM_JOB_ID:-}\",\"host\":\"$(hostname)\"}"
json_escape() { local s=${1//\\/\\\\}; printf '%s' "${s//\"/\\\"}"; }
sha256_of() {
    if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi
}
dir_bytes() {  # GNU du -sb on the cluster; du -sk elsewhere (macOS), to the nearest KiB
    local b; b=$(du -sb "$1" 2>/dev/null | cut -f1)
    [ -n "$b" ] || b=$(( $(du -sk "$1" | cut -f1) * 1024 ))
    echo "$b"
}
manifest() {  # one artifact.written per file the run left: what it wrote under output/, and the results archive
    # A zarr store (a *.fenics results bundle or a *.zarr) is ONE dataset, read file by file through
    # /datasets/{id}/files/ (docs/plan-viewers.md F1): announced with its total size and no checksum.
    local f size sum
    # The API serves these files as another user: a producer's restrictive mode (e.g. a 0600 mkstemp file renamed into
    # place) must not hide one, or the file route fails mid-response (simulation 4570).
    chmod -R a+rX "$EXPERIMENT/output" 2>/dev/null || true
    while IFS= read -r f; do
        if [ -d "$EXPERIMENT/$f" ]; then
            emit artifact.written info "{\"uri\":\"$(json_escape "$f")\",\"bytes\":$(dir_bytes "$EXPERIMENT/$f")}"
            continue
        fi
        size=$(wc -c < "$EXPERIMENT/$f" | tr -d ' ')
        sum=$(sha256_of "$EXPERIMENT/$f")
        emit artifact.written info "{\"uri\":\"$(json_escape "$f")\",\"bytes\":$size,\"sha256\":\"$sum\"}"
    done < <(cd "$EXPERIMENT" && {
        find output \( -type d \( -name '*.fenics' -o -name '*.zarr' \) -prune -print \) -o -type f -print 2>/dev/null
        [ -f results.zip ] && echo results.zip
    } | LC_ALL=C sort)
    # SLURM keeps appending to the log after this trap, so it is announced without a size or checksum.
    emit artifact.written info '{"uri":"job.out","kind":"log","name":"SLURM log"}'
}
finish() {
    code=$?
    trap - EXIT
    manifest || true
    elapsed=$(awk -v a="$JOB_START_S" -v b="$(date +%s.%N)" 'BEGIN { printf "%.3f", b - a }')
    if [ "$code" -eq 0 ]; then status=ok; level=info; error=null
    else status=error; level=error; error="\"exit code $code\""; fi
    emit job.end "$level" "{\"exit_code\":$code,\"wall_s\":$elapsed}"
    emit span.end "$level" "{\"name\":\"job\",\"attrs\":$JOB_ATTRS,\"start_ts\":\"$JOB_START_TS\",\"end_ts\":\"$(now_ts)\",\"duration_s\":$elapsed,\"status\":\"$status\",\"error\":$error}"
    exit "$code"
}
trap finish EXIT
trap 'exit 143' TERM
emit span.start info "{\"name\":\"job\",\"attrs\":$JOB_ATTRS,\"start_ts\":\"$JOB_START_TS\"}"
emit job.start info "$JOB_ATTRS"

cat > "$EVENTS/pbg.env" <<'PBG_ENV'
PBG_TRACEPARENT=00-@@TRACE_ID@@-@@JOB_SPAN@@-01
PBG_TRACE_BAGGAGE=simulation_id=@@SIMULATION_ID@@,experiment_id=@@EXPERIMENT_ID@@
PBG_EVENT_TAGS=backend=slurm
PBG_EVENT_SINKS=file:/experiment/events/engine-{source}.jsonl
PBG_ENV

echo "Simulation @@JOB_NAME@@ running."
singularity run \
    --compat \
    --env-file "$EVENTS/pbg.env" \
    --bind "$EXPERIMENT":/experiment \
    @@CONTAINER@@ \
    run \
    /experiment/@@JOB_NAME@@.@@SUFFIX@@ \
    -o "@@OUTPUT_DIR@@" \
    -n @@END_TIME@@

# output/ stays: each file in it is a dataset (docs/plan-observability.md O5). results.zip keeps the archive endpoint.
(cd "$EXPERIMENT/output" && zip -r ../results.zip ./*)
echo "Simulation run completed. data saved to $EXPERIMENT."
"""


@dataclass(frozen=True)
class SimulationJob:
    job_name: str
    experiment_id: str
    simulation_id: int
    correlation_id: str
    experiment_dir: str
    container: str
    file_suffix: str
    output_dir: str
    end_time: float
    log_file: str
    is_batch: bool
    partition: str
    qos: str
    node_list: str = ""


def simulation_job_script(job: SimulationJob) -> str:
    values = {
        "JOB_NAME": job.job_name,
        "CPUS": "1" if job.is_batch else "2",
        "MEM": "1GB" if job.is_batch else "8GB",
        "PARTITION": job.partition,
        "QOS": job.qos,
        "LOG_FILE": job.log_file,
        "NODELIST": f"#SBATCH --nodelist={job.node_list}" if job.node_list else "",
        "EXPERIMENT_DIR": job.experiment_dir,
        "TRACE_ID": trace_id_from_correlation(job.correlation_id),
        "JOB_SPAN": job_span_id(job.correlation_id),
        "SIMULATION_ID": str(job.simulation_id),
        "EXPERIMENT_ID": job.experiment_id,
        "CONTAINER": job.container,
        "SUFFIX": job.file_suffix,
        "OUTPUT_DIR": job.output_dir,
        "END_TIME": str(job.end_time),
    }
    script = _TEMPLATE
    for key, value in values.items():
        script = script.replace(f"@@{key}@@", value)
    return script
