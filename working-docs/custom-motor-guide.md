# 自定义电机替换指南

本文档总结在 Microduck 上使用非原装 XL330 电机时的注意事项和完整流程。
适用前提：新电机的**外形尺寸与 XL330 一致**，MJCF 模型无需修改。

---

## 一、选型注意事项

### 必须满足的硬件要求

| 参数 | XL330 参考值 | 说明 |
|---|---|---|
| 额定电压 | 3.7–6.0V | 训练环境有电压 DR，需与仿真范围匹配 |
| 堵转力矩 | ~0.43 Nm | 腿部关节峰值需求，过小则无法支撑 |
| 空载转速 | ~70 RPM @ 5V | 过慢影响步态频率（50 Hz 控制） |
| 通信协议 | Dynamixel P2 / Feetech / 其他 | 决定能否直接用 BAM 现有驱动 |
| 编码器分辨率 | ≥ 12 bit | 位置精度影响 sim2real 迁移 |

### BAM 库已内置支持的电机

直接可用，无需辨识（或可以用已有参数作为初始值）：

- `xl330` — 原装
- `xl320` — Dynamixel，较小力矩
- `mx64` / `mx106` — Dynamixel，较大力矩
- `feetech_sts3215_7_4V` — Feetech 总线舵机，低成本替代
- `erob80_50` / `erob80_100` — 高性能谐波减速电机

**优先从这个列表里选**，可以跳过系统辨识步骤，节省大量时间。

---

## 二、系统辨识流程（电机不在内置列表时）

### 第一步：采集实验数据

需要在**真实电机**上跑驱动 + 反驱动实验，采集位置、速度、电流随时间的曲线。

**Dynamixel / Feetech 电机**，使用 BAM 内置录制脚本：

```bash
# Dynamixel
python -m bam.dynamixel.record --output ./my_motor_logs

# Feetech
python -m bam.feetech.record --output ./my_motor_logs
```

**其他协议电机**，需要自己实现一个录制脚本，输出格式与 BAM 的 `Logs` 类兼容（参考 `bam/logs.py`）。

采集要求：
- 覆盖全速度范围（空载到满载）
- 正转 + 反转各方向
- 至少 3–5 分钟数据
- 采样率 ≥ 100 Hz

### 第二步：拟合 BAM 参数

```bash
python -m bam.fit \
  --logdir ./my_motor_logs \
  --actuator dynamixel \
  --model m6 \
  --output my_motor_params.json \
  --trials 100000
```

拟合完成后验证结果：

```bash
python -m bam.fit \
  --logdir ./my_motor_logs \
  --actuator dynamixel \
  --model m6 \
  --output my_motor_params.json \
  --eval
```

输出的 `my_motor_params.json` 包含：

```json
{
    "kt": ...,              // 力矩常数 Nm/A
    "R": ...,               // 电阻 Ω
    "armature": ...,        // 转子惯量 kg·m²
    "friction_base": ...,   // 静摩擦
    "friction_viscous": ...,// 粘性摩擦
    ...
}
```

### 第三步：注册新电机参数

将 JSON 文件放入 BAM 参数库：

```bash
mkdir -p microduck_rl/.venv/lib/python3.12/site-packages/bam/params/my_motor
cp my_motor_params.json microduck_rl/.venv/lib/python3.12/site-packages/bam/params/my_motor/m6.json
```

---

## 三、修改训练配置

> **平台说明：**
> - `microduck_local`（本地 CPU harness）— 在 Mac（包括 Apple Silicon）上直接运行，用于原型验证
> - `microduck_rl`（MuJoCo Warp）— 需要 **NVIDIA CUDA GPU**，MuJoCo Warp 不支持 Apple Silicon 的 Metal/MPS。正式训练需租用 NVIDIA 云机器（如 HuggingFace Jobs、Lambda Labs、Vast.ai 等）
>
> 推荐工作流：**Mac 上用 `microduck_local` 验证电机参数和行为可行性 → 移植到 `microduck_rl` 用 GPU 做最终训练 → 导出 ONNX 部署真机**

### 3.1 修改电机型号（microduck_rl，需要 NVIDIA GPU）

文件：`microduck_rl/src/mjlab_microduck/robot/microduck_constants.py`

```python
_BAM_ACTUATOR_KWARGS = dict(
    motor_name="my_motor",   # 改这里
    kp_fw=200.0,             # 固件 PD 刚度，见下方说明
    ...
)
```

### 3.2 修改本地 CPU harness

文件：`microduck_local/src/microduck_local/walk_env.py`

同样找到 BAM actuator 初始化处，改 `motor_name`。

### 3.3 标定固件刚度 kp_fw

`kp_fw` 是电机固件的位置环 PD 刚度，**必须与你的电机固件实际配置一致**，否则仿真和真机行为不匹配。

- XL330 默认：`kp_fw = 200`
- 测量方法：在真机上施加已知力矩，测量稳态位置误差，反推 kp
- 或者直接读取电机固件寄存器（Dynamixel: `Present_Position_P_Gain`）

---

## 四、验证步骤（改完后必做）

### 4.1 合规测试

```bash
cd microduck_local
uv run --with pytest pytest tests/
```

所有测试必须通过，特别是：
- `test_env_contract.py` — obs/action 维度不变
- `test_walk_env_physics.py` — DR 参数范围正确

### 4.2 仿真物理验证

在训练之前，验证新电机参数下的仿真物理是否合理：

