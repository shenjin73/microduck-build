#!/usr/bin/env python3
"""Week 0.5 follow-up: what could MPS actually buy on this M5 Max?

The physics runs in MuJoCo Warp, whose macOS wheel has no Metal backend (and
mujoco_warp checks for a CUDA toolkit/driver), so the rollout can only run on
CPU. That leaves the PPO update — a ~200k-param MLP — as the only MPS-eligible
work. This script times exactly the network work one training iteration
performs, using the real shapes from the run logs:

    actor   61 -> 512 -> 256 -> 128 -> 14
    critic  76 -> 512 -> 256 -> 128 -> 1
    num_steps_per_env=24, num_learning_epochs=5, num_mini_batches=4

and compares it against the measured wall-clock iteration time (13.04 s at
512 envs) to bound MPS's possible speedup.
"""
import time

import torch
import torch.nn as nn

ENVS = 512
STEPS_PER_ENV = 24
EPOCHS = 5
MINIBATCHES = 4
BATCH = ENVS * STEPS_PER_ENV          # 12288 transitions per iteration
MINIBATCH = BATCH // MINIBATCHES      # 3072 per gradient step


def mlp(i, h, o):
    return nn.Sequential(
        nn.Linear(i, h[0]), nn.ELU(),
        nn.Linear(h[0], h[1]), nn.ELU(),
        nn.Linear(h[1], h[2]), nn.ELU(),
        nn.Linear(h[2], o),
    )


def bench(device, reps=3):
    dev = torch.device(device)
    torch.manual_seed(0)
    actor = mlp(61, (512, 256, 128), 14).to(dev)
    critic = mlp(76, (512, 256, 128), 1).to(dev)
    opt = torch.optim.Adam(list(actor.parameters()) + list(critic.parameters()), lr=1e-3)

    obs_a = torch.randn(BATCH, 61, device=dev)
    obs_c = torch.randn(BATCH, 76, device=dev)

    def iteration():
        # (a) rollout inference: one forward per env-step, batched over envs
        with torch.no_grad():
            for _ in range(STEPS_PER_ENV):
                actor(obs_a[:ENVS])
        # (b) PPO update: epochs x minibatches of forward+backward
        for _ in range(EPOCHS):
            for mb in torch.randperm(BATCH, device=dev).split(MINIBATCH):
                loss = actor(obs_a[mb]).pow(2).mean() + critic(obs_c[mb]).pow(2).mean()
                opt.zero_grad(set_to_none=True)
                loss.backward()
                opt.step()

    iteration()  # warm up / JIT
    if dev.type == "mps":
        torch.mps.synchronize()
    times = []
    for _ in range(reps):
        t = time.perf_counter()
        iteration()
        if dev.type == "mps":
            torch.mps.synchronize()
        times.append(time.perf_counter() - t)
    return min(times)


def main():
    print(f"batch/iteration={BATCH}  minibatch={MINIBATCH}  "
          f"grad steps/iteration={EPOCHS * MINIBATCHES}")
    print(f"rollout forwards/iteration={STEPS_PER_ENV} (batch {ENVS})\n")
    results = {}
    for dev in ("cpu", "mps"):
        if dev == "mps" and not torch.backends.mps.is_available():
            print("mps: not available"); continue
        results[dev] = bench(dev)
        print(f"{dev:>4}: {results[dev] * 1000:8.1f} ms per iteration of network work")
    if "cpu" in results and "mps" in results:
        speedup = results["cpu"] / results["mps"]
        print(f"\nMPS network speedup: {speedup:.2f}x")
        measured_iter = 13.04  # s/iter at 512 envs, from logs/envs-512.log
        share = results["cpu"] / measured_iter
        print(f"CPU network work is {share * 100:.2f}% of the measured "
              f"{measured_iter} s iteration")
        best_case = measured_iter - results["cpu"] + results["mps"]
        print(f"Best-case iteration with MPS: {best_case:.3f} s "
              f"({measured_iter / best_case:.3f}x, i.e. "
              f"{(1 - best_case / measured_iter) * 100:.2f}% faster)")
        print(f"Physics (untouched, CPU-only) = {measured_iter - results['cpu']:.2f} s "
              f"= {(measured_iter - results['cpu']) / measured_iter * 100:.2f}% of the iteration")


if __name__ == "__main__":
    main()
