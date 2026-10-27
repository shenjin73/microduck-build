import math

from .locomotion import *  # noqa: F401,F403 — cascades the full upstream namespace,

_ROUTINE_CROUCH_STEPS = round(5.0 / C.CTRL_DT)
_ROUTINE_RISE_STEPS = round(1.0 / C.CTRL_DT)
_ROUTINE_STAND_STEPS = round(2.0 / C.CTRL_DT)
_ROUTINE_WALK_STEPS = round(5.0 / C.CTRL_DT)
_ROUTINE_STOP_STEPS = round(1.0 / C.CTRL_DT)
_ROUTINE_WALK_START = _ROUTINE_CROUCH_STEPS + _ROUTINE_RISE_STEPS + _ROUTINE_STAND_STEPS
_ROUTINE_STOP_START = _ROUTINE_WALK_START + _ROUTINE_WALK_STEPS
_ROUTINE_FINAL_STAND_START = _ROUTINE_STOP_START + _ROUTINE_STOP_STEPS
_ROUTINE_PERIOD_STEPS = _ROUTINE_FINAL_STAND_START + _ROUTINE_STAND_STEPS
_ROUTINE_WALK_SPEED = 0.4


def _routine_step(env) -> int:
    return int(env.step_count) % _ROUTINE_PERIOD_STEPS


def _routine_stage(env) -> str:
    step = _routine_step(env)
    if step < _ROUTINE_CROUCH_STEPS:
        return "crouch"
    if step < _ROUTINE_CROUCH_STEPS + _ROUTINE_RISE_STEPS:
        return "rise"
    if step < _ROUTINE_WALK_START:
        return "stand"
    if step < _ROUTINE_STOP_START:
        return "walk"
    if step < _ROUTINE_FINAL_STAND_START:
        return "stop"
    return "stand"


def _routine_obs(env) -> None:
    phase = 2.0 * math.pi * _routine_step(env) / _ROUTINE_PERIOD_STEPS
    walking = _routine_stage(env) == "walk"
    env.twist_cmd[:] = (_ROUTINE_WALK_SPEED if walking else 0.0, 0.0, 0.0)
    if walking:
        yaw = _trunk_yaw(env)
        home_yaw = getattr(env, "home_yaw", yaw)
        error = math.atan2(math.sin(yaw - home_yaw), math.cos(yaw - home_yaw))
        env.twist_cmd[2] = float(np.clip(-4.0 * error, -1.0, 1.0))
    env.body_cmd[4], env.body_cmd[5] = math.sin(phase), math.cos(phase)


def _routine_caption(env) -> str:
    return f"routine: {_routine_stage(env)} ({_routine_step(env) * C.CTRL_DT:.2f} s / 16 s)"


def _routine_crouch_height(env) -> float:
    return _squat_z(env) if _routine_stage(env) == "crouch" else 0.0


def _routine_stand_tall(env) -> float:
    return _stand_tall(env) if _routine_stage(env) != "crouch" else 0.0


def _routine_stand_pose(env) -> float:
    return _pose_home(env) if _routine_stage(env) in ("rise", "stand", "stop") else 0.0


def _routine_stand_still(env) -> float:
    return _run_speed(env) if _routine_stage(env) == "stand" else 0.0


def _routine_keep_pace(env) -> float:
    return _run_speed(env) if _routine_stage(env) == "walk" else 0.0


def _routine_walk_pose(env) -> float:
    return _run_pose(env) if _routine_stage(env) == "walk" else 0.0


def _routine_static_feet(env) -> float:
    return _both_feet_down(env) if _routine_stage(env) != "walk" else 0.0


def _routine_flat_feet(env) -> float:
    return _flat_feet(env) if _routine_stage(env) != "walk" else 0.0


def _routine_still_pen(env) -> float:
    return _still_penalty(env) if _routine_stage(env) != "walk" else 0.0


def _routine_slip_pen(env) -> float:
    return _run_slip_pen(env) if _routine_stage(env) == "walk" else 0.0


def _routine_clearance_pen(env) -> float:
    return _run_clearance_pen(env) if _routine_stage(env) == "walk" else 0.0


def _routine_smooth_pen(env) -> float:
    scale = 0.75 if _routine_stage(env) == "walk" else 2.5
    return scale * _action_rate_pen(env)


