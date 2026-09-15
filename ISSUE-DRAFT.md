# Draft: findings from a 30M-step from-scratch run (local notes, not for upstream as-is)

> **给未来的自己（提交前删掉这段）：** 这份草稿记录 3 个可复现的问题 + 1 个结果。第 1 条会让
> `select-run` 完全不可用；第 3 条我定位到了但没修。英文部分是准备直接贴到 issue 里的正文。

---

## Environment

| | |
|---|---|
| `microduck-lab` | `3f788f3` (2026-09-11) |
| `microduck_rl` (pinned) | `badc4e7` |
| `microduck` (pinned) | `2c61dcc` |
| Machine | Apple M5 Max, 18 cores (6P + 12E), macOS 26.6.2 |
| Python | 3.12.13 (via `uv`) |
| Setup | `./scripts/setup.sh` — 55 contract tests passed |

---

## 1. `select-run` cannot see any `train-walk` checkpoint (blocks the tool entirely)

### Repro

```bash
uv run train-walk --envs 24 --steps 30_000_000 --run-name gait-30m
uv run select-run runs/gait-30m --dry-run
```

### Actual

```
no checkpoints or final model under runs/gait-30m (train with --checkpoint-every to keep them)
```

### Expected

60 checkpoints listed. They are on disk:

```
$ ls runs/gait-30m/checkpoints/ | head -4
model_10499832_steps.zip
model_10999824_steps.zip
model_vecnormalize_10499832_steps.pkl
model_vecnormalize_10999824_steps.pkl
```

### Cause

Two different spellings of the vecnormalize filename, and `select_run` only knows one:

| writer | filename | how |
|---|---|---|
| `train.py` (`train-walk`) | `model_vecnormalize_<tag>.pkl` | SB3 `CheckpointCallback(name_prefix="model", save_vecnormalize=True)` — `train.py:183-185` |
| `train_behavior.py` | `vecnormalize_<tag>.pkl` | own save — `train_behavior.py:276` |
| `select_run.checkpoints()` | looks for `vecnormalize_<tag>.pkl` **only** — `select_run.py:57` |

So `checkpoints()` silently skips every entry for a `train-walk` run and returns `[]`
(and the "final" branch at `select_run.py:60` only fires after training ends).

### Secondary

The error message says *"train with `--checkpoint-every` to keep them"*, but
**`--checkpoint-every` is a `train-behavior` flag — `train-walk` does not have it.**
The advice points at a switch that does not exist on the command the user just ran.

### Impact

