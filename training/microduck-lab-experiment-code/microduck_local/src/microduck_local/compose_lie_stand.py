"""Compose a lie-down policy and alpha_stand into one timed ONNX controller."""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import onnx
from onnx import TensorProto, compose, helper, numpy_helper


def _load(path: Path) -> onnx.ModelProto:
    model = onnx.load(path)
    inp = model.graph.input[0]
    out = model.graph.output[0]
    in_shape = [d.dim_value for d in inp.type.tensor_type.shape.dim]
    out_shape = [d.dim_value for d in out.type.tensor_type.shape.dim]
    if in_shape != [1, 61] or out_shape != [1, 14]:
        raise ValueError(f"{path}: expected obs[1,61] -> actions[1,14]")
    return model


def compose_lie_stand(lie_path: Path, stand_path: Path, out_path: Path) -> onnx.ModelProto:
    lie_source, stand_source = _load(lie_path), _load(stand_path)
    lie = compose.add_prefix(lie_source, "lie_", rename_inputs=True)
    stand = compose.add_prefix(stand_source, "stand_", rename_inputs=True)

    start = numpy_helper.from_array(np.array([0], np.int64), "obs_start")
    command_start = numpy_helper.from_array(np.array([48], np.int64), "command_start")
    axes = numpy_helper.from_array(np.array([1], np.int64), "obs_axes")
    command_zeros = numpy_helper.from_array(np.zeros((1, 13), np.float32), "command_zeros")
    selector_index = numpy_helper.from_array(np.array(48, np.int64), "selector_index")
    selector_threshold = numpy_helper.from_array(np.array(0.5, np.float32), "selector_threshold")

    nodes = [
        # The routine env puts a 0/1 selector in obs[48], but neither child was
        # trained on it. Strip all 13 command slots before child inference.
        helper.make_node("Slice", ["obs", start.name, command_start.name, axes.name],
                         ["sensor_obs"]),
        helper.make_node("Concat", ["sensor_obs", command_zeros.name], ["policy_obs"], axis=1),
        helper.make_node("Identity", ["policy_obs"], [lie.graph.input[0].name]),
        helper.make_node("Identity", ["policy_obs"], [stand.graph.input[0].name]),
        helper.make_node("Gather", ["obs", selector_index.name], ["lie_selector"], axis=1),
        helper.make_node("Greater", ["lie_selector", selector_threshold.name], ["lying"]),
        *lie.graph.node,
        *stand.graph.node,
        helper.make_node("Where", ["lying", lie.graph.output[0].name,
                                   stand.graph.output[0].name], ["actions"]),
    ]
    graph = helper.make_graph(
        nodes, "lie_stand_cycle", [helper.make_tensor_value_info("obs", TensorProto.FLOAT, [1, 61])],
        [helper.make_tensor_value_info("actions", TensorProto.FLOAT, [1, 14])],
        initializer=[*lie.graph.initializer, *stand.graph.initializer, start, command_start,
                     axes, command_zeros, selector_index, selector_threshold],
        value_info=[*lie.graph.value_info, *stand.graph.value_info],
    )
    model = helper.make_model(graph, producer_name="microduck-local",
                              opset_imports=[helper.make_opsetid("", 18)])
    model.ir_version = 8
    model.metadata_props.extend(lie_source.metadata_props)
    for key, value in (
        ("composite.lie", str(lie_path)),
        ("composite.stand", str(stand_path)),
        ("composite.selector", "obs[48] > 0.5 selects lie; otherwise alpha_stand"),
        ("composite.behavior", "lie_stand_cycle"),
    ):
        model.metadata_props.add(key=key, value=value)
    onnx.checker.check_model(model, full_check=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    onnx.save_model(model, out_path)
    return model


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lie", type=Path)
    parser.add_argument("stand", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    compose_lie_stand(args.lie, args.stand, args.out)
    print(f"wrote {args.out}: 6 s lie (about 1 s transition + 5 s hold), "
          "6 s stand (about 1 s get-up + 5 s hold)")


if __name__ == "__main__":
    main()
