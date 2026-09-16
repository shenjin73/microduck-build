# 自定义电机替换指南

本文档总结在 Microduck 上使用非原装 XL330 电机时的注意事项和完整流程。

> **本次修订（2026-09-16）：** 初版有 8 处会直接误导操作的问题，已全部按源码实测修正。
> 逐条差异见文末「附录：与初版的差异」。所有命令行参数、模块名、文件行号都已在本仓
> 当前 checkout 上实际验证过（验证方式注明在对应位置）。

---

## 〇、先明确一件事：换电机不只是改一个名字

Microduck 的 sim2real 核心是 **BAM actuator 模型**：
`microduck_rl` 用 `FrictionDRBamActuatorCfg`（`motor_name="xl330"`, `model="m6"`, `kp_fw=200.0`,
`vin_range=(6.5, 8.2)`, `delay_min/max_lag=3/6`），`microduck_local` 用它的 CPU port。
换电机意味着同时改变：**力矩常数、电流限制、速度常数、固件 P 增益语义、摩擦、齿隙、
编码器读数、总线延迟、热保护**。改 `motor_name` 只是最后一步。

---

## 一、选型注意事项

### 1.1 必须满足的硬件要求

下表右列是 **repo 实际训练/部署时用的参数**，不是 datasheet 值——选型要对齐的是这一列。

| 参数 | **repo 实际假设（XL330）** | 说明 |
|---|---|---|
| 供电电压 | **`vin = 7.5V` nominal**；DR 范围 **`6.5–8.2V`** | 2S Li-ion 区间；runtime 电池映射 `6.6V`（空）–`8.2V`（满） |
| 固件电流限制 | **`1.75 A`**（`XL330_MAX_CURRENT`） | BAM 用它算可持续扭矩 |
| 可持续扭矩 | **`kt × 1.75A ≈ 0.6405 Nm`** | `XL330_MAX_TORQUE = 0.36601349688984386 × 1.75` |
| 空载转速 | ~70 RPM @ 5V | 影响步态频率（50 Hz 控制） |
| 通信协议 | Dynamixel Protocol 2.0，`1_000_000` baud | runtime 写死 `rustypot` 的 `Xl330Controller` |
| 编码器分辨率 | 4096 counts/rev | 位置精度直接影响 sim2real |
| 固件 P 增益 | `kp_fw = 200.0` | 必须与你的电机固件实际值一致 |

> ⚠️ **不要只看 datasheet 的堵转力矩。** XML 小信号口径的力矩上限约 0.96 Nm，但那
> **不是固件电流限制后的可持续能力**（BAM 口径是 0.64 Nm）。选型要看的是
> 「供电电压 + 固件限流 + 速度常数 + 闭环 P 增益 + 热保护」这一组。

### 1.2 BAM 内置支持 —— **注意有两个不同的命名空间**

这是初版最容易搞错的地方。BAM 有**两套**名字，用途不同：

| 用途 | 取值来源 | 可用值 |
|---|---|---|
| **辨识**（`bam.fit --actuator`） | `bam/actuators.py` 的字典键 | `xl330`, `xl330i`, `xl320`, `mx64`, `mx106`, **`sts3215`**, `erob80_50`, `erob80_100`, `unitree_go1` |
| **训练**（`BamActuatorCfg(motor_name=...)`） | **`bam/params/` 下的目录名** | `xl330`, `xl320`, `mx64`, `mx106`, `erob80_50`, `erob80_100`, **`feetech_sts3215_7_4V`** |

**它们不总是一样。** Feetech 就是例外：辨识侧叫 `sts3215`，训练侧目录名是
`feetech_sts3215_7_4V`。实测（`_resolve_json_path`）：

