from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import onnx
from onnx import TensorProto, compose, helper, numpy_helper


def _load_policy(path: Path) -> onnx.ModelProto:
    model = onnx.load(path)
    inputs = [(value.name, [dim.dim_value for dim in value.type.tensor_type.shape.dim])
              for value in model.graph.input]
    outputs = [(value.name, [dim.dim_value for dim in value.type.tensor_type.shape.dim])
               for value in model.graph.output]
    if inputs != [("obs", [1, 61])] or outputs != [("actions", [1, 14])]:
        raise ValueError(f"{path}: expected obs[1,61] -> actions[1,14], got {inputs} -> {outputs}")
    return model


def compose_policies(crouch_path: Path, walker_path: Path, out_path: Path,
                     transition_walker_path: Path | None = None,
                     transition_seconds: float = 0.5,
                     center_crouch_head: bool = False) -> onnx.ModelProto:
    crouch_source = _load_policy(crouch_path)
    walker_source = _load_policy(walker_path)
    transition_source = _load_policy(transition_walker_path) if transition_walker_path else None
    crouch = compose.add_prefix(crouch_source, "crouch_", rename_inputs=False)
    walker = compose.add_prefix(walker_source, "walker_", rename_inputs=True)
    transition = (compose.add_prefix(transition_source, "transition_", rename_inputs=False)
                  if transition_source else None)

    index = numpy_helper.from_array(np.array(48, dtype=np.int64), "walk_command_index")
    threshold = numpy_helper.from_array(np.array(0.2, dtype=np.float32), "walk_command_threshold")
    slice_start = numpy_helper.from_array(np.array([0], dtype=np.int64), "walker_slice_start")
    slice_end = numpy_helper.from_array(np.array([59], dtype=np.int64), "walker_slice_end")
    slice_axes = numpy_helper.from_array(np.array([1], dtype=np.int64), "walker_slice_axes")
    phase_zeros = numpy_helper.from_array(np.zeros((1, 2), dtype=np.float32), "walker_phase_zeros")
    nodes = [
        helper.make_node("Slice", ["obs", slice_start.name, slice_end.name, slice_axes.name],
                         ["walker_obs_prefix"]),
        helper.make_node("Concat", ["walker_obs_prefix", phase_zeros.name], ["walker_obs"], axis=1),
        helper.make_node("Gather", ["obs", index.name], ["walk_vx"], axis=1),
        helper.make_node("Greater", ["walk_vx", threshold.name], ["walking"]),
    ]
    initializers = [*crouch.graph.initializer, *walker.graph.initializer, index, threshold,
                    slice_start, slice_end, slice_axes, phase_zeros]
    subgraphs = [*crouch.graph.node, *walker.graph.node]
    value_info = [*crouch.graph.value_info, *walker.graph.value_info]
    walking_output = walker.graph.output[0].name
    crouch_output = crouch.graph.output[0].name
    if transition is not None:
        if not 0.0 < transition_seconds < 5.0:
            raise ValueError("transition_seconds must be between 0 and 5")
        cosine_index = numpy_helper.from_array(np.array(60, dtype=np.int64), "phase_cosine_index")
        cosine_threshold = numpy_helper.from_array(
            np.array(-np.cos(2.0 * np.pi * transition_seconds / 14.0), dtype=np.float32),
            "transition_cosine_threshold",
        )
        initializers.extend([*transition.graph.initializer, cosine_index, cosine_threshold])
        subgraphs.extend(transition.graph.node)
        value_info.extend(transition.graph.value_info)
        nodes.extend([
            helper.make_node("Gather", ["obs", cosine_index.name], ["phase_cosine"], axis=1),
            helper.make_node("Greater", ["phase_cosine", cosine_threshold.name], ["after_transition"]),
            helper.make_node("Where", ["after_transition", walking_output,
                                      transition.graph.output[0].name], ["walking_actions"]),
        ])
        walking_output = "walking_actions"
    selected_output = "raw_actions" if center_crouch_head else "actions"
    nodes.append(helper.make_node(
        "Where", ["walking", walking_output, crouch_output], [selected_output],
    ))
    if center_crouch_head:
        head_start = numpy_helper.from_array(np.array([7], dtype=np.int64), "head_start")
        head_end = numpy_helper.from_array(np.array([9], dtype=np.int64), "head_end")
        action_end = numpy_helper.from_array(np.array([14], dtype=np.int64), "action_end")
        head_min = numpy_helper.from_array(np.array(-1.2, dtype=np.float32), "head_min")
        head_max = numpy_helper.from_array(np.array(1.2, dtype=np.float32), "head_max")
        initializers.extend([head_start, head_end, action_end, head_min, head_max])
        nodes.extend([
            helper.make_node("Slice", ["raw_actions", slice_start.name, head_start.name, slice_axes.name],
                             ["head_prefix"]),
            helper.make_node("Slice", ["raw_actions", head_start.name, head_end.name, slice_axes.name],
                             ["head_yaw_roll"]),
            helper.make_node("Clip", ["head_yaw_roll", head_min.name, head_max.name], ["head_limited"]),
            helper.make_node("Slice", ["raw_actions", head_end.name, action_end.name, slice_axes.name],
                             ["head_suffix"]),
            helper.make_node("Concat", ["head_prefix", "head_limited", "head_suffix"], ["actions"], axis=1),
        ])
    output = helper.make_tensor_value_info("actions", TensorProto.FLOAT, [1, 14])
    graph = helper.make_graph(
        [*nodes[:2], *subgraphs, *nodes[2:]],
        "crouch_walk_composite", [crouch.graph.input[0]], [output],
        initializer=initializers, value_info=value_info,
    )
    model = helper.make_model(
        graph, producer_name="microduck-local", opset_imports=[helper.make_opsetid("", 18)],
    )
    model.ir_version = 8
    model.metadata_props.extend(crouch_source.metadata_props)
    metadata = [
        ("composite.crouch", str(crouch_path)),
        ("composite.walker", str(walker_path)),
        ("composite.selector", "obs[48] > 0.2 selects walking; otherwise crouch"),
    ]
    if transition_source is not None:
        metadata.extend([
            ("composite.transition_walker", str(transition_walker_path)),
            ("composite.transition_seconds", str(transition_seconds)),
        ])
    if center_crouch_head:
        metadata.append(("composite.center_crouch_head", "head_yaw and head_roll are clamped to +/-1.2 rad throughout"))
    for key, value in metadata:
        model.metadata_props.add(key=key, value=value)
    onnx.checker.check_model(model, full_check=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    onnx.save_model(model, out_path)
    return model


def main() -> None:
    parser = argparse.ArgumentParser(description="Compose crouch/stand and walking ONNX policies")
    parser.add_argument("crouch", type=Path)
    parser.add_argument("walker", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--transition-walker", type=Path)
    parser.add_argument("--transition-seconds", type=float, default=0.5)
    parser.add_argument("--center-crouch-head", action="store_true")
    args = parser.parse_args()
    compose_policies(args.crouch, args.walker, args.out, args.transition_walker,
                     args.transition_seconds, args.center_crouch_head)
    print(f"wrote {args.out}: obs[1,61] -> actions[1,14], walk when obs[48] > 0.2")


if __name__ == "__main__":
    main()
