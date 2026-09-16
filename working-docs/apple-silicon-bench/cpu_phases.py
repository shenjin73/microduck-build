#!/usr/bin/env python3
"""Why does train-walk average ~5 cores on an 18-core M5 Max?

`ps -o %cpu` is a decaying average, so it smooths away the PPO phase structure.
This measures true instantaneous parallelism: sample the process tree's
CUMULATIVE cpu time and take delta(cpu)/delta(wall) between samples.

That reports, per interval, how many cores were actually busy -- which is what
exposes the rollout (parallel, worker-bound) vs update (serial, trainer-bound)
alternation, and the single-threaded startup.
"""
import re
import subprocess
import sys
import time

CMD = ["uv", "run", "train-walk", "--envs", "32", "--steps", "1_000_000",
       "--run-name", "_cpu_probe"]


def descendants(pid):
    out = [pid]
    try:
        kids = subprocess.run(["pgrep", "-P", str(pid)], capture_output=True,
                              text=True).stdout.split()
    except Exception:
        return out
    for k in kids:
        out.extend(descendants(int(k)))
    return out


def parse_cputime(s):
    """'MM:SS.ss' or 'HH:MM:SS.ss' -> seconds."""
    parts = s.strip().split(":")
    try:
        parts = [float(p) for p in parts]
    except ValueError:
        return 0.0
    secs = 0.0
    for p in parts:
        secs = secs * 60 + p
    return secs


def cpu_seconds(pid):
    pids = ",".join(str(p) for p in descendants(pid))
    out = subprocess.run(["ps", "-o", "time=", "-p", pids],
                         capture_output=True, text=True).stdout
    return sum(parse_cputime(l) for l in out.splitlines() if l.strip())


def main():
    t0 = time.time()
    proc = subprocess.Popen(CMD, stdout=open("/tmp/cpu_probe2.log", "w"),
                            stderr=subprocess.STDOUT)
    pid = proc.pid
    samples = []          # (wall_since_start, cumulative_cpu_s, inst_cores)
    prev_cpu, prev_wall = 0.0, 0.0
    while proc.poll() is None:
        time.sleep(0.5)
        wall = time.time() - t0
        cpu = cpu_seconds(pid)
        # Guard against the window where the tree is briefly invisible.
        inst = (cpu - prev_cpu) / (wall - prev_wall) if wall > prev_wall else 0.0
        samples.append((wall, cpu, max(inst, 0.0)))
        prev_cpu, prev_wall = cpu, wall
    proc.wait()
    total_wall = time.time() - t0
    total_cpu = cpu_seconds(pid) if False else prev_cpu

    print(f"total wall {total_wall:.1f}s   total cpu {total_cpu:.1f}s   "
          f"average {total_cpu / total_wall:.2f} cores\n")

    vals = [s[2] for s in samples]
    if not vals:
        return
    vals_sorted = sorted(vals)
    n = len(vals_sorted)
    print(f"instantaneous cores: peak {max(vals):.2f}  "
          f"p50 {vals_sorted[n // 2]:.2f}  p90 {vals_sorted[int(n * 0.9)]:.2f}  "
          f"min {min(vals):.2f}\n")
    print("timeline (1 row per 2 samples = 1 s):")
    for i in range(0, len(samples), 2):
        w, _c, inst = samples[i]
        print(f"  t={w:5.1f}s  {inst:5.2f} cores  {'#' * int(inst * 3)}")

    with open("/tmp/cpu_series2.txt", "w") as fh:
        for w, _c, inst in samples:
            fh.write(f"{w:.1f} {inst:.3f}\n")
    print("\nseries -> /tmp/cpu_series2.txt")


if __name__ == "__main__":
    sys.exit(main())