```text
motor_name='xl330'                 model='m6' -> params/xl330/m6.json              ✓
motor_name='feetech_sts3215_7_4V'  model='m1' -> params/feetech_sts3215_7_4V/m1.json ✓
motor_name='sts3215'               model='m1' -> FileNotFoundError: Available motors: [...]  ✗
motor_name='feetech_sts3215_7_4V'  model='m6' -> FileNotFoundError: Available models: ['m1'] ✗
```

**可用参数文件（实测）：**

| 目录 | 可用 model |
|---|---|
| `xl330` | **m1, m2, m3, m4, m5, m6**（`m6` 是带摩擦的完整模型） |
| `feetech_sts3215_7_4V` | **只有 `m1`** |
| 其余（`xl320`/`mx64`/`mx106`/`erob80_*`） | 见各自目录 |

> ⚠️ `bam/mjlab.py` 的 docstring 写「支持的 motor_name：xl330, xl320, mx106, mx64,
> **erob80:50**, erob80:100」——**这份 docstring 与实际不符**：目录名是 `erob80_50`
> （下划线不是冒号），而且它没列 `feetech_sts3215_7_4V`。**以 `bam/params/` 的目录名为准。**

### 1.3 Feetech / HD-1910 的真实情况

**`HD-1910-C001` 不在 BAM 任何内置参数库里。** 也不要用 STS3215 的参数代替——两者
控制/电机/齿轮箱不同，且 STS3215 只有 `m1`（不是 XL330 那种 `m6` 摩擦模型）。

HD-1910 的选型验证表（协议、半双工电平、位置/速度单位、P/I/D 语义、电流/电压/温度读数、
返回延迟、backlash）见 `microduck-clone-validation-risk-plan.md` §3.2。

### 1.4 「外形尺寸一致」**不足以免改 MJCF**

> 初版写「外形尺寸与 XL330 一致 → MJCF 模型无需修改」，**过于乐观，已修正**。

即使外壳尺寸相同，仍必须复核：

| 项目 | 为什么 | 判断规则 |
|---|---|---|
| 每个 servo 的**质量与惯量** | 800g 小双足对质量极敏感 | 总质量差 > 5% → 必须改 MJCF |
| **CoM**（trunk / head assembly） | 直接决定平衡 | CoM 差 > 5–10 mm → 必须改 MJCF/DR |
| 输出轴位置、horn 厚度、安装偏移 | 关节 frame 会偏 | 关节 frame 变 → 必须改 |
| 可达角度 / 机械限位 | 影响动作空间 | 限位不同 → 必须改 XML + runtime clamp |
| **齿隙 / backlash** | 小舵机齿隙会破坏 sim2real | 测量 deadband；必要时用 backlash 变体训练 |
| 线缆、连接板、主板、电池位置 | 改变 CoM | 计入上表 |
| 脚底材料/摩擦 | 影响步态 | 实测 |

`microduck_local` 的域随机化（`walk_env.py`）只能覆盖**小**偏差：

```python
MASS_SCALE_RANGE = (0.95, 1.05)
ARMATURE_SCALE_RANGE = (0.9, 1.1)
TRUNK_COM_STAGES = ((0, 0.003), (12_000, 0.005), (24_000, 0.010), (36_000, 0.015))
```

**结论：可以先不改碰撞几何，但必须复核质量/惯量/CoM/限位/齿隙。**

---

## 二、系统辨识流程（电机不在内置列表时）

### 2.0 先装依赖（初版完全没提，缺了必然报错）

BAM 的辨识工具链**不在任何 venv 的默认依赖里**。实测当前环境：

| 模块 | 实测结果 |
|---|---|
| `import bam.fit` | `ModuleNotFoundError: No module named 'optuna'` |
| `import bam.feetech.record` | `ModuleNotFoundError: No module named 'pypot'` |
| `import bam.dynamixel.record` | `ModuleNotFoundError: No module named 'dynamixel_sdk'` |
| `import bam.process` | ✅ 可导入（无第三方依赖） |

