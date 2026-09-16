#!/usr/bin/env bash
# Times each Week 4/5 command from the clone plan on this Mac.
# Full output goes to /tmp/w45-*.log; only timings are printed here.
set -uo pipefail
cd "$HOME/Projects/microduck-build/microduck-lab/microduck_local"
L=/tmp/w45

run() {                    # run <label> <cmd...>
  local label="$1"; shift
  local log="$L-$(echo "$label" | tr ' /' '__').log"
  local t0=$(date +%s.%N)
  "$@" >"$log" 2>&1
  local rc=$?
  local t1=$(date +%s.%N)
  printf '%-46s %7.1fs  rc=%s\n' "$label" "$(echo "$t1 - $t0" | bc)" "$rc"
}

run "W4 pytest (3 contract files)" \
  uv run --with pytest pytest tests/test_env_contract.py tests/test_walk_env_physics.py tests/test_bam_actuator.py -q -p no:cacheprovider
run "W4 render-rollout (shipped alpha)" \
  uv run render-rollout --policy ../microduck/policies/alpha_walking.onnx --behavior run --out /tmp/rr-alpha
run "W5 export-walk (1M-step run)" \
  uv run export-walk runs/_bench_e16
run "W5 render-rollout (trained 1M run)" \
  uv run render-rollout --policy runs/_bench_e16/policy.onnx --behavior run --out /tmp/rr-bench
run "W5 distill (from shipped alpha)" \
  uv run distill --teacher ../microduck/policies/alpha_walking.onnx --run-name _bench_distill
run "W5 export-walk (distilled)" \
  uv run export-walk runs/_bench_distill
