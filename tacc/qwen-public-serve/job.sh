#!/usr/bin/env bash
set -euo pipefail
umask 077
: "${TACC_WORKDIR:?Submit with tcloud submit}"
: "${TACC_USERDIR:?Submit with tcloud submit}"
: "${SLURM_JOB_ID:?Submit with tcloud submit}"
: "${CONDA_PREFIX:?SDK must activate the course management environment}"
# CONDA_PREFIX path may vary by environment

source /mnt/home/public/course-envs/CSIT6000V/project/activate.sh
trap 'rm -rf -- "${QWEN_RUN_DIR:-}"' EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
export QWEN_CACHE_HOME="$TACC_USERDIR/CSIT6000V-project-cache"
mkdir -p -m 700 "$QWEN_CACHE_HOME"
hostname
printf 'SERVICE_BASE_URL=http://%s:8000/v1\n' "$(hostname)"
export CUDA_VISIBLE_DEVICES=0,1
# Official serve.sh does not enable tool calling; vLLM then rejects
# requests that include tools with HTTP 400. Keep the course runtime
# and model flags, and add the Qwen3 tool parser.
bash "$QWEN_PROJECT_ROOT/runtime.sh" "$QWEN_PROJECT_ROOT/vllm-env/bin/python" \
    -m vllm.entrypoints.openai.api_server \
    --model "$QWEN_PROJECT_ROOT/models/Qwen3.8-27B-AWQ-INT4" \
    --served-model-name qwen3.8-27b \
    --safetensors-load-strategy prefetch \
    --host 0.0.0.0 --port 8000 \
    --tensor-parallel-size 2 --language-model-only --dtype bfloat16 \
    --gpu-memory-utilization 0.90 --max-model-len 32768 \
    --max-num-seqs 4 --max-num-batched-tokens 4096 \
    --reasoning-parser qwen3 --enable-prefix-caching \
    --enable-auto-tool-choice --tool-call-parser qwen3_xml