```bash
# 在你要用的那个 venv 里（microduck_local 或 microduck_rl）
uv pip install optuna wandb pypot dynamixel-sdk
#   optuna + wandb  → bam.fit 必需（bam/fit.py 顶部直接 import 两者）
#   pypot           → bam.feetech.record 必需
#   dynamixel-sdk   → bam.dynamixel.record 必需
```

### 2.1 采集原始数据

**参数名以源码为准**（初版写的 `--output` **不存在**）：

```bash
# Feetech
python -m bam.feetech.record \
  --logdir ./raw_logs --mass 0.0 --length 0.0 --motor sts3215 --id 1 --kp 32

# Dynamixel（多一个 --arm-mass）
python -m bam.dynamixel.record \
  --logdir ./raw_logs --mass 0.0 --arm-mass 0.0 --length 0.0 --motor xl330 --kp 200
```

实际参数（`bam/feetech/record.py` / `bam/dynamixel/record.py`）：

| 参数 | Feetech | Dynamixel | 说明 |
|---|---|---|---|
| `--logdir` | **必填** | **必填** | 初版误写为 `--output` |
| `--mass` / `--length` / `--motor` | **必填** | **必填** | 摆杆质量/长度/电机名 |
| `--arm-mass` | — | **必填** | |
| `--id` | **必填** | — | |
| `--port` | 默认 `/dev/ttyUSB0` | 默认 `/dev/ttyUSB0` | **见下方警告** |
| `--trajectory` | 默认 `lift_and_drop` | 同 | |
| `--kp` | 默认 32 | 默认 32 | 要与固件实际值一致 |
| `--vin` | 默认 **15.0** | 默认 **15.0** | ⚠️ 对 2S/6V 舵机必须显式改成实际值 |

> 🐛 **`bam.feetech.record` 没有正确使用 `--port` / `--id`（源码级 bug，实测确认）：**
> 它声明了这两个参数，但正文硬编码：
> ```python
> io = FeetechSTS3215IO("/dev/ttyACM0")   # 忽略 --port
> ids = [1]                               # 忽略 --id
> io.set_mode({1: 0})                     # 全部写死 motor 1
> ```
> 采集 Feetech 前必须**先改这个脚本**（或自己写采集脚本），否则无论怎么传参都只连
> `/dev/ttyACM0` 的 1 号电机。Dynamixel 侧同一路径也要检查。

**采集要求：** 覆盖全速度范围（空载→满载）、正反转双向、≥3–5 分钟、采样率 ≥100 Hz。

### 2.2 重采样（初版缺失，`bam.fit` 读的是 processed JSON）

`bam.fit` 读的不是原始 log，而是 `bam.process` 重采样后的固定 `dt` 数据：

```bash
python -m bam.process --raw ./raw_logs --logdir ./processed_logs --dt 0.005
```

实测参数：`--raw`（必填）、`--logdir`（必填）、`--dt`（默认 `0.005`）。

### 2.3 拟合

```bash
python -m bam.fit \
  --logdir ./processed_logs \
  --actuator sts3215 \
  --model m1 \
  --output my_motor_params.json \
  --trials 100000
```

> ⚠️ **`--actuator` 必须是 `bam/actuators.py` 里的键。**
> 初版写 `--actuator dynamixel`——那会**直接 `KeyError`**，因为 `bam/fit.py:86` 是
> 字典查找 `actuators[args.actuator]()`，没有 `dynamixel` 这个键。
> 正确取值见 §1.2 的表（XL330 → `xl330`，Feetech STS3215 → `sts3215`）。

`bam.fit` 的完整参数：`--logdir` `--output`(默认 `params.json`) `--method`(默认 `cmaes`)
`--actuator` `--model` `--trials`(默认 100000) `--workers` `--load-study` `--reset_period`
`--wandb` `--set` `--validation_kp` `--eval`（后两个是下划线，不是连字符）。

拟合质量验证：

```bash
python -m bam.fit --logdir ./processed_logs --actuator sts3215 --model m1 \
  --output my_motor_params.json --eval
```

