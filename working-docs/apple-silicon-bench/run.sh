#!/usr/bin/env bash
# Week 0.5 — Apple Silicon throughput benchmark for microduck_rl.
#
# Runs the OFFICIAL MicroDuck velocity task on this Mac through mjlab's own CPU
# mode (CUDA_VISIBLE_DEVICES="" -> select_gpus() returns (None, 0); mjlab/utils/gpu.py:56).
# Wandb is disabled because no API key is configured on this box; it is a logging
# sink only and does not affect physics or throughput.
#
# Runs the env-count ladder SEQUENTIALLY on purpose: concurrent runs contend for
# the same CPU and would make steps/sec meaningless.
#
# Usage: ./run.sh 64 256 512
set -uo pipefail

RL="$HOME/Projects/microduck-build/microduck-lab/microduck_rl"
OUT="$(cd "$(dirname "$0")" && pwd)/logs"
ITERS="${ITERS:-50}"
mkdir -p "$OUT"

for N in "$@"; do
  log="$OUT/envs-${N}.log"
  echo "=== num_envs=$N iters=$ITERS ==="
  start=$(date +%s)
  ( cd "$RL" && CUDA_VISIBLE_DEVICES="" WANDB_MODE=disabled \
      uv run train Mjlab-Velocity-Flat-MicroDuck \
        --env.scene.num-envs "$N" --agent.max_iterations "$ITERS" ) >"$log" 2>&1
  rc=$?
  end=$(date +%s)
  echo "exit=$rc wall=$((end-start))s log=$log"
done