```bash
uv run render-rollout --policy ../microduck/policies/alpha_walking.onnx \
  --behavior run --out /tmp/motor-check
```

观察视频：
- 鸭子应该能走（官方策略在新电机参数下能走，说明参数合理）
- 如果摔倒或抖动剧烈，说明 `kp_fw` 或摩擦参数偏差太大

### 4.3 重新训练

参数验证通过后，从官方策略热启动训练：

```bash
uv run train-walk --envs 24 --steps 15_000_000 --run-name my-motor-v1 \
  --init-from ../microduck/policies/alpha_walking.onnx
```

用 `--behavior run` 渲染验证：

```bash
uv run export-walk runs/my-motor-v1
uv run render-rollout --policy runs/my-motor-v1/policy.onnx --behavior run --out /tmp/rr-my-motor
```

---

## 五、sim2real 注意事项

- **不要直接把 XL330 训练的策略部署到新电机上**，力矩常数和摩擦特性不同会导致抖动或摔倒
- BAM 参数的误差会被 Domain Randomization 的 `friction_scale_range` 部分吸收，但差异太大（>30%）时 DR 范围不足以覆盖
- 部署前必须用 `microduck_rl/scripts/infer_policy.py` 在真机上做推理测试，确认 obs 命令槽写法正确
- 新电机的**编码器延迟**如果与 XL330 不同，需要相应调整 `joint_vel` 的滞后步数（默认 1 步）

---

## 六、无 GPU 折中方案（仅 Mac CPU）

没有 NVIDIA GPU 时，跳过 `microduck_rl`，完全在 `microduck_local` 上完成验证和训练，直接导出 ONNX 部署真机。策略质量比 GPU 版低，但足以验证新电机能不能走。

### 6.1 系统辨识（内置列表外才需要）

注册参数到 `microduck_local` 的 venv，不是 `microduck_rl`：

```bash
cd microduck_local

# 采集数据
uv run python -m bam.dynamixel.record --output ./my_motor_logs
uv run python -m bam.feetech.record --output ./my_motor_logs   # Feetech 用这条

# 拟合
uv run python -m bam.fit \
  --logdir ./my_motor_logs \
  --actuator dynamixel \
  --model m6 \
  --output my_motor_params.json \
  --trials 100000

# 验证拟合质量
uv run python -m bam.fit \
  --logdir ./my_motor_logs \
  --actuator dynamixel \
  --model m6 \
  --output my_motor_params.json \
  --eval

# 注册到本地 venv
mkdir -p .venv/lib/python3.12/site-packages/bam/params/my_motor
cp my_motor_params.json .venv/lib/python3.12/site-packages/bam/params/my_motor/m6.json
```

### 6.2 修改 walk_env.py 加载新参数

`BamXL330Actuator` 没有 `motor_name` 参数，通过 `params=` 字典传入是最安全的方式（不改源码）。

在 `microduck_local/src/microduck_local/walk_env.py` 找到 `BamXL330Actuator(...)` 的调用处（约 490 行），改为：

```python
import json as _json
_my_params = _json.load(open("my_motor_params.json"))

self.bam = BamXL330Actuator(
    self.model, self.data, C.JOINT_NAMES,
    dt=C.PHYSICS_DT,
    params=_my_params,      # ← 新增
    kp_fw=YOUR_KP_FW,       # ← 改成你的固件刚度（XL330 默认 200.0）
    ...
)
```

或者直接改 `bam_actuator.py` 第 306 行，把 `"xl330"` 改成 `"my_motor"`：

```python
with open(_resolve_json_path(None, "my_motor", "m6")) as fh:
```

### 6.3 验证物理正确性

```bash
cd microduck_local

# 合规测试
uv run --with pytest pytest tests/

# 官方策略在新电机参数下应该还能走；摔倒或抖动说明参数偏差太大
uv run render-rollout \
  --policy ../microduck/policies/alpha_walking.onnx \
  --behavior stand --out /tmp/motor-check
```

### 6.4 本地训练 + 导出

```bash
cd microduck_local

uv run train-walk \
  --envs 32 \
  --steps 20_000_000 \
  --actuator bam \
  --run-name my-motor-v1

uv run export-walk runs/my-motor-v1

uv run render-rollout \
  --policy runs/my-motor-v1/policy.onnx \
  --behavior stand --out /tmp/rr-my-motor
```

### 与 GPU 方案对比

| | 本地 CPU | GPU (microduck_rl) |
|---|---|---|
| 训练时间 | ~30–60 分钟 | ~15 分钟 |
| 策略质量 | 够验证可行性 | sim2real 更稳 |
| 适用场景 | 确认新电机能不能走 | 最终部署到真机 |

本地跑通后，若需要更好的部署质量，再租 GPU 用 `microduck_rl` 做最终训练。

---

## 七、快速决策树

```
新电机是否在 BAM 内置列表？
├── 是 → 直接改 motor_name → 跑合规测试 → 重新训练
└── 否 → 系统辨识 → 注册参数 → 改 motor_name → 跑合规测试 → 重新训练

通信协议是否 Dynamixel 或 Feetech？
├── 是 → 用 BAM 内置录制脚本采集数据
└── 否 → 自己实现录制接口（参考 bam/logs.py 格式）

有没有 NVIDIA GPU？
├── 有 → 用 microduck_rl 做最终训练（更好的 sim2real）
└── 没有 → 用第六节的纯 CPU 流程，直接从 microduck_local 导出部署
```