_register(Behavior(
    id="crouch_walk_cycle",
    suggest="crouch stand and walk in a loop",
    emoji="🔁",
    title="Crouch, stand and walk cycle",
    description=(
        "Crouch for five seconds, rise for one, stand still for two, walk "
        "straight for five, stop for one, stand still for two, then repeat."
    ),
    how_it_learns=(
        "A clock identifies each part of the sixteen-second cycle. Separate "
        "stand-still rewards make both two-second pauses real targets. A heading "
        "commander keeps the walk straight, while a distilled alpha_walking start "
        "supplies a proven stride. Smoothness is weighted more heavily off the walk."
    ),
    keywords=(
        "crouch stand and walk in a loop", "crouch walk cycle", "squat walk cycle",
        "crouch then walk", "下蹲走路循环", "蹲下站立走路", "下蹲站立行走",
    ),
    terms=(
        RewardTerm("crouch_height", "Points for holding a 5.5 cm deep crouch during its window",
                   4.0, _routine_crouch_height),
        RewardTerm("stand_tall", "Points for full standing height outside the crouch",
                   4.0, _routine_stand_tall),
        RewardTerm("normal_pose", "Points for the normal standing pose outside the walk",
                   1.0, _routine_stand_pose),
        RewardTerm("stand_still", "Big points for no body movement during both two-second pauses",
                   3.0, _routine_stand_still),
        RewardTerm("keep_pace", "Big points for forward speed during the five-second walk",
                   6.0, _routine_keep_pace),
        RewardTerm("track_turn", "Points for tracking straight-ahead heading corrections",
                   2.0, _run_track_ang),
        RewardTerm("pose", "Points for a walking-appropriate leg pose",
                   1.0, _routine_walk_pose),
        RewardTerm("stay_upright", "Points for keeping the body upright throughout the cycle",
                   2.0, _run_upright),
        RewardTerm("head_up", "Points for holding the head near its natural pose",
                   1.0, _head_up_blend),
        RewardTerm("feet_planted", "Points for both feet down outside the walk",
                   1.0, _routine_static_feet),
        RewardTerm("flat_feet", "Points for flat feet outside the walk",
                   0.8, _routine_flat_feet),
        RewardTerm("hold_still", "Penalty for drifting outside the walk",
                   1.0, _routine_still_pen, is_penalty=True),
        RewardTerm("plant_the_foot", "Penalty for planted-foot slipping while walking",
                   0.1, _routine_slip_pen, is_penalty=True),
        RewardTerm("foot_clearance", "Penalty for walking without lifting the swing feet",
                   0.5, _routine_clearance_pen, is_penalty=True),
        RewardTerm("smooth_moves", "Penalty for abrupt actions, stronger outside the walk",
                   1.0, _routine_smooth_pen, is_penalty=True),
        RewardTerm("gentle_joints", "Small penalty for flailing the joints fast",
                   1.0, _joint_vel_pen, is_penalty=True),
        RewardTerm("save_energy", "Small penalty for straining the motors",
                   1.0, _torque_pen, is_penalty=True),
        RewardTerm("no_limit_parking", "Penalty for grinding joints against their end stops",
                   1.0, _limit_parking_pen, is_penalty=True),
    ),
    default_steps=6_000_000,
    success_metric="two cycles with still pauses and straight, full-stride walking, without falling",
    episode_s=32.0,
    symmetric=False,
    height_termination=False,
    forward_cmd=_ROUTINE_WALK_SPEED,
    distill_walker=True,
    checkpoint_every=150_000,
    obs_fn=_routine_obs,
    caption_fn=_routine_caption,
))


def _straight_walk_obs(env) -> None:
    yaw = _trunk_yaw(env)
    home_yaw = getattr(env, "home_yaw", yaw)
    error = math.atan2(math.sin(yaw - home_yaw), math.cos(yaw - home_yaw))
    env.twist_cmd[:] = (0.4, 0.0, float(np.clip(-4.0 * error, -1.0, 1.0)))


