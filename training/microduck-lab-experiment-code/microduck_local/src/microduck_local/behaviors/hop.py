"""Continuous left-leg forward hopping behavior.

The contact schedule is clocked through two existing command slots, so the
memoryless policy can distinguish load, flight and landing without changing
the 61-observation deployment contract.  Curriculum rungs change only servo
physics and target strictness; the reward weights stay sealed across stages.
"""

from __future__ import annotations

import math
import os

import numpy as np

from .airflip import _soft_landing_pen
from .core import Behavior, CurriculumStage, RewardTerm, _register, _trunk_yaw
from .locomotion import _run_body_ang_pen, _run_upright
from .poses import (
    _head_up,
    _head_up_pull,
    _limit_parking_pen,
    _torque_pen,
)

_HOP_PERIOD_S = 0.72
_HOP_PERIOD_STEPS = max(1, round(_HOP_PERIOD_S / 0.02))
_HOP_FLIGHT_CENTRE = 0.46
_HOP_FLIGHT_HALF_WIDTH = 0.20


def _hop_knob(env, name: str, default: float) -> float:
    """Read a stage knob from the preview instance or trainer environment."""
    raw = getattr(env, "spawn_overrides", {}).get(name, os.environ.get(name))
    try:
        return float(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default


def _hop_phase(env) -> float:
    return (int(env.step_count) % _HOP_PERIOD_STEPS) / _HOP_PERIOD_STEPS


def _hop_obs(env) -> None:
    """Publish forward intent and the hop clock in existing command slots."""
    phase = 2.0 * math.pi * _hop_phase(env)
    env.twist_cmd[:] = (max(0.0, _hop_knob(env, "MICRODUCK_HOP_SPEED", 0.28)), 0.0, 0.0)
    env.body_cmd[4], env.body_cmd[5] = math.sin(phase), math.cos(phase)


def _hop_flight_gate(env) -> float:
    """Raised-cosine desired-flight window, in [0, 1]."""
    d = abs(_hop_phase(env) - _HOP_FLIGHT_CENTRE)
    d = min(d, 1.0 - d)
    if d >= _HOP_FLIGHT_HALF_WIDTH:
        return 0.0
    return 0.5 + 0.5 * math.cos(math.pi * d / _HOP_FLIGHT_HALF_WIDTH)


def _hop_contact_cycle(env) -> float:
    """Left-only support -> flight -> left-or-both landing, continuously."""
    c = env.foot_contact_state
    gate = _hop_flight_gate(env)
    airborne = float(not c["left"] and not c["right"])
    phase = _hop_phase(env)
    landing_grace = 0.62 <= phase < 0.80
    support = float(c["left"] and (landing_grace or not c["right"]))
    return gate * airborne + (1.0 - gate) * support


def _hop_air_clearance(env) -> float:
    """Flight-window clearance; planted or shuffling feet earn nothing."""
    clearance = max(0.005, _hop_knob(env, "MICRODUCK_HOP_CLEARANCE", 0.035))
    c = env.foot_contact_state
    if c["left"] or c["right"]:
        return 0.0
    zl = float(env.data.geom_xpos[env.foot_geoms["left"]][2])
    zr = float(env.data.geom_xpos[env.foot_geoms["right"]][2])
    # Planted foot geom centres sit about 8.6 mm above the floor.
    actual = max(0.0, min(zl, zr) - 0.0086)
    return _hop_flight_gate(env) * float(np.clip(actual / clearance, 0.0, 1.0))


def _hop_right_foot_up(env) -> float:
    """Keep the right leg tucked except for the allowed two-foot touchdown."""
    phase = _hop_phase(env)
    if 0.62 <= phase < 0.80 and env.foot_contact_state["left"]:
        return 1.0  # the requested two-foot landing is legal
    if env.foot_contact_state["right"]:
        return 0.0
    zl = float(env.data.geom_xpos[env.foot_geoms["left"]][2])
    zr = float(env.data.geom_xpos[env.foot_geoms["right"]][2])
    d = (zr - zl) - 0.04
    # Wide enough to pull from equal-height airborne feet, tight enough to
    # keep the right foot visibly tucked once the gait exists.
    return 0.5 * float(np.exp(-(d * d) / 0.06**2)) + 0.5 * float(np.exp(-(d * d) / 0.025**2))


def _hop_forward(env) -> float:
    """Bounded heading-frame forward tracking; standing pays exactly zero."""
    target = max(0.05, _hop_knob(env, "MICRODUCK_HOP_SPEED", 0.28))
    fwd, lat, _ = env.heading_lin_vel()
    std2 = 0.10
    raw = float(np.exp(-((fwd - target) ** 2 + lat * lat) / std2))
    standing = float(np.exp(-(target * target) / std2))
    tracked = float(np.clip((raw - standing) / max(1.0 - standing, 1e-6), 0.0, 1.0))
    # Body-frame forward velocity pays a circle in full unless task income is
    # coupled to the observable quantities that distinguish straight travel.
    # The first two hop runs simply traded additive yaw costs against forward
    # reward, so turning must switch the forward income itself off.
    straight = float(np.exp(-(float(env._gyro[2]) ** 2) / 0.25))
    straight *= float(np.exp(-(lat * lat) / 0.08))
    # A forward dive must not be the cheapest way to cash the speed term.
    return tracked * _run_upright(env) * straight


def _hop_reset(env) -> None:
    env._hop_assist_cycle = -1


def _hop_pre_step(env) -> None:
    """One launch impulse per cycle on assisted curriculum rungs.

    The first run earned essentially zero `get_air` in every stage: no rollout
    sampled a jump, so PPO learned a turning step gait instead.  This is a
    physics ladder, not reward — early rungs put the missing airborne state on
    policy, and the final rung sets the impulse to exactly zero.
    """
    impulse = max(0.0, _hop_knob(env, "MICRODUCK_HOP_ASSIST", 0.0))
    if impulse <= 0.0:
        return
    cycle = int(env.step_count) // _HOP_PERIOD_STEPS
    phase = _hop_phase(env)
    if cycle == getattr(env, "_hop_assist_cycle", -1) or not (0.22 <= phase <= 0.38):
        return
    c = env.foot_contact_state
    if not c["left"]:
        return
    env._hop_assist_cycle = cycle
    env.data.qvel[2] = max(float(env.data.qvel[2]), impulse)
    # A small heading-relative nudge makes the rehearsed state a FORWARD hop,
    # not a vertical pogo. It ladders down with the vertical assist too.
    yaw = _trunk_yaw(env)
    forward = 0.15 * impulse
    env.data.qvel[0] += forward * math.cos(yaw)
    env.data.qvel[1] += forward * math.sin(yaw)


def _hop_no_sideways(env) -> float:
    _, lateral, _ = env.heading_lin_vel()
    return -min((lateral / 0.20) ** 2, 1.0)


def _hop_no_yaw(env) -> float:
    return -min((float(env._gyro[2]) / 3.0) ** 2, 1.0)


_register(Behavior(
    id="one_leg_hop",
    suggest="hop forward on one leg",
    emoji="🐇",
    title="Left-leg forward hop",
    description=(
        "Hop forward continuously from the left leg, keeping the right leg "
        "lifted; either the left foot or both feet may touch down."
    ),
    how_it_learns=(
        "A clock in two existing command slots tells the policy when to load "
        "the left leg, fly and land. It earns only for real two-foot-off-ground "
        "clearance, forward travel while upright, and the requested left-leg "
        "contact cycle; a two-foot landing is explicitly allowed. Four stages "
        "ladder away launch assistance, raise clearance, and finish on honest BAM servos."
    ),
    keywords=("hop forward on one leg", "one leg hop", "single leg hop",
              "left leg hop", "forward hop", "单腿往前跳", "左腿跳"),
    terms=(
        RewardTerm("hop_cycle", "Big points for left support, real flight, then left-or-both landing",
                   4.0, _hop_contact_cycle),
        RewardTerm("get_air", "Points for both feet clearing the floor during the flight phase",
                   3.0, _hop_air_clearance),
        RewardTerm("forward_hop", "Big points for moving forward at the requested hopping speed",
                   4.0, _hop_forward),
        RewardTerm("right_foot_up", "Points for keeping the right leg lifted between landings",
                   2.0, _hop_right_foot_up),
        RewardTerm("stay_upright", "Points for keeping the body upright through the hop",
                   2.0, _run_upright),
        RewardTerm("head_up", "Points for holding the head near its natural pose",
                   0.8, _head_up),
        RewardTerm("head_up_pull", "Points for pulling a drooped head back toward natural pose",
                   0.7, _head_up_pull),
        RewardTerm("soft_landings", "Penalty for slamming either foot into the floor",
                   0.75, _soft_landing_pen, is_penalty=True),
        RewardTerm("no_yaw", "Penalty for turning instead of hopping straight ahead",
                   1.5, _hop_no_yaw, is_penalty=True),
        RewardTerm("no_sideways", "Penalty for circling or sliding sideways",
                   1.0, _hop_no_sideways, is_penalty=True),
        RewardTerm("calm_roll", "Small penalty for uncontrolled trunk roll and pitch rates",
                   0.025, _run_body_ang_pen, is_penalty=True),
        RewardTerm("no_limit_parking", "Penalty for grinding joints against their end stops",
                   1.0, _limit_parking_pen, is_penalty=True),
        RewardTerm("save_energy", "Penalty for straining the motors",
                   0.5, _torque_pen, is_penalty=True),
    ),
    default_steps=8_000_000,
    success_metric="continuous forward hops with a real flight phase and no falls",
    episode_s=12.0,
    symmetric=False,  # left is deliberately the support leg
    height_termination=False,
    forward_cmd=0.28,
    reset_fn=_hop_reset,
    pre_step_fn=_hop_pre_step,
    obs_fn=_hop_obs,
    curriculum=(
        CurriculumStage(
            "assisted take-off discovery", 1_500_000,
            {"MICRODUCK_ACTUATOR": "xml", "MICRODUCK_HOP_SPEED": "0.14",
             "MICRODUCK_HOP_CLEARANCE": "0.015", "MICRODUCK_HOP_ASSIST": "0.65"},
            "A launch impulse makes real airborne states appear while the policy learns the left-leg cycle.",
        ),
        CurriculumStage(
            "policy takes over the launch", 1_500_000,
            {"MICRODUCK_ACTUATOR": "xml", "MICRODUCK_HOP_SPEED": "0.20",
             "MICRODUCK_HOP_CLEARANCE": "0.022", "MICRODUCK_HOP_ASSIST": "0.35"},
            "The same scorecard, with half the launch help and more forward travel.",
        ),
        CurriculumStage(
            "weak assist on honest servos", 2_000_000,
            {"MICRODUCK_ACTUATOR": "bam", "MICRODUCK_HOP_SPEED": "0.24",
             "MICRODUCK_HOP_CLEARANCE": "0.030", "MICRODUCK_HOP_ASSIST": "0.18"},
            "Transfer the hop to BAM servos while the last small impulse keeps flight sampled.",
        ),
        CurriculumStage(
            "unassisted straight continuous hops", 3_000_000,
            {"MICRODUCK_ACTUATOR": "bam", "MICRODUCK_HOP_SPEED": "0.28",
             "MICRODUCK_HOP_CLEARANCE": "0.035", "MICRODUCK_HOP_ASSIST": "0.0"},
            "No launch help: the policy must hop forward itself without circling.",
        ),
    ),
))


# ------------------------------------------------ alternating forward hops
_ALT_PERIOD_S = 1.0
_ALT_PERIOD_STEPS = round(_ALT_PERIOD_S / 0.02)


def _alt_phase(env) -> float:
    return (int(env.step_count) % _ALT_PERIOD_STEPS) / _ALT_PERIOD_STEPS


def _alt_obs(env) -> None:
    phase = 2.0 * math.pi * _alt_phase(env)
    env.twist_cmd[:] = (max(0.0, _hop_knob(env, "MICRODUCK_HOP_SPEED", 0.30)), 0.0, 0.0)
    env.body_cmd[4], env.body_cmd[5] = math.sin(phase), math.cos(phase)


def _alt_flight_gate(env) -> float:
    phase = _alt_phase(env)
    d = min(abs(phase - 0.25), abs(phase - 0.75))
    half_width = 0.14
    if d >= half_width:
        return 0.0
    return 0.5 + 0.5 * math.cos(math.pi * d / half_width)


def _alt_contact_cycle(env) -> float:
    """Left launch -> flight -> right launch -> flight -> left, repeatedly."""
    c = env.foot_contact_state
    gate = _alt_flight_gate(env)
    airborne = float(not c["left"] and not c["right"])
    phase = _alt_phase(env)
    support_side = "left" if phase < 0.25 or phase >= 0.75 else "right"
    other = "right" if support_side == "left" else "left"
    # A short two-foot touchdown is legal around each support handover.
    handover = abs(phase - 0.50) < 0.08 or phase < 0.08 or phase > 0.92
    support = float(c[support_side] and (handover or not c[other]))
    return gate * airborne + (1.0 - gate) * support


def _alt_air_clearance(env) -> float:
    c = env.foot_contact_state
    if c["left"] or c["right"]:
        return 0.0
    clearance = max(0.005, _hop_knob(env, "MICRODUCK_HOP_CLEARANCE", 0.035))
    zl = float(env.data.geom_xpos[env.foot_geoms["left"]][2])
    zr = float(env.data.geom_xpos[env.foot_geoms["right"]][2])
    actual = max(0.0, min(zl, zr) - 0.0086)
    return _alt_flight_gate(env) * float(np.clip(actual / clearance, 0.0, 1.0))


def _alt_load_gate(env) -> float:
    """Two smooth crouch windows, one before each leg's launch."""
    phase = _alt_phase(env)
    d = min(abs(phase - 0.10), abs(phase - 0.60))
    width = 0.12
    if d >= width:
        return 0.0
    return 0.5 + 0.5 * math.cos(math.pi * d / width)


def _alt_spring_height(env) -> float:
    """Crouch before launch, then extend — the missing spring motion."""
    if _alt_flight_gate(env) > 0.5:
        return 0.0  # an airborne root has no ground-relative pose target
    depth = max(0.01, _hop_knob(env, "MICRODUCK_HOP_CROUCH", 0.032))
    target = env.stand_z - depth * _alt_load_gate(env)
    d2 = (float(env._trunk_xpos[2]) - target) ** 2
    return (0.5 * float(np.exp(-d2 / 0.045**2))
            + 0.5 * float(np.exp(-d2 / 0.018**2)))


def _alt_push_up(env) -> float:
    """Upward velocity during each take-off, not horizontal foot shuffling."""
    phase = _alt_phase(env)
    d = min(abs(phase - 0.20), abs(phase - 0.70))
    width = 0.10
    if d >= width:
        return 0.0
    gate = 0.5 + 0.5 * math.cos(math.pi * d / width)
    return gate * float(np.clip(float(env.data.qvel[2]) / 0.60, 0.0, 1.0)) * _run_upright(env)


def _alt_state(env) -> None:
    if not env.foot_contact_state["left"] and not env.foot_contact_state["right"]:
        env._alt_last_air_step = int(env.step_count)


def _alt_forward(env) -> float:
    """Travel pays in full only when the recent gait actually became airborne."""
    age = int(env.step_count) - int(getattr(env, "_alt_last_air_step", -10_000))
    participation = 1.0 if age <= round(0.30 / 0.02) else 0.10
    return participation * _hop_forward(env)


def _alt_reset(env) -> None:
    env._alt_assist_half = -1
    env._alt_last_air_step = -10_000


def _alt_pre_step(env) -> None:
    """Alternating launch ladder; final-stage assist is exactly zero."""
    impulse = max(0.0, _hop_knob(env, "MICRODUCK_HOP_ASSIST", 0.0))
    if impulse <= 0.0:
        return
    half_steps = _ALT_PERIOD_STEPS // 2
    half = int(env.step_count) // half_steps
    local = (int(env.step_count) % half_steps) / half_steps
    if half == getattr(env, "_alt_assist_half", -1) or not (0.34 <= local <= 0.48):
        return
    support_side = "left" if half % 2 == 0 else "right"
    if not env.foot_contact_state[support_side]:
        return
    env._alt_assist_half = half
    env.data.qvel[2] = max(float(env.data.qvel[2]), impulse)
    yaw = _trunk_yaw(env)
    forward = 0.15 * impulse
    env.data.qvel[0] += forward * math.cos(yaw)
    env.data.qvel[1] += forward * math.sin(yaw)


_register(Behavior(
    id="alternate_hop",
    suggest="alternate feet and hop forward",
    emoji="🐇",
    title="Alternating forward hops",
    description=(
        "Hop forward by alternating left and right support, with a real flight "
        "phase between them and brief two-foot touchdowns allowed."
    ),
    how_it_learns=(
        "A visible cycle asks for left support, flight, right support, then "
        "flight again. Alternating the launch leg removes the permanent "
        "one-sided torque that made the first experiment orbit; yaw rate and "
        "sideways travel are still charged directly. Early launch impulses "
        "put flight into rollouts and are removed completely in the final stage."
    ),
    keywords=("alternate feet and hop forward", "alternating hop", "alternate hop",
              "two feet alternate", "两脚交替跳", "双脚交替跳"),
    terms=(
        RewardTerm("alternate_cycle", "Big points for left-flight-right-flight contact timing",
                   5.0, _alt_contact_cycle),
        RewardTerm("get_air", "Points for both feet clearing the floor between supports",
                   3.0, _alt_air_clearance),
        RewardTerm("spring_height", "Points for crouching before each launch and extending again",
                   3.0, _alt_spring_height),
        RewardTerm("push_up", "Points for producing upward speed during each take-off",
                   2.0, _alt_push_up),
        RewardTerm("forward_hop", "Big points for straight forward travel after real flight",
                   4.0, _alt_forward),
        RewardTerm("stay_upright", "Points for keeping the body upright through every handover",
                   2.5, _run_upright),
        RewardTerm("head_up", "Points for holding the head near its natural pose",
                   0.8, _head_up),
        RewardTerm("head_up_pull", "Points for pulling a drooped head back toward natural pose",
                   0.7, _head_up_pull),
        RewardTerm("soft_landings", "Penalty for slamming either foot into the floor",
                   0.75, _soft_landing_pen, is_penalty=True),
        RewardTerm("no_yaw", "Penalty for turning instead of hopping straight ahead",
                   2.0, _hop_no_yaw, is_penalty=True),
        RewardTerm("no_sideways", "Penalty for circling or sliding sideways",
                   1.5, _hop_no_sideways, is_penalty=True),
        RewardTerm("calm_roll", "Small penalty for uncontrolled trunk roll and pitch rates",
                   0.025, _run_body_ang_pen, is_penalty=True),
        RewardTerm("no_limit_parking", "Penalty for grinding joints against their end stops",
                   1.0, _limit_parking_pen, is_penalty=True),
        RewardTerm("save_energy", "Penalty for straining the motors",
                   0.5, _torque_pen, is_penalty=True),
    ),
    default_steps=7_000_000,
    success_metric="straight-line distance covered with alternating airborne hops and no falls",
    episode_s=12.0,
    symmetric=False,  # mirroring must also shift the clock by half a cycle; the current map does not
    height_termination=False,
    forward_cmd=0.30,
    reset_fn=_alt_reset,
    pre_step_fn=_alt_pre_step,
    state_fn=_alt_state,
    obs_fn=_alt_obs,
    curriculum=(
        CurriculumStage(
            "discover alternating flight", 1_500_000,
            {"MICRODUCK_ACTUATOR": "xml", "MICRODUCK_HOP_SPEED": "0.15",
             "MICRODUCK_HOP_CLEARANCE": "0.015", "MICRODUCK_HOP_CROUCH": "0.020",
             "MICRODUCK_HOP_ASSIST": "0.60"},
            "Alternate assisted launches so both left-to-right and right-to-left flight are sampled.",
        ),
        CurriculumStage(
            "alternate under weaker help", 1_500_000,
            {"MICRODUCK_ACTUATOR": "xml", "MICRODUCK_HOP_SPEED": "0.22",
             "MICRODUCK_HOP_CLEARANCE": "0.023", "MICRODUCK_HOP_CROUCH": "0.026",
             "MICRODUCK_HOP_ASSIST": "0.32"},
            "Keep alternating while the policy takes over most of each launch.",
        ),
        CurriculumStage(
            "transfer to honest servos", 2_000_000,
            {"MICRODUCK_ACTUATOR": "bam", "MICRODUCK_HOP_SPEED": "0.26",
             "MICRODUCK_HOP_CLEARANCE": "0.030", "MICRODUCK_HOP_CROUCH": "0.030",
             "MICRODUCK_HOP_ASSIST": "0.15"},
            "Use BAM servos with only a small remaining discovery impulse.",
        ),
        CurriculumStage(
            "unassisted alternating hops", 2_000_000,
            {"MICRODUCK_ACTUATOR": "bam", "MICRODUCK_HOP_SPEED": "0.30",
             "MICRODUCK_HOP_CLEARANCE": "0.035", "MICRODUCK_HOP_CROUCH": "0.032",
             "MICRODUCK_HOP_ASSIST": "0.0"},
            "No assistance: alternate feet and travel straight under the policy alone.",
        ),
    ),
))


# ------------------------------------------------ two-foot bunny hops
_BUNNY_PERIOD_STEPS = round(0.80 / 0.02)


def _bunny_phase(env) -> float:
    return (int(env.step_count) % _BUNNY_PERIOD_STEPS) / _BUNNY_PERIOD_STEPS


def _bunny_obs(env) -> None:
    phase = 2.0 * math.pi * _bunny_phase(env)
    env.twist_cmd[:] = (max(0.0, _hop_knob(env, "MICRODUCK_HOP_SPEED", 0.25)), 0.0, 0.0)
    env.body_cmd[4], env.body_cmd[5] = math.sin(phase), math.cos(phase)


def _bunny_window(env, centre: float, width: float) -> float:
    d = abs(_bunny_phase(env) - centre)
    d = min(d, 1.0 - d)
    if d >= width:
        return 0.0
    return 0.5 + 0.5 * math.cos(math.pi * d / width)


def _bunny_contact_cycle(env) -> float:
    flight = _bunny_window(env, 0.45, 0.18)
    c = env.foot_contact_state
    airborne = float(not c["left"] and not c["right"])
    grounded = float(c["left"] and c["right"])
    return flight * airborne + (1.0 - flight) * grounded


def _bunny_air_clearance(env) -> float:
    c = env.foot_contact_state
    if c["left"] or c["right"]:
        return 0.0
    clearance = max(0.005, _hop_knob(env, "MICRODUCK_HOP_CLEARANCE", 0.035))
    zl = float(env.data.geom_xpos[env.foot_geoms["left"]][2])
    zr = float(env.data.geom_xpos[env.foot_geoms["right"]][2])
    actual = max(0.0, min(zl, zr) - 0.0086)
    return _bunny_window(env, 0.45, 0.18) * float(np.clip(actual / clearance, 0.0, 1.0))


def _bunny_spring_height(env) -> float:
    if _bunny_window(env, 0.45, 0.18) > 0.5:
        return 0.0
    depth = max(0.01, _hop_knob(env, "MICRODUCK_HOP_CROUCH", 0.035))
    target = env.stand_z - depth * _bunny_window(env, 0.17, 0.16)
    d2 = (float(env._trunk_xpos[2]) - target) ** 2
    return (0.5 * float(np.exp(-d2 / 0.045**2))
            + 0.5 * float(np.exp(-d2 / 0.018**2)))


def _bunny_push_up(env) -> float:
    gate = _bunny_window(env, 0.32, 0.11)
    return gate * float(np.clip(float(env.data.qvel[2]) / 0.65, 0.0, 1.0)) * _run_upright(env)


def _bunny_reset(env) -> None:
    env._bunny_assist_cycle = -1
    env._bunny_last_air_step = -10_000


def _bunny_state(env) -> None:
    if not env.foot_contact_state["left"] and not env.foot_contact_state["right"]:
        env._bunny_last_air_step = int(env.step_count)


def _bunny_forward(env) -> float:
    age = int(env.step_count) - int(getattr(env, "_bunny_last_air_step", -10_000))
    return (1.0 if age <= round(0.30 / 0.02) else 0.10) * _hop_forward(env)


def _bunny_pre_step(env) -> None:
    impulse = max(0.0, _hop_knob(env, "MICRODUCK_HOP_ASSIST", 0.0))
    if impulse <= 0.0:
        return
    cycle = int(env.step_count) // _BUNNY_PERIOD_STEPS
    phase = _bunny_phase(env)
    if cycle == getattr(env, "_bunny_assist_cycle", -1) or not (0.28 <= phase <= 0.38):
        return
    c = env.foot_contact_state
    if not (c["left"] and c["right"]):
        return
    env._bunny_assist_cycle = cycle
    env.data.qvel[2] = max(float(env.data.qvel[2]), impulse)
    yaw = _trunk_yaw(env)
    forward = 0.12 * impulse
    env.data.qvel[0] += forward * math.cos(yaw)
    env.data.qvel[1] += forward * math.sin(yaw)


_register(Behavior(
    id="bunny_hop",
    suggest="hop forward with both feet",
    emoji="🐰",
    title="Two-foot forward hops",
    description="Crouch, push off with both feet together, fly forward, and land on both feet repeatedly.",
    how_it_learns=(
        "Both legs now share one simple spring cycle: crouch together, extend "
        "together, become genuinely airborne, then land together. Forward "
        "travel pays fully only after real flight and only while yaw and "
        "sideways speed stay low. Launch assistance is removed by the final stage."
    ),
    keywords=("hop forward with both feet", "two foot hop", "both feet jump",
              "bunny hop", "双脚一起跳", "双脚跳"),
    terms=(
        RewardTerm("bunny_cycle", "Big points for both-feet load, flight, and both-feet landing",
                   5.0, _bunny_contact_cycle),
        RewardTerm("get_air", "Points for both feet visibly clearing the floor",
                   4.0, _bunny_air_clearance),
        RewardTerm("spring_height", "Points for a visible crouch followed by full extension",
                   4.0, _bunny_spring_height),
        RewardTerm("push_up", "Points for upward speed during the two-foot push-off",
                   3.0, _bunny_push_up),
        RewardTerm("forward_hop", "Points for straight forward travel after real flight",
                   4.0, _bunny_forward),
        RewardTerm("stay_upright", "Points for keeping the body upright through landing",
                   2.5, _run_upright),
        RewardTerm("head_up", "Points for holding the head near its natural pose",
                   0.8, _head_up),
        RewardTerm("head_up_pull", "Points for lifting a drooped head",
                   0.7, _head_up_pull),
        RewardTerm("soft_landings", "Penalty for slamming into the floor",
                   0.75, _soft_landing_pen, is_penalty=True),
        RewardTerm("no_yaw", "Penalty for turning instead of hopping straight",
                   2.0, _hop_no_yaw, is_penalty=True),
        RewardTerm("no_sideways", "Penalty for circling or sliding sideways",
                   1.5, _hop_no_sideways, is_penalty=True),
        RewardTerm("no_limit_parking", "Penalty for grinding joints against their stops",
                   1.0, _limit_parking_pen, is_penalty=True),
        RewardTerm("save_energy", "Penalty for straining the motors",
                   0.5, _torque_pen, is_penalty=True),
    ),
    default_steps=5_000_000,
    success_metric="straight distance covered by repeated unassisted two-foot flight cycles",
    episode_s=12.0,
    symmetric=False,  # current mirror map time-reflects the clock slots
    height_termination=False,
    forward_cmd=0.25,
    reset_fn=_bunny_reset,
    pre_step_fn=_bunny_pre_step,
    state_fn=_bunny_state,
    obs_fn=_bunny_obs,
    curriculum=(
        CurriculumStage(
            "learn crouch and two-foot take-off", 1_500_000,
            {"MICRODUCK_ACTUATOR": "xml", "MICRODUCK_HOP_SPEED": "0.12",
             "MICRODUCK_HOP_CLEARANCE": "0.015", "MICRODUCK_HOP_CROUCH": "0.025",
             "MICRODUCK_HOP_ASSIST": "0.60"},
            "Strong servos and a launch impulse expose the complete crouch-flight-land cycle.",
        ),
        CurriculumStage(
            "transfer the spring to BAM", 1_500_000,
            {"MICRODUCK_ACTUATOR": "bam", "MICRODUCK_HOP_SPEED": "0.20",
             "MICRODUCK_HOP_CLEARANCE": "0.025", "MICRODUCK_HOP_CROUCH": "0.032",
             "MICRODUCK_HOP_ASSIST": "0.25"},
            "Use honest servos with less than half the launch assistance.",
        ),
        CurriculumStage(
            "unassisted two-foot forward hops", 2_000_000,
            {"MICRODUCK_ACTUATOR": "bam", "MICRODUCK_HOP_SPEED": "0.25",
             "MICRODUCK_HOP_CLEARANCE": "0.035", "MICRODUCK_HOP_CROUCH": "0.035",
             "MICRODUCK_HOP_ASSIST": "0.0"},
            "No impulse: crouch, jump and travel must all come from the learned policy.",
        ),
    ),
))


__all__ = [n for n in dir() if not n.startswith("__")]