### 2.4 注册参数：**用 `json_path`，不要复制进 site-packages**

> 初版让你把 JSON `cp` 到 `.venv/lib/python3.12/site-packages/bam/params/<motor>/`。
> **这是错的长期方案**：`uv sync` 会重建 venv、HF Jobs 上是全新环境，都会丢失，
> 而且不可复现。

正确做法是把 JSON **放进 repo**，用 `BamActuatorCfg` 的 `json_path` 字段
（实测存在于 `bam/mjlab.py:112`，与 `motor_name`/`model` **互斥**）：

```text
microduck_rl/params/hd1910/m1.json        # 放进 repo，跟着 git 走
```

---

## 三、修改训练配置

> **平台说明：**
> - `microduck_local`（本地 CPU harness）— Mac（含 Apple Silicon）直接跑，用于原型验证
> - `microduck_rl`（MuJoCo Warp）— 需要 **NVIDIA CUDA GPU**；Apple Silicon 上
>   warp 只有 CPU 设备，官方命令需 `CUDA_VISIBLE_DEVICES=""` 才进 CPU 模式，
>   但那只有 ~950 steps/s（`microduck_local` 同机是 ~19,000）。详见
>   `apple-silicon-throughput-benchmark.md`。

### 3.1 修改电机型号（`microduck_rl`，需要 NVIDIA GPU）

文件：`microduck_rl/src/mjlab_microduck/robot/microduck_constants.py`

```python
from pathlib import Path

_BAM_ACTUATOR_KWARGS = dict(
    # 二选一：内置电机用 motor_name + model，自定义用 json_path（互斥）
    json_path=str(Path(__file__).resolve().parents[3] / "params" / "hd1910" / "m1.json"),
    target_names_expr=(r"^(?!passive_).*",),
    kp_fw=YOUR_MEASURED_KP,          # 实测/固件值，XL330 是 200.0
    vin_range=(6.5, 8.2),
    vin_drop_gain_range=(0.0, 0.2),
    vin_min=6.0,
    delay_min_lag=MEASURED_MIN_LAG,  # XL330 是 3
    delay_max_lag=MEASURED_MAX_LAG,  # XL330 是 6
)
actuators = FrictionDRBamActuatorCfg(**_BAM_ACTUATOR_KWARGS)
```

> 若用内置电机（例如临时对照），把 `json_path` 换成 `motor_name="xl330", model="m6"`。
> **不要同时给两者**——`BamActuatorCfg` 会直接报错。

### 3.2 修改本地 CPU harness（`microduck_local`）

文件：`src/microduck_local/bam_actuator.py` 的 `BamXL330Actuator`，
调用处在 `src/microduck_local/walk_env.py:490`。

**⚠️ 仅传 `params=` 不足以完整换电机。** `BamXL330Actuator` 虽然接受
`params` / `kp_fw` / `max_current`，但**控制律仍硬编码 XL330 常数**
（`bam_actuator.py:258-273`，在 `__init__` 里直接赋值）：

```python
XL330_ENCODER_COUNTS_PER_REV = 4096
XL330_KP_DIVISOR             = 256
XL330_PWM_LIMIT              = 885
XL330_ERROR_GAIN             = (4096 / (2π)) / (256 × 885)
XL330_MAX_PWM                = 1.0
XL330_MAX_CURRENT            = 1.75
XL330_NOMINAL_VIN            = 7.5
# __init__ 里：self.error_gain = XL330_ERROR_GAIN; self.max_pwm = XL330_MAX_PWM  ← 未走 spec
```

所以对 Feetech/HD-1910，你**至少**要显式参数化：