_register(Behavior(
    id="straight_walk",
    suggest="walk straight without turning",
    emoji="🚶",
    title="Straight walking only",
    description="Walk forward with full strides and track a straight heading without circling.",
    how_it_learns=(
        "An alpha_walking distilled start supplies the stride. Speed and yaw-rate "
        "tracking dominate the score, while a heading commander gives the policy "
        "an observable correction instead of an unobservable absolute-yaw reward."
    ),
    keywords=("walk straight without turning", "straight walk", "walk straight", "直走", "笔直走路"),
    terms=(
        RewardTerm("keep_pace", "Big points for matching forward speed without sliding sideways",
                   6.0, _run_speed),
        RewardTerm("track_turn", "Big points for tracking the straight-heading correction",
                   6.0, _run_track_ang),
        RewardTerm("pose", "Points for a walking-appropriate leg pose",
                   1.0, _run_pose),
        RewardTerm("stay_upright", "Points for keeping the body upright",
                   2.0, _run_upright),
        RewardTerm("head_up", "Points for tracking the natural head pose",
                   3.5, _run_head_pose),
        RewardTerm("foot_clearance", "Penalty for not lifting the swing feet",
                   1.0, _run_clearance_pen, is_penalty=True),
        RewardTerm("plant_the_foot", "Penalty for planted-foot slipping",
                   0.1, _run_slip_pen, is_penalty=True),
        RewardTerm("smooth_moves", "Penalty for jerky actions",
                   1.0, _action_rate_pen, is_penalty=True),
        RewardTerm("calm_roll", "Penalty for rolling or pitching the trunk too fast",
                   0.025, _run_body_ang_pen, is_penalty=True),
        RewardTerm("no_limit_parking", "Penalty for grinding joints against their end stops",
                   1.0, _limit_parking_pen, is_penalty=True),
    ),
    default_steps=2_000_000,
    success_metric="forward displacement with low lateral error and yaw, without falling",
    episode_s=20.0,
    height_termination=False,
    forward_cmd=0.4,
    distill_walker=True,
    checkpoint_every=100_000,
    obs_fn=_straight_walk_obs,
))


_SQUAT_CYCLE_CROUCH_STEPS = round(5.0 / C.CTRL_DT)
_SQUAT_CYCLE_STAND_STEPS = round(2.0 / C.CTRL_DT)
_SQUAT_CYCLE_WALK_STEPS = round(5.0 / C.CTRL_DT)
_SQUAT_CYCLE_WALK_START = _SQUAT_CYCLE_CROUCH_STEPS + _SQUAT_CYCLE_STAND_STEPS
_SQUAT_CYCLE_FINAL_STAND_START = _SQUAT_CYCLE_WALK_START + _SQUAT_CYCLE_WALK_STEPS
_SQUAT_CYCLE_PERIOD_STEPS = _SQUAT_CYCLE_FINAL_STAND_START + _SQUAT_CYCLE_STAND_STEPS
_SQUAT_CYCLE_WALK_SPEED = 0.4


def _squat_cycle_step(env) -> int:
    return int(env.step_count) % _SQUAT_CYCLE_PERIOD_STEPS


def _squat_cycle_stage(env) -> str:
    step = _squat_cycle_step(env)
    if step < _SQUAT_CYCLE_CROUCH_STEPS:
        return "crouch"
    if step < _SQUAT_CYCLE_WALK_START:
        return "stand"
    if step < _SQUAT_CYCLE_FINAL_STAND_START:
        return "walk"
    return "stand"


def _squat_cycle_is_crouch(env) -> bool:
    return _squat_cycle_stage(env) == "crouch"


def _squat_cycle_obs(env) -> None:
    phase = 2.0 * math.pi * _squat_cycle_step(env) / _SQUAT_CYCLE_PERIOD_STEPS
    walking = _squat_cycle_stage(env) == "walk"
    env.twist_cmd[:] = (_SQUAT_CYCLE_WALK_SPEED if walking else 0.0, 0.0, 0.0)
    if walking:
        yaw = _trunk_yaw(env)
        home_yaw = getattr(env, "home_yaw", yaw)
        error = math.atan2(math.sin(yaw - home_yaw), math.cos(yaw - home_yaw))
        env.twist_cmd[2] = float(np.clip(-4.0 * error, -1.0, 1.0))
    env.body_cmd[4], env.body_cmd[5] = math.sin(phase), math.cos(phase)


def _squat_cycle_caption(env) -> str:
    return (f"squat cycle: {_squat_cycle_stage(env)} "
            f"({_squat_cycle_step(env) * C.CTRL_DT:.2f} s / 14 s)")


def _squat_cycle_crouch_height(env) -> float:
    return _squat_z(env) if _squat_cycle_is_crouch(env) else 0.0


