import numpy as np
import onnx
import onnxruntime as ort
from onnx import TensorProto, helper, numpy_helper

from microduck_local.compose_policy import compose_policies


def _linear_policy(scale: float) -> onnx.ModelProto:
    indices = numpy_helper.from_array(np.arange(14, dtype=np.int64), "indices")
    factor = numpy_helper.from_array(np.array(scale, dtype=np.float32), "scale")
    gather = helper.make_node("Gather", ["obs", indices.name], ["features"], axis=1)
    multiply = helper.make_node("Mul", ["features", factor.name], ["actions"])
    graph = helper.make_graph(
        [gather, multiply],
        "linear_policy",
        [helper.make_tensor_value_info("obs", TensorProto.FLOAT, [1, 61])],
        [helper.make_tensor_value_info("actions", TensorProto.FLOAT, [1, 14])],
        initializer=[indices, factor],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 18)])
    model.ir_version = 8
    return model


def _run(model_path, obs):
    session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    return session.run(["actions"], {"obs": obs})[0]


def test_composed_policy_selects_the_expected_branch(tmp_path):
    crouch_path = tmp_path / "crouch.onnx"
    walker_path = tmp_path / "walker.onnx"
    out_path = tmp_path / "composite.onnx"
    onnx.save(_linear_policy(1.0), crouch_path)
    onnx.save(_linear_policy(2.0), walker_path)
    composed = compose_policies(crouch_path, walker_path, out_path)
    onnx.checker.check_model(composed, full_check=True)

    obs = np.arange(61, dtype=np.float32)[None]
    obs[0, 48] = 0.0
    np.testing.assert_allclose(_run(out_path, obs), _run(crouch_path, obs), rtol=0, atol=0)
    obs[0, 48] = 0.4
    np.testing.assert_allclose(_run(out_path, obs), _run(walker_path, obs), rtol=0, atol=0)

    assert len(composed.graph.input) == 1
    assert len(composed.graph.output) == 1
    assert composed.graph.input[0].name == "obs"
    assert composed.graph.output[0].name == "actions"
    names = [value.name for value in composed.graph.initializer]
    assert len(names) == len(set(names))
    metadata = {entry.key: entry.value for entry in composed.metadata_props}
    assert metadata["composite.selector"] == "obs[48] > 0.2 selects walking; otherwise crouch"


def test_composed_policy_uses_transition_walker_before_straight_walker(tmp_path):
    crouch_path = tmp_path / "crouch.onnx"
    walker_path = tmp_path / "walker.onnx"
    transition_path = tmp_path / "transition.onnx"
    out_path = tmp_path / "composite.onnx"
    onnx.save(_linear_policy(1.0), crouch_path)
    onnx.save(_linear_policy(2.0), walker_path)
    onnx.save(_linear_policy(3.0), transition_path)
    composed = compose_policies(crouch_path, walker_path, out_path, transition_path, 0.5)
    onnx.checker.check_model(composed, full_check=True)

    obs = np.arange(61, dtype=np.float32)[None]
    obs[0, 48] = 0.4
    obs[0, 60] = -1.0
    np.testing.assert_allclose(_run(out_path, obs), _run(transition_path, obs), rtol=0, atol=0)
    obs[0, 60] = 0.0
    np.testing.assert_allclose(_run(out_path, obs), _run(walker_path, obs), rtol=0, atol=0)
    metadata = {entry.key: entry.value for entry in composed.metadata_props}
    assert metadata["composite.transition_seconds"] == "0.5"


def test_composed_policy_clamps_head_yaw_and_roll_throughout(tmp_path):
    crouch_path = tmp_path / "crouch.onnx"
    walker_path = tmp_path / "walker.onnx"
    out_path = tmp_path / "composite.onnx"
    onnx.save(_linear_policy(1.0), crouch_path)
    onnx.save(_linear_policy(2.0), walker_path)
    compose_policies(crouch_path, walker_path, out_path, center_crouch_head=True)

    obs = np.arange(61, dtype=np.float32)[None]
    obs[0, 48] = 0.0
    actual = _run(out_path, obs)
    expected = _run(crouch_path, obs)
    np.testing.assert_allclose(actual[0, 7:9], [1.2, 1.2], rtol=0, atol=1e-7)
    np.testing.assert_allclose(actual[0, :7], expected[0, :7], rtol=0, atol=0)
    np.testing.assert_allclose(actual[0, 9:], expected[0, 9:], rtol=0, atol=0)
    obs[0, 48] = 0.4
    actual = _run(out_path, obs)
    expected = _run(walker_path, obs)
    np.testing.assert_allclose(actual[0, 7:9], [1.2, 1.2], rtol=0, atol=1e-7)
    np.testing.assert_allclose(actual[0, :7], expected[0, :7], rtol=0, atol=0)
    np.testing.assert_allclose(actual[0, 9:], expected[0, 9:], rtol=0, atol=0)
