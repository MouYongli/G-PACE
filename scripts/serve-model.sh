#!/usr/bin/env bash
# Start one OpenAI-compatible vLLM server from the serving environment (decision D004).
#
#   GPUS=2 PORT=8001 scripts/serve-model.sh Qwen/Qwen3-8B [extra vllm serve arguments...]
#
# GPUS     CUDA_VISIBLE_DEVICES for this server (required; agree on GPUs before use, the machine is shared)
# PORT     listening port (default 8000)
# Weights are read from the Hugging Face cache (HF_HOME, default ~/.cache/huggingface).
# Record the model revision, vLLM, torch and CUDA versions in run.json for every formal run.
set -euo pipefail

model="${1:?usage: GPUS=<ids> [PORT=8000] $0 <model> [vllm args...]}"
shift
: "${GPUS:?set GPUS to the GPU ids reserved for this server, e.g. GPUS=2}"
port="${PORT:-8000}"

root="$(git rev-parse --show-toplevel)"
venv="$root/envs/serve/.venv"
[[ -x "$venv/bin/vllm" ]] || { echo "serving environment missing; run: make setup-serve" >&2; exit 1; }

export CUDA_VISIBLE_DEVICES="$GPUS"
# Tools that vLLM calls at run time (ninja for the FlashInfer JIT kernels) live in the serving venv.
export PATH="$venv/bin:$PATH"
exec "$venv/bin/vllm" serve "$model" --port "$port" --enable-prefix-caching "$@"