def _squat_cycle_stand_tall(env) -> float:
    return 0.0 if _squat_cycle_is_crouch(env) else _stand_tall(env)


def _squat_cycle_stand_pose(env) -> float:
    return _pose_home(env) if _squat_cycle_stage(env) == "stand" else 0.0


def _squat_cycle_stand_still(env) -> float:
    return _run_speed(env) if _squat_cycle_stage(env) == "stand" else 0.0


def _squat_cycle_keep_pace(env) -> float:
    return _run_speed(env) if _squat_cycle_stage(env) == "walk" else 0.0


def _squat_cycle_walk_pose(env) -> float:
    return _run_pose(env) if _squat_cycle_stage(env) == "walk" else 0.0


def _squat_cycle_static_feet(env) -> float:
    return _both_feet_down(env) if _squat_cycle_stage(env) != "walk" else 0.0


def _squat_cycle_flat_feet(env) -> float:
    return _flat_feet(env) if _squat_cycle_stage(env) != "walk" else 0.0


def _squat_cycle_still_pen(env) -> float:
    return _still_penalty(env) if _squat_cycle_stage(env) != "walk" else 0.0


def _squat_cycle_slip_pen(env) -> float:
    return _run_slip_pen(env) if _squat_cycle_stage(env) == "walk" else 0.0


def _squat_cycle_clearance_pen(env) -> float:
    return _run_clearance_pen(env) if _squat_cycle_stage(env) == "walk" else 0.0


def _squat_cycle_smooth_pen(env) -> float:
    scale = 0.75 if _squat_cycle_stage(env) == "walk" else 2.5
    return scale * _action_rate_pen(env)


_SQUAT_CYCLE_CROUCH_ROOT = np.array([
    0.0, 0.0, 0.063764, 0.997473, -0.010442, 0.021785, 0.066812,
])
_SQUAT_CYCLE_CROUCH_JOINTS = np.array([
    -0.354696, 0.069437, 0.185876, 1.572092, 1.339433,
    0.472521, 0.447006, -0.679569, 0.160407,
    0.251857, 0.120356, -0.738299, -1.572970, -0.799548,
])


def _squat_cycle_spawn_crouch(env):
    d, m = env.data, env.model
    d.qpos[:] = 0.0
    d.qpos[:7] = _SQUAT_CYCLE_CROUCH_ROOT
    d.qpos[env.joint_qpos_adr] = _SQUAT_CYCLE_CROUCH_JOINTS
    d.qvel[:] = 0.0
    d.ctrl[:] = d.qpos[env.joint_qpos_adr]
    mujoco.mj_forward(m, d)
    env.prev_joint_vel = env._joint_vel().copy()
    return env._get_obs()


def _squat_cycle_head_level(env) -> float:
    cid = getattr(env, "_squat_cam_id", None)
    if cid is None:
        cid = mujoco.mj_name2id(env.model, mujoco.mjtObj.mjOBJ_CAMERA, "head_camera")
        if cid < 0:
            raise RuntimeError("scene has no head_camera element")
        env._squat_cam_id = cid
    forward_z = float(env.data.cam_xmat[cid][8])
    elevation = math.asin(max(-1.0, min(1.0, forward_z)))
    return (0.5 * math.exp(-(elevation / 0.7) ** 2)
            + 0.5 * math.exp(-(elevation / 0.25) ** 2))


def _squat_cycle_head_forward(env) -> float:
    q = env._joint_pos_rel()[C.HEAD_JOINT_IDS]
    d2 = float(q[2] ** 2 + q[3] ** 2)
    return 0.5 * math.exp(-d2 / 1.5 ** 2) + 0.5 * math.exp(-d2 / 0.45 ** 2)


