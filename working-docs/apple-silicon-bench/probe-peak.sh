#!/usr/bin/env bash
# Week 0.5 — find the PEAK num-envs this Mac can hold, and whether throughput
# keeps climbing toward the official 4096-env training config.
#
# Shorter ladder (10 iters) because this is a scaling probe, not the timing
# reference. Samples the whole process tree RSS so a memory ceiling shows up as
# data instead of an OOM kill.
#
# Usage: ./probe-peak.sh 1024 2048 4096
set -uo pipefail

RL="$HOME/Projects/microduck-build/reference/microduck-lab/microduck_rl"
OUT="$(cd "$(dirname "$0")" && pwd)/logs"
ITERS="${ITERS:-10}"
mkdir -p "$OUT"

# Recursively list $1 and all its descendants.
tree() {
  echo "$1"
  local c
  for c in $(pgrep -P "$1" 2>/dev/null); do tree "$c"; done
}

for N in "$@"; do
  log="$OUT/peak-${N}.log"
  memlog="$OUT/peak-${N}.mem"
  echo "=== num_envs=$N iters=$ITERS ==="
  start=$(date +%s)
  ( cd "$RL" && CUDA_VISIBLE_DEVICES="" WANDB_MODE=disabled \
      uv run train Mjlab-Velocity-Flat-MicroDuck \
        --env.scene.num-envs "$N" --agent.max_iterations "$ITERS" ) >"$log" 2>&1 &
  pid=$!
  peak=0
  while kill -0 "$pid" 2>/dev/null; do
    rss=$(ps -o rss= -p "$(tree "$pid" | tr '\n' ',' | sed 's/,$//')" 2>/dev/null \
          | awk '{s+=$1} END {print s+0}')
    [ "${rss:-0}" -gt "$peak" ] && peak=$rss
    echo "$rss" >>"$memlog"
    sleep 2
  done
  wait "$pid"; rc=$?
  end=$(date +%s)
  echo "exit=$rc wall=$((end-start))s peak_rss=$((peak/1024))MB log=$log"
done