- `error_gain`（P 增益语义与 PWM 换算）
- `max_pwm`
- `max_current`（或「无电流限制」）
- 固件 kp 语义（速度/位置单位换算）
- `delay_min_lag` / `delay_max_lag`
- **内部目标速度限制**：BAM 的 STS3215 actuator 有
  `q_target_smooth = clamp(q_target, prev ± max_velocity × dt)`。若 HD-1910 也有，
  `microduck_local` 必须模拟它，否则控制律仍是 XL330。

**建议改法：** 新增 `BamServoSpec` dataclass，把上述常数从 XL330 常量改为 spec 字段，
**不要把 Feetech 伪装成 XL330**。

参数文件加载点在 `bam_actuator.py:304-306`：

```python
from bam.model import _resolve_json_path
with open(_resolve_json_path(None, "xl330", "m6")) as fh:   # ← 改 "xl330"/"m6"
```

### 3.3 标定固件刚度 `kp_fw`

`kp_fw` 是电机固件位置环的 PD 刚度，**必须与真机固件实际配置一致**，否则仿真与真机不匹配。

- XL330：`kp_fw = 200.0`（源码头注释：microban 用 125）
- 测量法：真机施加已知力矩，测稳态位置误差反推
- 或直接读固件寄存器（Dynamixel：`Present_Position_P_Gain`）

---

## 四、验证步骤（改完后必做）

### 4.1 合规测试

```bash
cd microduck_local
uv run --with pytest pytest tests/
```

必过项：`test_env_contract.py`（obs/action 维度不变）、`test_walk_env_physics.py`
（DR 参数范围正确，且**确实落到模型里**）、`test_bam_actuator.py`。

### 4.2 仿真物理验证

```bash
uv run render-rollout --policy ../microduck/policies/alpha_walking.onnx \
  --behavior run --out /tmp/motor-check
```

**看视频，不要只看数值。** 官方策略在新电机参数下应该还能走；摔倒或剧烈抖动说明
`kp_fw` 或摩擦参数偏差太大。注意这只是**敏感性测试**——跑不稳不代表 clone 不可行，
只说明需要基于 clone physics 重训。

### 4.3 从官方策略起步的正确方式

> 初版写 `train-walk --init-from ../microduck/policies/alpha_walking.onnx`——**这是错的**。

`train.py:140-144` 的实际期望是**一个 SB3 run 目录**（含 `model.zip` + `vecnormalize.pkl`）：

```python
prev = Path(args.init_from)
venv = VecNormalize.load(str(prev / "vecnormalize.pkl"), venv)
model = PPO.load(str(prev / "model"), ...)
```

从官方 ONNX 起步要用 `distill`：

```bash
uv run distill --teacher ../microduck/policies/alpha_walking.onnx --run-name my-walk
uv run export-walk runs/my-walk
# 之后可以基于 runs/my-walk 继续训练
```

### 4.4 重新训练

```bash
cd microduck_local
uv run train-walk --envs 32 --steps 3_000_000 --actuator bam --run-name my-motor-v1
uv run export-walk runs/my-motor-v1
uv run render-rollout --policy runs/my-motor-v1/policy.onnx --behavior run --out /tmp/rr-my-motor
```

---

## 五、sim2real 注意事项

- **不要直接把 XL330 训练的策略部署到新电机上**——力矩常数和摩擦特性不同会导致抖动或摔倒。
- BAM 参数误差会被 DR 的 `friction_scale_range` 部分吸收，但差异 > 30% 时 DR 覆盖不住。
- 新电机的**编码器延迟**与 XL330 不同时，要相应调整 `joint_vel` 的滞后步数（默认 1 步）
  与 BAM 的 `delay_min/max_lag`（XL330 是 3–6 步）。

> ⚠️ **`microduck_rl/scripts/infer_policy.py` 不是真机部署测试。**
> 它是**CPU MuJoCo 的部署演练（rehearsal）**——用来确认 ONNX 能加载、61/14 contract
> 正确、命令槽写法对。真机部署由 `microduck` repo 的 Rust runtime 完成
> （`robotd` + `duck-control` + `robotctl` + update system）。