_register(Behavior(
    id="crouch_stand_cycle",
    suggest="crouch stand then walk straight",
    emoji="↕️",
    title="Crouch, stand and walk straight",
    description=(
        "Crouch for five seconds, stand still for two, walk straight for five, "
        "then stand still for two before crouching again. Keep the head level."
    ),
    how_it_learns=(
        "A fourteen-second clock separates crouch, two standing pauses and walking. "
        "World-frame gaze and head yaw/roll rewards keep the head up and facing "
        "forward without forbidding small sways. Crouch starts expose the "
        "missing skill before the course removes them. A heading commander keeps "
        "the alpha_walking-inspired stride straight; only the walk pays for speed."
    ),
    keywords=(
        "crouch stand then walk straight", "crouch stand cycle", "squat stand cycle",
        "crouch and stand in a loop", "crouch and stand", "下蹲站立循环",
        "蹲下站起来", "下蹲起立", "下蹲站立直行",
    ),
    terms=(
        RewardTerm("crouch_height", "Big points for a 5.5 cm deep crouch in its window",
                   5.0, _squat_cycle_crouch_height),
        RewardTerm("stand_tall", "Big points for full standing height outside the crouch",
                   5.0, _squat_cycle_stand_tall),
        RewardTerm("normal_pose", "Points for the normal pose during both standing pauses",
                   2.0, _squat_cycle_stand_pose),
        RewardTerm("stand_still", "Big points for no movement during both standing pauses",
                   3.0, _squat_cycle_stand_still),
        RewardTerm("keep_pace", "Big points for forward speed during the five-second walk",
                   6.0, _squat_cycle_keep_pace),
        RewardTerm("track_turn", "Points for tracking straight-ahead heading corrections",
                   2.0, _run_track_ang),
        RewardTerm("pose", "Points for a walking-appropriate leg pose",
                   1.0, _squat_cycle_walk_pose),
        RewardTerm("stay_upright", "Points for keeping the body upright",
                   2.0, _upright),
        RewardTerm("head_up", "Big points for keeping the head and gaze level, not drooped",
                   4.0, _squat_cycle_head_level),
        RewardTerm("head_forward", "Big points for keeping head yaw and roll near forward",
                   20.0, _squat_cycle_head_forward),
        RewardTerm("feet_planted", "Points for both feet down outside the walk",
                   1.5, _squat_cycle_static_feet),
        RewardTerm("flat_feet", "Points for flat feet outside the walk",
                   1.0, _squat_cycle_flat_feet),
        RewardTerm("hold_still", "Penalty for drifting outside the walk",
                   1.5, _squat_cycle_still_pen, is_penalty=True),
        RewardTerm("plant_the_foot", "Penalty for planted-foot slipping while walking",
                   0.1, _squat_cycle_slip_pen, is_penalty=True),
        RewardTerm("foot_clearance", "Penalty for walking without lifting the swing feet",
                   0.5, _squat_cycle_clearance_pen, is_penalty=True),
        RewardTerm("smooth_moves", "Penalty for abrupt actions, stronger outside the walk",
                   1.0, _squat_cycle_smooth_pen, is_penalty=True),
        RewardTerm("gentle_joints", "Small penalty for flailing the joints fast",
                   1.0, _joint_vel_pen, is_penalty=True),
        RewardTerm("save_energy", "Small penalty for straining the motors",
                   1.0, _torque_pen, is_penalty=True),
        RewardTerm("no_limit_parking", "Penalty for grinding joints against their end stops",
                   1.0, _limit_parking_pen, is_penalty=True),
    ),
    default_steps=6_000_000,
    success_metric="two cycles with level-head crouches, still pauses and straight walking",
    episode_s=28.0,
    symmetric=False,
    height_termination=False,
    forward_cmd=_SQUAT_CYCLE_WALK_SPEED,
    distill_walker=True,
    checkpoint_every=150_000,
    spawn_families=((0.0, _squat_cycle_spawn_crouch),),
    obs_fn=_squat_cycle_obs,
    caption_fn=_squat_cycle_caption,
    curriculum=(
        CurriculumStage(
            "discover the deep crouch from crouch starts", 1_000_000,
            {"MICRODUCK_ACTUATOR": "xml", "MICRODUCK_SPAWN_FAMILY_PROBS": "0.85"},
            "Most episodes begin in a real deep crouch with flat feet and a level head.",
        ),
        CurriculumStage(
            "hold the crouch with honest servos", 2_000_000,
            {"MICRODUCK_ACTUATOR": "bam", "MICRODUCK_SPAWN_FAMILY_PROBS": "0.50"},
            "Half the episodes start in the crouch; the rest must enter it from standing.",
        ),
        CurriculumStage(
            "complete every cycle from standing", 3_000_000,
            {"MICRODUCK_ACTUATOR": "bam", "MICRODUCK_SPAWN_FAMILY_PROBS": "0.0"},
            "No crouch spawns: every cycle starts standing and must include the deep crouch.",
        ),
    ),
))


__all__ = [n for n in dir() if not n.startswith("__")]
