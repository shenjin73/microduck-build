"""Can the Microduck jump under its honest BAM XL330 actuator model?

This is a feasibility probe, not an RL score.  It commands a symmetric
crouch -> fast extension trajectory, scans its depth and timing, and measures
whether *both* feet really leave the floor.  Run this before spending another
PPO job on a jump reward:

    uv run python scripts/probe_bunny_jump.py
    uv run python scripts/probe_bunny_jump.py --actuator bam --seeds 0,1,2,3,4

A candidate passes only when every requested seed clears both feet by at least
1 cm.  BAM torque is sampled at every 5 ms physics substep; the report includes
clamp duty and the longest continuous clamp interval so a simulated jump is
not called feasible by quietly asking the servos for impossible sustained
stall torque.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from itertools import product
from pathlib import Path

import numpy as np

from microduck_local import contract as C
from microduck_local.walk_env import MicroduckWalkEnv

# Positive amount follows the editor's symmetric `squat` rig direction.
_SQUAT_COEF = np.zeros(C.NUM_JOINTS, np.float32)
_SQUAT_COEF[[2, 3, 4, 11, 12, 13]] = (-1.0, -2.0, -1.0, 1.0, 2.0, 1.0)


@dataclass
class Trial:
    actuator: str
    seed: int
    depth: float
    crouch_s: float
    extend_s: float
    overshoot: float
    head_throw: float
    flight_s: float
    landing_frac: float
    crouch_drop_m: float
    clearance_m: float
    airborne_s: float
    peak_vz_mps: float
    peak_tilt_deg: float
    final_tilt_deg: float
    landed_upright: bool
    peak_torque_nm: float
    torque_clamp_duty: float
    longest_clamp_s: float


def squat_action(amount: float, head_throw: float = 0.0) -> np.ndarray:
    """Deployment-contract target for a symmetric squat plus head throw."""
    action = _SQUAT_COEF * np.float32(amount)
    # Moving both pitch joints together translates the 38%-of-body-mass head;
    # the leg-only scan launched but pitched over, so both signs are searched.
    action[5] += np.float32(head_throw)
    action[6] += np.float32(head_throw)
    return action


class TorqueWatch:
    """Sample BAM torque at the 5 ms physics rate, including clamp duration."""

    def __init__(self, env: MicroduckWalkEnv):
        self.env = env
        self.peak = 0.0
        self.n = 0
        self.clamped = 0
        self.run = 0
        self.longest = 0
        if env.bam is None:
            self.limit = float(np.max(np.abs(env.model.actuator_forcerange)))
            return
        force_limit = np.asarray(env.bam.force_limit, float)
        self.limit = float(np.max(force_limit))
        original = env.bam.before_step

        def watched():
            tau = original()
            self.sample(np.asarray(tau, float))
            return tau

        env.bam.before_step = watched

    def reset(self) -> None:
        self.peak = 0.0
        self.n = self.clamped = self.run = self.longest = 0

    def sample(self, torque: np.ndarray) -> None:
        self.n += 1
        self.peak = max(self.peak, float(np.max(np.abs(torque))))
        at_clamp = bool(np.any(np.abs(torque) >= 0.95 * self.limit))
        self.clamped += int(at_clamp)
        self.run = self.run + 1 if at_clamp else 0
        self.longest = max(self.longest, self.run)

    @property
    def duty(self) -> float:
        return self.clamped / max(self.n, 1)


def _linspace_steps(start: float, end: float, seconds: float):
    n = max(1, round(seconds / C.CTRL_DT))
    for i in range(1, n + 1):
        yield start + (end - start) * i / n


def run_trial(env: MicroduckWalkEnv, watch: TorqueWatch, *, actuator: str,
              seed: int, depth: float, crouch_s: float, extend_s: float,
              overshoot: float, head_throw: float, flight_s: float,
              landing_frac: float) -> Trial:
    env.reset(seed=seed)
    watch.reset()
    zero = squat_action(0.0)

    # Settle from reset's tiny joint perturbation before defining floor zero.
    for _ in range(round(0.8 / C.CTRL_DT)):
        env.step(zero)
    foot_zero = {side: float(env.data.geom_xpos[gid][2])
                 for side, gid in env.foot_geoms.items()}
    stand_z = float(env._trunk_xpos[2])

    for amount in _linspace_steps(0.0, depth, crouch_s):
        env.step(squat_action(amount))
    for _ in range(round(0.06 / C.CTRL_DT)):
        env.step(squat_action(depth))
    crouch_drop = stand_z - float(env._trunk_xpos[2])

    clearance = -1.0
    airborne_steps = airborne_run = longest_air = 0
    airborne_seen = False
    upright_landing_run = 0
    landed_stably = False
    peak_vz = -np.inf
    peak_tilt = 0.0

    def measure() -> None:
        nonlocal clearance, airborne_steps, airborne_run, longest_air
        nonlocal airborne_seen, upright_landing_run, landed_stably
        nonlocal peak_vz, peak_tilt
        contacts = env._foot_contacts()
        airborne = not contacts["left"] and not contacts["right"]
        airborne_steps += int(airborne)
        airborne_run = airborne_run + 1 if airborne else 0
        longest_air = max(longest_air, airborne_run)
        airborne_seen = airborne_seen or airborne
        clearance = max(clearance, min(
            float(env.data.geom_xpos[env.foot_geoms[side]][2]) - foot_zero[side]
            for side in ("left", "right")))
        peak_vz = max(peak_vz, float(env.data.qvel[env._root_qvel + 2]))
        g = env._projected_gravity()
        tilt = float(np.degrees(np.arccos(np.clip(-g[2], -1.0, 1.0))))
        if not landed_stably:
            peak_tilt = max(peak_tilt, tilt)
        upright_touchdown = (airborne_seen and contacts["left"] and contacts["right"]
                             and tilt <= 30.0 and float(env._trunk_xpos[2]) >= 0.09)
        upright_landing_run = upright_landing_run + 1 if upright_touchdown else 0
        # Ten consecutive control ticks: not a one-frame contact on the way
        # into a face-plant, but a 200 ms landing another hop could launch from.
        landed_stably = landed_stably or upright_landing_run >= 10

    # Overshooting slightly beyond the stand pose is part of the scan: merely
    # returning to stand produced no jump in the first hand probe.
    for i, amount in enumerate(_linspace_steps(depth, -overshoot, extend_s), 1):
        n = max(1, round(extend_s / C.CTRL_DT))
        env.step(squat_action(amount, head_throw * i / n))
        measure()
    for _ in range(round(flight_s / C.CTRL_DT)):
        env.step(squat_action(-overshoot, head_throw))
        measure()
    landing_depth = depth * landing_frac
    landing = list(_linspace_steps(-overshoot, landing_depth, 0.10))
    for i, amount in enumerate(landing, 1):
        env.step(squat_action(amount, head_throw * (1.0 - i / len(landing))))
        measure()
    for _ in range(round(0.20 / C.CTRL_DT)):
        env.step(squat_action(landing_depth))
        measure()
    recovery = list(_linspace_steps(landing_depth, 0.0, 0.30))
    for amount in recovery:
        env.step(squat_action(amount))
        measure()
    for _ in range(round(0.30 / C.CTRL_DT)):
        env.step(zero)
        measure()

    # XML torque is published once per control step rather than through the
    # BAM watcher; include its peak for shape, but clamp duration is BAM-only.
    if env.bam is None:
        watch.peak = float(np.max(np.abs(env.data.actuator_force)))

    g = env._projected_gravity()
    final_tilt = float(np.degrees(np.arccos(np.clip(-g[2], -1.0, 1.0))))
    landed = bool(landed_stably)

    return Trial(
        actuator=actuator, seed=seed, depth=depth, crouch_s=crouch_s,
        extend_s=extend_s, overshoot=overshoot, head_throw=head_throw,
        flight_s=flight_s, landing_frac=landing_frac,
        crouch_drop_m=float(crouch_drop), clearance_m=float(clearance),
        airborne_s=float(longest_air * C.CTRL_DT), peak_vz_mps=float(peak_vz),
        peak_tilt_deg=float(peak_tilt), final_tilt_deg=final_tilt,
        landed_upright=landed, peak_torque_nm=float(watch.peak),
        torque_clamp_duty=float(watch.duty if env.bam is not None else 0.0),
        longest_clamp_s=float(watch.longest * C.PHYSICS_DT if env.bam is not None else 0.0),
    )


def _floats(spec: str) -> list[float]:
    return [float(x) for x in spec.split(",") if x.strip()]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--actuator", choices=("bam", "xml", "both"), default="both")
    ap.add_argument("--seeds", default="0,1,2")
    ap.add_argument("--depths", default="0.10,0.20,0.30,0.40,0.50")
    ap.add_argument("--crouch-s", default="0.15,0.30,0.45")
    ap.add_argument("--extend-s", default="0.04,0.08,0.12,0.18")
    ap.add_argument("--overshoots", default="0.00,0.08,0.16")
    ap.add_argument("--head-throws", default="-0.60,-0.30,0.00,0.30,0.60")
    ap.add_argument("--flight-s", default="0.06,0.12,0.18,0.24")
    ap.add_argument("--landing-fracs", default="0.50,1.00")
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    actuators = ("xml", "bam") if args.actuator == "both" else (args.actuator,)
    seeds = [int(x) for x in args.seeds.split(",")]
    configs = list(product(_floats(args.depths), _floats(args.crouch_s),
                           _floats(args.extend_s), _floats(args.overshoots),
                           _floats(args.head_throws), _floats(args.flight_s),
                           _floats(args.landing_fracs)))
    all_trials: list[Trial] = []

    for actuator in actuators:
        env = MicroduckWalkEnv(
            actuator=actuator, obs_noise=False, domain_rand=False,
            random_yaw=False, action_delay=False, push_robot=False,
            terminate_on_fall=False, height_termination=False, max_episode_s=5.0,
        )
        watch = TorqueWatch(env)
        for depth, crouch_s, extend_s, overshoot, head_throw, flight_s, landing_frac in configs:
            for seed in seeds:
                all_trials.append(run_trial(
                    env, watch, actuator=actuator, seed=seed, depth=depth,
                    crouch_s=crouch_s, extend_s=extend_s, overshoot=overshoot,
                    head_throw=head_throw, flight_s=flight_s,
                    landing_frac=landing_frac,
                ))

        grouped = {}
        for t in (x for x in all_trials if x.actuator == actuator):
            key = (t.depth, t.crouch_s, t.extend_s, t.overshoot, t.head_throw,
                   t.flight_s, t.landing_frac)
            grouped.setdefault(key, []).append(t)
        def clean(rows):
            return all(x.clearance_m >= 0.01 and x.airborne_s >= C.CTRL_DT
                       and x.peak_tilt_deg <= 30.0 and x.landed_upright for x in rows)

        ranked = sorted(grouped.items(), key=lambda kv: (
            clean(kv[1]),
            min(x.clearance_m for x in kv[1]),
            min(x.airborne_s for x in kv[1]),
            -max(x.peak_tilt_deg for x in kv[1]),
            -max(x.longest_clamp_s for x in kv[1]),
        ), reverse=True)

        print(f"\n{actuator.upper()} — {len(configs)} trajectories x {len(seeds)} seeds")
        print(" depth crouch extend over head flight land | clear(min/med) air(min) vz(max) tilt(max) stable clampDuty clampRun")
        for key, rows in ranked[:args.top]:
            clear = [x.clearance_m for x in rows]
            print(
                f" {key[0]:5.2f} {key[1]:6.2f} {key[2]:6.2f} {key[3]:4.2f} {key[4]:5.2f}"
                f" {key[5]:6.2f} {key[6]:4.2f} |"
                f" {min(clear):6.3f}/{np.median(clear):.3f}"
                f" {min(x.airborne_s for x in rows):6.2f}"
                f" {max(x.peak_vz_mps for x in rows):6.2f}"
                f" {max(x.peak_tilt_deg for x in rows):7.1f}"
                f" {sum(x.landed_upright for x in rows):2d}/{len(rows):<2d}"
                f" {max(x.torque_clamp_duty for x in rows):9.1%}"
                f" {max(x.longest_clamp_s for x in rows):8.3f}s"
            )
        passing = [item for item in ranked if clean(item[1])]
        if passing:
            print(f"VERDICT: FEASIBLE — {len(passing)} trajectories clear >= 1 cm, stay within 30 deg, and land upright on every seed.")
        else:
            print("VERDICT: NOT SHOWN FEASIBLE — no trajectory clears >= 1 cm and lands upright on every seed.")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text("\n".join(json.dumps(asdict(x), sort_keys=True) for x in all_trials) + "\n")
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