上真机前应依次做：

1. `infer_policy.py` / `microduck_local render-rollout`：仿真回放
2. `robotd --fake`：runtime 软件路径（不需要硬件）
3. 单电机 / 单腿台架
4. 整机悬挂、低增益、固定站姿
5. 地面站立（`robotd init`，不跑 policy）
6. 低 `action_scale` 行走：0.2 → 0.4 → 0.6 → 0.9
7. 通过 `robotctl` 或 dev release 部署

---

## 六、无 GPU 折中方案（仅 Mac CPU）

没有 NVIDIA GPU 时，跳过 `microduck_rl`，完全在 `microduck_local` 上完成验证和训练，
直接导出 ONNX 部署真机。**策略质量可能低于 GPU 版，但足以验证新电机能不能走。**

> **实测性能（M5 Max）：** `microduck_local` ~19,000 steps/s；同机 `microduck_rl`
> 的 CPU 模式只有 ~950 steps/s（慢 20 倍，且官方命令需 `CUDA_VISIBLE_DEVICES=""`）。
> 换算：3.9 亿步的正式训练量在 `microduck_local` 上约 **5.8 h（过夜）**。
> 详见 `apple-silicon-throughput-benchmark.md`。

### 6.1 系统辨识

同 §2，但注册用 `json_path`（**不要**复制进 venv）：

```bash
cd microduck_local
uv pip install optuna wandb pypot dynamixel-sdk      # §2.0

python -m bam.feetech.record --logdir ./raw_logs --mass M --length L --motor sts3215 --id 1 --vin YOUR_V
python -m bam.process --raw ./raw_logs --logdir ./processed_logs --dt 0.005
python -m bam.fit --logdir ./processed_logs --actuator sts3215 --model m1 \
  --output params/hd1910/m1.json --trials 100000
```

### 6.2 让 `microduck_local` 加载新参数

参照 §3.2——**先泛化 servo control constants，再换 JSON**。只改
`_resolve_json_path(None, "xl330", "m6")`（`bam_actuator.py:306`）是不够的。

### 6.3 验证 + 训练 + 导出

```bash
uv run --with pytest pytest tests/
uv run render-rollout --policy ../microduck/policies/alpha_walking.onnx --behavior run --out /tmp/motor-check
uv run train-walk --envs 32 --steps 3_000_000 --actuator bam --run-name my-motor-v1
uv run export-walk runs/my-motor-v1
uv run render-rollout --policy runs/my-motor-v1/policy.onnx --behavior run --out /tmp/rr-my-motor
```

### 6.4 与 GPU 方案对比

| | 本地 CPU（`microduck_local`） | GPU（`microduck_rl`） |
|---|---|---|
| 吞吐（实测/口径） | ~19,000 steps/s | 云 NVIDIA ~73,000 steps/s **[由 README 反推]** |
| 3.9 亿步折算 | ~5.8 h | ~1.5 h |
| sim2real 保真度 | DR 缺 3 个 obs 级项（见下） | 完整 recipe |
| 适用 | 确认新电机能不能走（零成本 MVP） | 最终部署质量 |

> **保真度差距是可枚举的：** `microduck_local` 与 `microduck_rl` base velocity 任务的
> DR 差异只有 3 个 obs 级项——IMU 安装误差 ±6°、编码器 bias ±0.015 rad、IMU 延迟 0–1 步
> （`microduck_local/README.md:74-75` 自述「each a small change to `_get_obs`」）。
> **注意两个 harness 的 step 数不等价**（batch 差 12 倍），所以「跑同样步数」不保证同样质量。

---

## 七、快速决策树