`select-run` exists specifically to pick a checkpoint by **achieved ground speed with a
fall-rate rejection floor** (`select_run.py` header: *"NO best-checkpoint selection … it
collapsed into 'longest-surviving'"*). For `train-walk` runs — the locomotion path — it
can never do that, so the failure mode it was written to prevent is exactly the one a
`train-walk` user is exposed to.

### Workaround used

Build the pairs by hand with the `model_vecnormalize_` spelling:

```python
for m in sorted(d.glob("model_*.zip"), key=lambda p: int(p.stem.split("_")[1])):
    tag = m.stem.split("_", 1)[1]
    vn  = d / f"model_vecnormalize_{tag}.pkl"   # not vecnormalize_{tag}.pkl
```

**Confidence: high.** Verified by running it and by reading all three files.

---

## 2. `_cached_export` passes `out=` to a function whose parameter is `out_path`

### Evidence

```python
# select_run.py:80
export_fn(run_dir, model_path=model_path, vn_path=vn_path, out=out)

# export_onnx.py:43
def export(run_dir: Path, out_path: Path, model_path: Path | None = None,
           vn_path: Path | None = None) -> Path:
```

### Repro

```python
from microduck_local.export_onnx import export
export(run, model_path=m, vn_path=vn, out=o)
# TypeError: export() got an unexpected keyword argument 'out'
```

**Confidence: high** for the signature mismatch. It is not reachable until finding 1 is
fixed (select-run bails at discovery first), so the two need fixing together.

---

## 3. The lab does not show the `one_leg` trick — for **any** policy, including the shipped one

### Symptom

Assign `one_leg` to a duck; it stands with both feet planted and never does the trick.

### Repro A — the lab

```bash
bash .claude/skills/restart-servers/restart.sh --fresh runs/my-flamingo
# then, over the WS:
#   {"assign": {"duck": "d0", "policy": "run:teach-one_leg-3f8b6f"}}   # the SHIPPED brain
#   {"reset": true}
```

Measure the two ankle bodies (`/scene` body order: `6 = ankle_left`, `15 = ankle_right`)
over 150 frames at 25 Hz:

| policy in the lab | ankle-height difference | frames with >5 mm asymmetry |
|---|---|---|
| `run:teach-one_leg-3f8b6f` (**shipped**) | mean 0.0003, range −0.0019 … 0.0021 | **0%** |
| `run:my-flamingo` | mean 0.0024, range 0.0024 … 0.0025 | **0%** |
| `my-walk` (walking) | oscillating ±0.02 | 90% |
| `first-gait` (standing) | constant +0.0065 | 100% |

A frozen, symmetric stance. **The shipped policy behaving identically rules out the
training artifact** — this is not "my run didn't learn it".

### Repro B — the same bytes, headless

```bash
uv run render-rollout --policy <same policy.onnx> --camera front \
    --width 640 --height 480 --sheet-frames 4 --out /tmp/rr
```

→ `contacts: both feet 28% of frames`, and at t=13.3 s and t=20.0 s
`feet L=1 R=0` — the right foot is off the ground. The trick *is* in the weights.
(`live.onnx` and `policy.onnx` are md5-identical, so the lab has the same bytes.)

### Ruled out (measured, not assumed)

| Candidate | Why it is not it |
|---|---|
| The policy / the training | shipped `teach-one_leg-3f8b6f` reproduces it |
| Randomizer flags | **both** paths disable them — `render_rollout.build_env` (`render_rollout.py:606`) passes `obs_noise=False, domain_rand=False, action_delay=False, random_yaw=False`, and `Duck._make_env` puts the same four in its `common` dict (`viz_server.py:376`) |
| The assign / palette path | `do_assign` resolves the path and calls `env_kwargs_for_policy_path`, which *does* return `behavior_id` |
| `MICRODUCK_ACTUATOR` alone | under `xml` the render still tricks and the lab still does not |

### Still open

- `standing_spawns=True` (lab) vs `spawn_overrides={}` (render) — same intent, different plumbing
- `shared_model_scope` under `xml`: ducks share one compiled `mjModel`; the comment argues it is safe *because* `domain_rand=False`, which is an argument rather than a measurement
- the lab's own frame loop

### Documentation conflict worth noting

`env_kwargs_for_behavior`'s docstring, and `render_rollout.build_env`'s, both describe the
lab and the render as building "exactly" the same env. Measured, they do not. One of the
two is describing an intention rather than the code.

**Confidence: high** that the lab and the render disagree; **not established** which
single difference causes it.

---

## 4. Side finding: one global actuator switch cannot serve both kinds of policy

`restart.sh` launches the lab with `MICRODUCK_ACTUATOR=bam` hard-coded.

| lab actuator | walk policies (trained on `bam`) | `one_leg` trick (trained on `xml`) |
|---|---|---|
| `bam` (what `restart.sh` does) | ✅ `my-walk` 0.39 m/s, `alpha_walking` 0.59 m/s | ❌ stands still |
| `xml` | ❌ `my-walk` 0.39 → **0.10** m/s | ❌ still stands still |

`train-walk` defaults to `bam`; `train-behavior` tricks stay on the env default `xml`
(README: *"The env's own default and everything built on it (tricks, the lab) stay `xml`"*).
Since `Duck._make_env` resolves **one** actuator per lab process, a roster mixing the two
cannot be previewed correctly. Worth deciding deliberately rather than by a hard-coded
default in a restart script.

---

## 5. Result (not a bug): 30M steps from scratch still does not walk

`uv run train-walk --envs 24 --steps 30_000_000` — **30 min**, 16,666 steps/s, 60
checkpoints. Scored with `eval-walk --behavior run --cmd 0.4 --episodes 12`
(achieved body-x speed, **not** reward):

| steps | falls | achieved speed | tracked |
|---:|---:|---:|---:|
| 2.5M | 0/12 | −0.000 | −0% |
| 5.0M | 0/12 | −0.000 | −0% |
| 7.5M | 0/12 | 0.000 | 0% |
| 10.0M | 2/12 | 0.002 | 0% |
| 12.5M | 8/12 | −0.010 | −2% |
| 15.0M | 6/12 | 0.009 | 2% |
| 17.5M | 0/12 | −0.001 | −0% |
| 20.0M | 11/12 | −0.036 | −9% |
| **22.5M** | **12/12** | **0.265** | **66%** |
| 25.0M | 12/12 | −0.045 | −11% |
| 27.5M | 12/12 | 0.126 | 31% |
| 30.0M (final) | 12/12 | 0.075 | 19% |

Three things stand out:

1. **No checkpoint has both speed and survival.** Every survivor (2.5 / 5 / 7.5 / 17.5M)
   sits at ~0 m/s; everything with speed falls in 100% of episodes.
2. **The curve is non-monotonic and degrades at the end.** 22.5M → 25M goes
   `0.265 → −0.045` (backwards), and the final model is worse than the 22.5M checkpoint.
3. **What it learned is "fall forwards", not walking.** The 22.5M render:
   `outcome: FELL after 44 steps (0.88 s)` — upright and stepping for ~3 steps, then
   pitch −16° → −31° → −71° → on its face.

This is the trade the README warns about (*"Speed without survival is the trap
`select-run`'s fall floor exists to catch"*), reached as a local optimum rather than as a
way station. It also extends the note at `microduck_local/README.md:653`
(*"1.5M steps from scratch buys 'do not fall', nothing more"*) — that holds to ~10M, after
which it starts falling as it explores movement.

**Interpretation, flagged as interpretation:** the shape suggests the binding constraint is
reward/curriculum design rather than sample count, so another 70M steps of the same recipe
is unlikely to be the answer. That is a hypothesis, not a measurement.

---

## Suggested fixes, smallest first

1. `select_run.checkpoints()` — accept both `vecnormalize_<tag>.pkl` and
   `model_vecnormalize_<tag>.pkl`; fix `_cached_export`'s `out=` → positional `out_path`;
   drop the `--checkpoint-every` hint (or add the flag to `train-walk`).
2. Make the lab's actuator per-duck rather than per-process, so a mixed roster previews
   correctly.
3. Finding 3 needs the isolation above before anything should be changed.
