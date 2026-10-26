"""Search a full-body one-shot jump trajectory before asking PPO to imitate it.

This is a small dependency-free cross-entropy optimiser (CEM).  Four symmetric
full-body key poses are searched under BAM physics: crouch, launch, flight and
landing.  Once both feet touch after real flight, Pollen's shipped alpha_stand
is allowed to catch the landing; the searched trajectory still has to create
flight and arrive upright enough for that handoff.

    uv run python scripts/optimize_bunny_jump.py --generations 20 --population 96

The best candidate and every generation's measurements are written to the
requested JSON.  A clip is emitted only if the candidate clears 1 cm and
settles upright on all validation seeds.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from microduck_local import contract as C
from microduck_local.viz_server import _onnx_infer
from microduck_local.walk_env import MicroduckWalkEnv

# Pose vector per key: left hip/knee/ankle offsets, neck/head pitch offsets.
# Right sagittal joints mirror the left offsets.  Four keys -> 20 parameters.
N_POSES = 4
POSE_DIM = 5
DURATIONS = (0.24, 0.08, 0.12, 0.10)  # stand->crouch->launch->flight->landing


@dataclass
class Result:
    score: float
    seed: int
    clearance_m: float
    airborne_s: float
    peak_vz_mps: float
    peak_tilt_deg: float
    touchdown_tilt_deg: float
    stable_landing: bool
    final_tilt_deg: float
    final_trunk_z: float


def pose_action(pose: np.ndarray) -> np.ndarray:
    """Five symmetric pose coordinates -> the 14-action deployment contract."""
    hip, knee, ankle, neck, head = map(float, pose)
    a = np.zeros(C.NUM_JOINTS, np.float32)
    a[2], a[3], a[4] = hip, knee, ankle
    a[11], a[12], a[13] = -hip, -knee, -ankle
    a[5], a[6] = neck, head
    return a


def _ramp(a: np.ndarray, b: np.ndarray, seconds: float):
    n = max(1, round(seconds / C.CTRL_DT))
    for i in range(1, n + 1):
        yield a + (b - a) * np.float32(i / n)


class Evaluator:
    def __init__(self, stand_policy: Path):
        self.env = MicroduckWalkEnv(
            actuator="bam", obs_noise=False, domain_rand=False,
            random_yaw=False, action_delay=False, push_robot=False,
            terminate_on_fall=False, height_termination=False, max_episode_s=4.0,
        )
        self.stand = _onnx_infer(stand_policy)

    def evaluate(self, x: np.ndarray, seed: int) -> Result:
        env = self.env
        obs, _ = env.reset(seed=seed)
        zero = np.zeros(C.NUM_JOINTS, np.float32)
        # Start from the same quiet pose every clip starts from.  This is not
        # the landing handoff: alpha_stand is used only after a real jump.
        for _ in range(round(0.60 / C.CTRL_DT)):
            obs, *_ = env.step(zero)
        foot_zero = {side: float(env.data.geom_xpos[gid][2])
                     for side, gid in env.foot_geoms.items()}

        poses = [pose_action(p) for p in np.asarray(x).reshape(N_POSES, POSE_DIM)]
        sequence = []
        prev = zero
        for pose, duration in zip(poses, DURATIONS):
            sequence.extend(_ramp(prev, pose, duration))
            prev = pose
        # Hold the landing crouch long enough to contact, then alpha_stand may
        # catch it. The whole evaluation window is ~1.8 s.
        sequence.extend([poses[-1]] * round(0.30 / C.CTRL_DT))
        sequence.extend([zero] * round(0.50 / C.CTRL_DT))

        clearance = -1.0
        peak_vz = -np.inf
        peak_tilt = touchdown_tilt = 180.0
        airborne = airborne_run = longest_air = 0
        saw_air = False
        handed_off = False
        stable_run = 0
        stable = False

        for scripted in sequence:
            action = self.stand(obs) if handed_off else scripted
            obs, *_ = env.step(action)
            contacts = env._foot_contacts()
            is_air = not contacts["left"] and not contacts["right"]
            saw_air = saw_air or is_air
            airborne += int(is_air)
            airborne_run = airborne_run + 1 if is_air else 0
            longest_air = max(longest_air, airborne_run)
            clearance = max(clearance, min(
                float(env.data.geom_xpos[env.foot_geoms[s]][2]) - foot_zero[s]
                for s in ("left", "right")))
            peak_vz = max(peak_vz, float(env.data.qvel[env._root_qvel + 2]))
            g = env._projected_gravity()
            tilt = float(np.degrees(np.arccos(np.clip(-g[2], -1.0, 1.0))))
            if not handed_off:
                peak_tilt = max(0.0 if peak_tilt == 180.0 else peak_tilt, tilt)
            if saw_air and contacts["left"] and contacts["right"] and not handed_off:
                touchdown_tilt = tilt
                # Refuse a handoff that is already a face-plant. alpha_stand
                # can stabilise a landing, not undo an upside-down trajectory.
                if tilt <= 45.0 and float(env._trunk_xpos[2]) >= 0.08:
                    handed_off = True
            good = (handed_off and contacts["left"] and contacts["right"]
                    and tilt <= 20.0 and float(env._trunk_xpos[2]) >= 0.09)
            stable_run = stable_run + 1 if good else 0
            stable = stable or stable_run >= round(0.20 / C.CTRL_DT)

        g = env._projected_gravity()
        final_tilt = float(np.degrees(np.arccos(np.clip(-g[2], -1.0, 1.0))))
        air_s = longest_air * C.CTRL_DT
        # Dense enough to guide search, but landing dominates the ranking.
        score = (
            300.0 * float(np.clip(clearance, 0.0, 0.04))
            + 20.0 * float(np.clip(air_s, 0.0, 0.20))
            + 5.0 * float(np.clip(peak_vz, 0.0, 0.6))
            - 0.08 * min(peak_tilt, 180.0)
            - 0.05 * min(touchdown_tilt, 180.0)
            + (40.0 if stable else 0.0)
        )
        return Result(
            score=score, seed=seed, clearance_m=float(clearance),
            airborne_s=float(air_s), peak_vz_mps=float(peak_vz),
            peak_tilt_deg=float(peak_tilt), touchdown_tilt_deg=float(touchdown_tilt),
            stable_landing=stable, final_tilt_deg=final_tilt,
            final_trunk_z=float(env._trunk_xpos[2]),
        )


def initial_distribution() -> tuple[np.ndarray, np.ndarray]:
    """Start around a physical crouch/extend/landing story, not random noise."""
    # [hip, knee, ankle, neck, head] offsets for each key.
    mean = np.array([
        [-0.30, -0.60, -0.30, 0.00, 0.00],  # crouch
        [0.12, 0.24, 0.12, 0.00, 0.00],     # fast extension
        [0.00, 0.10, 0.05, 0.00, 0.00],     # compact-ish flight
        [-0.25, -0.50, -0.25, 0.00, 0.00],  # landing cushion
    ], np.float64).ravel()
    std = np.tile(np.array([0.25, 0.35, 0.25, 0.35, 0.35]), N_POSES)
    return mean, std


def clip_bounds(x: np.ndarray) -> np.ndarray:
    y = np.asarray(x, np.float64).reshape(N_POSES, POSE_DIM).copy()
    y[:, 0] = np.clip(y[:, 0], -1.0, 1.0)
    y[:, 1] = np.clip(y[:, 1], -1.4, 1.4)
    y[:, 2] = np.clip(y[:, 2], -1.0, 1.0)
    y[:, 3:] = np.clip(y[:, 3:], -1.0, 1.0)
    return y.ravel()


def write_clip(path: Path, x: np.ndarray) -> None:
    poses = np.asarray(x).reshape(N_POSES, POSE_DIM)
    times = np.cumsum((0.0,) + DURATIONS).tolist()
    keys = [{"t": 0.0, "joints": C.DEFAULT_POSE.astype(float).tolist(), "rootPitch": 0.0}]
    for t, pose in zip(times[1:], poses):
        joints = C.DEFAULT_POSE + pose_action(pose)
        keys.append({"t": round(float(t), 4), "joints": joints.astype(float).tolist(),
                     "rootPitch": 0.0})
    # One-shot clip: landing recovery is a controller handoff, not a fake loop.
    payload = {"version": 1, "name": path.stem, "duration": round(times[-1], 4),
               "loop": False, "keys": keys}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--generations", type=int, default=20)
    ap.add_argument("--population", type=int, default=96)
    ap.add_argument("--elite-frac", type=float, default=0.15)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--train-seeds", default="0,1,2")
    ap.add_argument("--validate-seeds", default="0,1,2,3,4")
    ap.add_argument("--stand-policy", type=Path,
                    default=Path("../microduck/policies/alpha_stand.onnx"))
    ap.add_argument("--out", type=Path, default=Path("runs/bunny-trajectory-search.json"))
    ap.add_argument("--clip", type=Path, default=Path("clips/bunny-hop-once.json"))
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    evaluator = Evaluator(args.stand_policy)
    mean, std = initial_distribution()
    elite_n = max(2, round(args.population * args.elite_frac))
    history = []
    train_seeds = [int(x) for x in args.train_seeds.split(",")]
    initial_rows = [evaluator.evaluate(mean, seed) for seed in train_seeds]
    best_score = min(r.score for r in initial_rows)
    best_x = mean.copy()
    best = min(initial_rows, key=lambda r: r.score)

    for generation in range(args.generations):
        samples = np.stack([clip_bounds(mean + std * rng.standard_normal(mean.size))
                            for _ in range(args.population)])
        batches = [[evaluator.evaluate(x, seed) for seed in train_seeds]
                   for x in samples]
        robust_scores = np.array([min(r.score for r in rows) for rows in batches])
        order = np.argsort(robust_scores)[::-1]
        elites = samples[order[:elite_n]]
        # Smoothing prevents one lucky generation collapsing the search cloud.
        mean = 0.25 * mean + 0.75 * elites.mean(axis=0)
        std = np.maximum(0.04, 0.25 * std + 0.75 * elites.std(axis=0))
        winner_rows = batches[int(order[0])]
        winner_score = float(robust_scores[int(order[0])])
        winner = min(winner_rows, key=lambda r: r.score)
        if winner_score > best_score:
            best_score, best, best_x = winner_score, winner, samples[int(order[0])].copy()
        row = {"generation": generation, "train_seeds": train_seeds,
               "robust_score": winner_score,
               "winner": [asdict(r) for r in winner_rows],
               "best": asdict(best), "mean": mean.tolist(), "std": std.tolist()}
        history.append(row)
        print(f"gen {generation:02d} worst {winner_score:7.2f}  "

              f"clear {winner.clearance_m*100:4.1f}cm air {winner.airborne_s:.2f}s "
              f"tilt {winner.peak_tilt_deg:5.1f}/{winner.touchdown_tilt_deg:5.1f} "
              f"stable={winner.stable_landing}")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"best_x": best_x.tolist(), "best": asdict(best),
                                        "history": history}, indent=2) + "\n")

    seeds = [int(x) for x in args.validate_seeds.split(",")]
    validation = [evaluator.evaluate(best_x, seed) for seed in seeds]
    passed = all(r.clearance_m >= 0.01 and r.airborne_s >= C.CTRL_DT
                 and r.stable_landing for r in validation)
    print("\nvalidation")
    for r in validation:
        print(f" seed {r.seed}: clear {r.clearance_m*100:.1f}cm air {r.airborne_s:.2f}s "
              f"tilt {r.peak_tilt_deg:.1f}/{r.touchdown_tilt_deg:.1f} "
              f"stable={r.stable_landing}")
    print("VERDICT:", "FEASIBLE" if passed else "NOT SHOWN FEASIBLE")
    args.out.write_text(json.dumps({"best_x": best_x.tolist(), "best": asdict(best),
                                    "validation": [asdict(r) for r in validation],
                                    "passed": passed, "history": history}, indent=2) + "\n")
    if passed:
        write_clip(args.clip, best_x)
        print(f"wrote clip {args.clip}")
    else:
        print("clip not written: the candidate missed the validation bar")


if __name__ == "__main__":
    main()