```
新电机是否在 BAM 内置列表？（查 bam/params/ 的目录名，不是 docstring）
├── 是 → 训练侧设 motor_name + model（注意辨识侧键名可能不同）
└── 否 → 系统辨识 → 放进 repo → 用 json_path 注册

通信协议是否 Dynamixel 或 Feetech？
├── 是 → 用 BAM 录制脚本（但先修 feetech/record.py 的硬编码 /dev/ttyACM0）
└── 否 → 自己实现录制（参考 bam/logs.py 格式，输出 processed JSON）

有没有 NVIDIA GPU？
├── 有 → 用 microduck_rl 做最终训练（完整 DR，更好的 sim2real）
└── 没有 → microduck_local 过夜训练（~5.8 h），但先补齐那 3 个 obs 级 DR 项

改完之后（三条都要做）：
├── 1. pytest tests/ 全过
├── 2. render-rollout 看视频（官方策略应还能走）
└── 3. 从 ONNX 起步用 distill，不要用 --init-from <onnx>
```

---

## 附录：与初版的差异（共 12 条）

| # | 初版 | 修正 |
|---|---|---|
| 1 | 「外形尺寸一致 → MJCF 无需修改」 | 「可先不改碰撞几何，但必须复核质量/惯量/CoM/限位/齿隙」，并给出判断阈值（§1.4） |
| 2 | XL330 参考 3.7–6.0V、堵转 0.43 Nm | repo 实际 `vin=7.5V`、DR `6.5–8.2V`、限流 `1.75A`、`kt×1.75A≈0.6405 Nm`（§1.1） |
| 3 | 暗示 BAM 内置 Feetech 可直接用 | 明确两个命名空间（辨识 `sts3215` vs 训练目录名 `feetech_sts3215_7_4V`）、只有 `m1`、**HD-1910 不在库中**（§1.2/§1.3） |
| 4 | 把 JSON 复制进 `.venv/site-packages` | 放进 repo + 用 `json_path`（`bam/mjlab.py:112`），解释为什么复制会丢（§2.4） |
| 5 | 无 `bam.process` 步骤、无依赖说明 | 补 `bam.process --raw --logdir --dt`；补 `optuna`/`wandb`/`pypot`/`dynamixel-sdk`（实测报错信息）（§2.0/§2.2） |
| 6 | 「只传 `params=` 就安全」 | 「仅 `params=` 不够」，列出必须泛化的 6 类控制常数（含 `q_target_smooth`）（§3.2） |
| 7 | `train-walk --init-from <onnx>` | `--init-from` 期望 **run 目录**；从 ONNX 起步用 `distill`（§4.3） |
| 8 | 把 `infer_policy.py` 当真机部署测试 | 标为 **CPU MuJoCo 演练**；真机部署是 Rust runtime，并给出 7 步上机顺序（§5） |

**另外 4 条是本次验证时新发现的（初版与风险计划都未提及）：**

| # | 问题 | 证据 |
|---|---|---|
| 9 | `--actuator dynamixel` 会直接 `KeyError` | `bam/fit.py:86` 是 `actuators[args.actuator]()` 字典查找；键来自 `bam/actuators.py`（无 `dynamixel`） |
| 10 | `--output` 不是 record 脚本的参数；`--mass`/`--length`/`--motor` 是必填 | 实测 `bam/feetech/record.py` 与 `bam/dynamixel/record.py` 的 `argparse` |
| 11 | `bam.feetech.record` 忽略 `--port`/`--id`，硬编码 `/dev/ttyACM0` 与 motor 1 | `feetech/record.py:43-45`：`io = FeetechSTS3215IO("/dev/ttyACM0")`、`ids = [1]` |
| 12 | `bam/mjlab.py` 的 docstring 与实际参数目录不符（写 `erob80:50`，实为 `erob80_50`；未列 `feetech_sts3215_7_4V`） | 实测 `_resolve_json_path` 按目录名解析 |

> 本指南所有命令行参数、模块名与文件行号均在当前 checkout 上实测过；
> 与本文档配套的风险分析见 `microduck-clone-validation-risk-plan.md`，
> 吞吐与平台实测见 `apple-silicon-throughput-benchmark.md`。
