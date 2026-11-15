#!/usr/bin/env bash
set -euo pipefail
umask 077
: "${TACC_WORKDIR:?Submit with tcloud submit}"
: "${TACC_USERDIR:?Submit with tcloud submit}"
: "${SLURM_JOB_ID:?Submit with tcloud submit}"
: "${CONDA_PREFIX:?SDK must activate the course management environment}"
test "$CONDA_PREFIX" = /mnt/home/public/course-envs/CSIT6000V/assignment1/mpi-gemm-v1

source /mnt/home/public/course-envs/CSIT6000V/project/activate.sh
cd "$TACC_WORKDIR"
mkdir -p -m 700 data

test -f server-url.txt
export QWEN_BASE_URL="$(tr -d '[:space:]' < server-url.txt)"
case "$QWEN_BASE_URL" in
  ''|*NODE*) echo "Set server-url.txt to the running model service URL." >&2; exit 1 ;;
esac
export APP_HOST=0.0.0.0
export APP_PORT="${APP_PORT:-8001}"
export QWEN_MODEL="${QWEN_MODEL:-qwen3.8-27b}"

# mpi-gemm-v1 is only the SDK bootstrap env and has no Python.
# Use the personal conda env for the application runtime.
APP_PYTHON="${APP_PYTHON:-$HOME/.Miniconda3/envs/trip-planning-agent/bin/python}"
if [[ ! -x "$APP_PYTHON" ]]; then
  echo "Missing application Python at $APP_PYTHON" >&2
  exit 1
fi

"$APP_PYTHON" -m pip install --quiet -r requirements.txt
hostname
printf "APP_BASE_URL=http://%s:%s\n" "$(hostname)" "$APP_PORT"
"$APP_PYTHON" -m uvicorn backend.main:app --host "$APP_HOST" --port "$APP_PORT"
