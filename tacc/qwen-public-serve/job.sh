#!/usr/bin/env bash
set -euo pipefail
umask 077
: "${TACC_WORKDIR:?Submit with tcloud submit}"
: "${TACC_USERDIR:?Submit with tcloud submit}"
: "${SLURM_JOB_ID:?Submit with tcloud submit}"
: "${CONDA_PREFIX:?SDK must activate the course management environment}"
test "$CONDA_PREFIX" = /mnt/home/public/course-envs/TACC6000V/assignment1/mpi-gemm-v1 \
  || test "$CONDA_PREFIX" = /mnt/home/public/course-envs/CSIT6000V/assignment1/mpi-gemm-v1

source /mnt/home/public/course-envs/CSIT6000V/project/activate.sh
trap 'rm -rf -- "${QWEN_RUN_DIR:-}"' EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
export QWEN_CACHE_HOME="$TACC_USERDIR/CSIT6000V-project-cache"
mkdir -p -m 700 "$QWEN_CACHE_HOME"
hostname
printf 'SERVICE_BASE_URL=http://%s:8000/v1\n' "$(hostname)"
bash "$QWEN_PROJECT_ROOT/serve.sh"
