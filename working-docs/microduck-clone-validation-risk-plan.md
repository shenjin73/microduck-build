# Microduck 复制品：`custom-motor-guide.md` 校验、风险清单与实施计划

日期：2026-09-16  
范围：基于当前 `microduck-build` 工作区内的 `microduck-lab` submodule，对 `working-docs/custom-motor-guide.md` 做源码级校验，并给出复制 Microduck 时在电机、主板/连接板、仿真、训练、部署上的风险与路线图。

---

## 0. 结论摘要

如果目标是做一个 Microduck 复制品，并且电机可能换成飞特 `HD-1910-C001`，最大的风险不是“代码能不能改”，而是：

1. **执行器模型不匹配**：官方策略和 `microduck_rl` 的 sim2real 核心围绕 Dynamixel XL330 + BAM M6 参数建立。换电机会直接改变力矩、电流限制、速度、延迟、摩擦、齿隙、编码器读数和热保护。
2. **运行时硬件接口不兼容**：官方 `microduck` runtime 当前代码是 `DynamixelIo`，使用 `rustypot::servo::dynamixel::xl330::Xl330Controller`，读写 XL330 寄存器。Feetech HD 系列即使也是串口总线舵机，也大概率不能直接跑原 runtime。
3. **Apple Silicon 限制是真的，但要更精确地表述**：`microduck_rl` 官方训练路径依赖 MuJoCo Warp + CUDA，Mac/Apple Silicon 不能等价替代官方 NVIDIA/CUDA 大规模训练。Mac 可以跑 `microduck_local` CPU harness 做验证/小规模训练/可视化，也可以尝试把训练改成 CPU/MPS fallback；但这必须通过吞吐、reward、BAM parity、ONNX contract 和 HIL 验证，不能只以“代码能跑”为成功标准。最终高质量 sim2real 仍建议保留 NVIDIA GPU 或 HF Jobs 路线作为基准。
4. **机械“外形尺寸一致”不足以免改仿真**：即使外壳尺寸相同，质量、惯量、轴心/安装偏移、输出盘厚度、限位、齿隙、线缆/连接板重量都会影响 800g 小双足；需要实测并更新 MJCF/DR。
5. **`custom-motor-guide.md` 有多处需要修正**：尤其是 BAM motor_name、系统辨识命令、`microduck_local` 参数接入、`--init-from ONNX`、以及把 `infer_policy.py` 当作真机部署测试。

推荐路线：

- **P0：先冻结硬件接口**：优先选与 XL330 控制接口尽量接近的舵机；若使用 Feetech HD-1910，先把 bus protocol / register map / 50Hz 读写预算验证出来，再投入机械批量。
- **P1：Mac 上用 `microduck_local` 建立 clone 的仿真基线**：几何、质量、惯量、电机参数、延迟、噪声全部参数化。
- **P2：NVIDIA GPU/HF Jobs 上用 `microduck_rl` 做最终训练**：Mac 只作为开发与验证机。
- **P3：真机部署前建立 HIL/台架验证**：单电机 BAM 辨识 → 单腿/悬挂鸭 → 低增益站立 → 行走。

---

## 1. 我核对过的源码/文档依据

主要看了这些文件：

- `working-docs/custom-motor-guide.md`
- `microduck-lab/microduck_rl/README.md`
- `microduck-lab/microduck_rl/AGENTS.md`
- `microduck-lab/microduck_rl/pyproject.toml`
- `microduck-lab/microduck_rl/src/mjlab_microduck/robot/microduck_constants.py`
- `microduck-lab/microduck_rl/src/mjlab_microduck/actuator/friction_dr_bam.py`
- `microduck-lab/microduck_local/README.md`
- `microduck-lab/microduck_local/AGENTS.md`
- `microduck-lab/microduck_local/src/microduck_local/bam_actuator.py`
- `microduck-lab/microduck_local/src/microduck_local/walk_env.py`
- `microduck-lab/microduck_local/src/microduck_local/contract.py`
- `microduck-lab/microduck/README.md`
- `microduck-lab/microduck/duck-control/src/bus.rs`
- `microduck-lab/microduck/duck-control/src/model.rs`
- `microduck-lab/microduck/deploy/robotd.toml`
- `microduck-lab/microduck/docs/design/architecture.md`
- `microduck-lab/microduck/docs/design/robotd-design.md`
- `microduck-lab/microduck/docs/project/media-bringup.md`
- `microduck-lab/microduck/docs/project/npu-bringup.md`

另外实际运行了 `microduck-lab/scripts/setup.sh`，当前环境能装好 `microduck_rl`、`microduck`、policies，并且 smoke tests 通过：`55 passed`。

---

## 2. 对 `custom-motor-guide.md` 的逐条校验

### 2.1 正确或基本正确的部分

- `microduck_rl` 需要 CUDA GPU，Apple Silicon 不能直接跑正式 MuJoCo Warp 训练：**正确**。
  - `microduck_rl/README.md` 明确写了 Requires a CUDA GPU。
  - `microduck_rl/pyproject.toml` 依赖 `warp-lang==1.12.0`，并专门为 linux-aarch64 CUDA wheel 写了 torch source 规则。
- `microduck_local` 是 Mac/CPU 本地 harness：**正确**。
  - `microduck_local/README.md` 明确说它是 Apple Silicon 上的 CPU-MuJoCo PPO 原型环境。
- 需要保持 61D observation / 14 action contract：**正确且非常重要**。
  - `microduck_local/contract.py`：`OBS_DIM = 61`, `NUM_JOINTS = 14`。
  - 真机 runtime 是 15 个舵机，但 mouth 不在 policy action 里：`microduck/duck-control/src/model.rs` 中 `NUM_JOINTS=15`, `MOUTH_INDEX=9`。
- BAM 是 sim2real 的核心：**正确**。
  - `microduck_rl/README.md` 和 `bam_actuator.py` 都强调：XL330 的 voltage control、back-EMF、摩擦、电压 sag、bus delay 是关键。

### 2.2 需要修正/补充的部分

#### A. “外形尺寸与 XL330 一致，MJCF 无需修改”过于乐观

即使外形相同，仍然可能需要改 MJCF：

- 每个 servo 的质量与惯量；
- 输出轴位置、horn 厚度、安装偏移；
- 可达角度/机械限位；
- 线缆、连接板、主板、电池位置引起的 CoM 改变；
- 齿隙/backlash；
- 脚底材料/摩擦。

`microduck_local/walk_env.py` 里虽然有 DR：

```python
MASS_SCALE_RANGE = (0.95, 1.05)
ARMATURE_SCALE_RANGE = (0.9, 1.1)
TRUNK_COM_STAGES = ((0, 0.003), ..., (36_000, 0.015))
HEAD_COM_STAGES = ((0, 0.003), ..., (24_000, 0.010))
```

但这只能覆盖小偏差。如果 clone 的电机/连接板/电池导致 CoM 超过厘米级变化，不能靠默认 DR 消化。

#### B. XL330 参考电压/力矩描述不精确

文档中写：

> 额定电压 3.7–6.0V；堵转力矩 ~0.43 Nm

但当前代码真实训练/部署假设更接近：

- BAM nominal `vin=7.5V`；
- voltage DR：`vin_range=(6.5, 8.2)`；
- runtime 电池映射：`BATTERY_EMPTY_V=6.6`, `BATTERY_FULL_V=8.2`；
- BAM XL330 current limit：`1.75A`；
- `XL330_MAX_TORQUE = kt * max_current = 0.3660 * 1.75 ≈ 0.640 Nm`；
- XML small-signal force ceiling约 `0.96 Nm`，但注释说明这是 voltage ceiling，不是 firmware current limit 后的真实可持续能力。

所以选型不能只看 datasheet stall torque；要对齐：供电电压、固件电流限制、速度常数、闭环 P 增益、热保护。

#### C. BAM 已内置 Feetech，但不是“HD-1910 可直接用”

当前 BAM package 中实际存在：

- actuator key：`sts3215`
- 参数目录：`params/feetech_sts3215_7_4V/m1.json`

没有看到 `HD-1910-C001` 的参数。也就是说：

- 如果 HD-1910 与 STS3215 控制/电机/齿轮箱不同，不能直接复用 STS3215 参数。
- 甚至 STS3215 也只有 `m1` 参数，不是 XL330 那样的 `m6` friction model。
- `BamActuatorCfg` 支持 custom `json_path`，比把 JSON 复制进 site-packages 更正确。

#### D. `microduck_local` 里“只传 params 就安全”不完整

`microduck_local/src/microduck_local/bam_actuator.py` 的类名和默认常量是 `BamXL330Actuator`。它支持：

```python
params: dict[str, float] | None = None
kp_fw: float = DEFAULT_KP_FW
max_current: float | None = XL330_MAX_CURRENT
```

但它仍然硬编码了 XL330 相关控制常数：

```python
XL330_ENCODER_COUNTS_PER_REV = 4096
XL330_KP_DIVISOR = 256
XL330_PWM_LIMIT = 885
XL330_ERROR_GAIN = ...
XL330_MAX_PWM = 1.0
XL330_MAX_CURRENT = 1.75
```

所以对 Feetech/HD-1910 来说，**只传 `params=` 还不够**。你至少要显式参数化：

- `error_gain`
- `max_pwm`
- `max_current` 或无 current limit
- firmware kp 语义
- 速度/位置单位换算
- command delay
- internal velocity smoothing/velocity limit，如 STS3215 BAM actuator 中有 `q_target_smooth`

否则 simulation 看似换了 kt/R/friction，实际控制律仍是 XL330。

#### E. `--init-from ../microduck/policies/alpha_walking.onnx` 是错的

`microduck_local/train.py` 中：

```python
prev = Path(args.init_from)
venv = VecNormalize.load(str(prev / "vecnormalize.pkl"), venv)
model = PPO.load(str(prev / "model"), ...)
```

所以 `--init-from` 期望的是一个 SB3 run directory，里面有 `model.zip` 和 `vecnormalize.pkl`，不是 `.onnx`。

如果要从官方 ONNX 起步，文档里更靠谱的是：

```bash
uv run distill --teacher ../microduck/policies/alpha_walking.onnx --run-name my-walk
uv run export-walk runs/my-walk
```

然后再基于这个 run dir 继续训练。

#### F. `infer_policy.py` 不是“真机部署测试”

`microduck_rl/scripts/infer_policy.py` 是 CPU MuJoCo deployment rehearsal，不是真机运行。真机部署由 `microduck` repo 的 Rust runtime：`robotd` + `duck-control` + `robotctl` + update system 完成。

真正上真机前，应做：

- `infer_policy.py` / `microduck_local render-rollout`：仿真回放；
- `robotd --fake`：runtime 软件路径；
- 单电机/单腿台架；
- 实机低增益/悬挂/支撑测试；
- 再通过 `robotctl` 或 dev release 部署。

#### G. BAM record/fit 命令还缺依赖和处理步骤

当前 `microduck_rl` 的 venv 中导入 `bam.fit` 会因为缺 `optuna` 报错；导入 `bam.feetech.record` 会因缺 `pypot` 报错；导入 `bam.dynamixel.record` 会因缺 `dynamixel_sdk` 报错。

此外 BAM `Logs` 读取的是 processed JSON，`bam/process.py` 会把 raw log 重采样到固定 `dt`。所以更完整流程应包含：

```bash
# raw logs -> processed logs
python -m bam.process --raw ./raw_logs --logdir ./processed_logs --dt 0.005

# fit on processed logs
python -m bam.fit --logdir ./processed_logs --actuator ... --model ... --output ...
```

Feetech record 脚本源码还硬编码了 `/dev/ttyACM0` 和 ID `1`，没有正确使用 `--port` / `--id` 参数：需要先修或自己写采集脚本。

---

## 3. Microduck clone 的关键硬件约束

### 3.1 原始机器人硬件接口画像

从当前代码看，官方 runtime 假设：

- 计算板：Rockchip RK3566/Radxa Zero 3W 类 Linux 板；
- 控制回路：`robotd` 50 Hz；
- 总线：Dynamixel Protocol 2.0，`/dev/ttyS2`，`1_000_000` baud；
- 设备数量：15 个舵机 + 一个 `imu_to_dxl` board；
- policy action：14 维，不包括 mouth；
- IMU：通过同一 Dynamixel bus 读，ID `200`；
- 相机：CSI camera，由 `mediad` 管；
- ToF：独立 `tofd`，I2C；
- 推理：ONNX Runtime，runtime 要求 `obs[1,61] -> actions[1,14]`。

关键代码证据：

```rust
// microduck/duck-control/src/model.rs
pub const NUM_JOINTS: usize = 15;
pub const MOUTH_INDEX: usize = 9;
pub const IMU_DXL_ID: u8 = 200;
pub const BAUD_RATE: u32 = 1_000_000;
```

```rust
// microduck/duck-control/src/bus.rs
use rustypot::servo::dynamixel::xl330::Xl330Controller;
const READ_ADDR: u8 = 124; // present_pwm/current/velocity/position
const READ_LEN: u8 = 12;
```

### 3.2 如果换 Feetech HD-1910-C001，最先验证什么

用户提供了三张 HD-1910-C001 资料图，能确认一部分机械/电气规格，但还不能替代完整通信协议手册。已知信息如下：

| 项目 | HD-1910-C001 图中信息 | 工程含义 |
|---|---|---|
| 产品型号 | `HD-1910-C001` | 需要在 BOM/CAD/MJCF 中固定具体 suffix，避免买到同外壳不同固件版本 |
| 通信 | TTL 串行总线，三针接口 | 不是 Dynamixel Protocol 2.0 的证据；必须拿寄存器表/协议或实测 |
| 电压范围 | `4V–8.4V` | 覆盖 Microduck 2S 电池区间；但图中性能只标到 4.8V/6V，7.4–8.4V 仍需实测 |
| 堵转扭力 | `9kg·cm @4.8V`, `12kg·cm @6V` | 约 `0.883Nm @4.8V`, `1.177Nm @6V`；峰值看起来高于 XL330，但不能等同可持续 torque |
| 空载速度 | `0.139s/60° @4.8V`, `0.111s/60° @6V` | 约 `72rpm / 7.54rad/s` 和 `90rpm / 9.43rad/s`；速度足够，但 load 下响应要测 |
| 空载电流 | `<200mA @4.8V`, `240mA @6V` | 仅说明 no-load 摩擦/电子功耗；不能推断行走电流 |
| 堵转电流 | `1.2A @4.8V`, `1.5A @6V` | 与官方 XL330 BAM 使用的 `1.75A` current limit 同量级；但保护逻辑/限流曲线未知 |
| 静态电流 | `20mA @4.8V/6V` | 待机功耗较低，对 15 舵机总待机约 300mA 级别 |
| 额定负载 | `2.2kg·cm @4.8V`, `3.0kg·cm @6V` | 约 `0.216Nm` 和 `0.294Nm`；连续负载能力可能明显低于 peak，行走热风险仍需台架验证 |
| 额定电流 | `500mA @4.8V`, `690mA @6V` | 15 舵机额定总电流可到 10A 级，连接板/电池/线径要按峰值更高设计 |
| 外形尺寸 | `34×20×23mm`，图中另有 34/30/20.16/23.29 等标注 | 与小型机器人舵机尺寸接近；仍要确认输出轴中心、horn 厚度、安装孔和关节 frame |
| 重量 | `21±2g` | 与原 servo 质量级别接近；但 ±2g×15 已是 ±30g，需要计入质量/CoM DR |
| 外壳材质 | `PA + Fiber` | 塑胶增强外壳；散热、刚性、螺丝柱强度要验证 |
| 结构 | 双轴结构、金属齿轮、多孔安装 | 机械上适合鸭子关节，但 backlash 和轴向间隙必须测 |

从这些图看，HD-1910-C001 **电压范围、尺寸、重量、峰值扭矩、速度都具备候选资格**，而且 `4–8.4V` 与 2S 电池兼容，这是好消息。但仍不能直接判定它能替代 XL330，因为 Microduck 的关键不是 datasheet peak torque，而是 50Hz 闭环下的：协议、寄存器、延迟、电流/电压/温度读数、P 增益语义、过载保护、backlash、热稳定性和 BAM 可辨识性。

因此以下仍是必须向供应商/实物验证的表：

| 项目 | 为什么重要 | 通过标准 |
|---|---|---|
| 协议 | 原 runtime 是 Dynamixel P2 + XL330 controller | 能否用现有 `rustypot` 直接读写；不能则写 `FeetechIo` |
| 半双工 UART 电平 | 连接板/主板硬件设计核心 | 与主板 IO 电平、方向控制、保护兼容 |
| 位置单位与零点 | 直接影响 obs joint_pos 和 targets | 每个关节可校准到 Microduck `DEFAULT_POSITION` |
| 速度单位 | obs joint_vel 进入 policy | 换算误差 < 5–10%，或加入 DR/重训 |
| P/I/D 寄存器语义 | BAM 控制律依赖 firmware kp | 可写、可读、可复现；I/D 可置 0 或建模 |
| 电流/扭矩读数 | safety/热保护/辨识需要 | 可读 present current/load；单位可标定 |
| 电压读数 | battery/voltage_adapt | 可读或另加 ADC/fuel gauge |
| 返回延迟 | 50 Hz bus budget | 15 舵机 + IMU 一次读写稳定 < 20 ms |
| 温度读数/保护 | 小双足很容易热 | runtime 能读 hottest motor 或另加热策略 |
| backlash | 小舵机齿隙会破坏 sim2real | 测量 deadband；必要时训练 Backlash variant |

---

## 4. 主要风险清单与解决方案

### R1. Apple Silicon 训练可行性：能移植，但不能默认等价于 CUDA 正式训练

**风险级别：高；部分可绕过。**

`microduck_rl` 官方路径用 MuJoCo Warp + PyTorch CUDA。Mac 上没有 NVIDIA CUDA，因此不能把 Apple GPU/MPS 直接视为等价替代。但这不代表 Apple Silicon 完全不能训练：可以走 `microduck_local` CPU/MPS 路线，也可以尝试给 `microduck_rl` 做 CPU/MPS fallback。关键区别是：**能跑起来 ≠ 达到官方 CUDA 路线的样本吞吐、物理并行度和 sim2real 可信度。**

如果某个 patch 只是把：

```python
device = "cuda"
```

改成：

```python
device = "mps"
```

那通常只解决了 PyTorch policy update 的设备问题，没有解决大规模 rollout/MuJoCo Warp/CUDA backend 的问题。Apple MPS 可以帮助神经网络前后向，但不等价于 CUDA/Warp 上的大量并行物理仿真。

**Apple Silicon 上可行的三条路线：**

| 路线 | Apple Silicon 可行性 | 适合用途 | 主要风险 |
|---|---:|---|---|
| `microduck_local` CPU/MPS | 高 | smoke、小规模训练、actuator 参数验证、ONNX export 检查 | 与官方 `microduck_rl` 物理/训练栈不完全等价 |
| `microduck_rl` CPU/MPS fallback | 中低 | 实验、降低 env 数的小规模训练 | Warp/MJLab/CUDA 依赖、吞吐不足、可能偷偷退化物理模型 |
| 官方 `microduck_rl` CUDA/HF Jobs | 高，需云 GPU | 最终训练基准 | 成本、环境配置 |
| MJX/JAX Metal 或自研 vectorized backend | 理论可行 | 长期 Apple-native 训练 | 工程量大，sim2real 需要重新验证 |

**Mac 上推荐先跑的路线：**

```bash
cd microduck-lab/microduck_local

uv run train-walk \
  --envs 16 \
  --steps 1_000_000 \
  --device cpu \
  --actuator bam \
  --run-name mac-hd1910-smoke-v1
```

可以试 MPS，但不要假设更快：

```bash
uv run train-walk \
  --envs 16 \
  --steps 1_000_000 \
  --device mps \
  --actuator bam \
  --run-name mac-hd1910-mps-v1
```

`microduck_local/train.py` 自身注释也提醒：这类小 MLP policy 上，CPU 经常比 MPS dispatch overhead 更划算。

**如果要验证 DeepSeek/其他工具改出的 `microduck_rl` Apple 版，必须跑这些检查：**

```bash
cd microduck-lab/microduck_rl

# 1. 检查 torch/MPS 可用性
uv run python -c "import torch; print('mps=', torch.backends.mps.is_available())"

# 2. 最小 smoke train：能否真正跑 rollout + PPO update
uv run train Mjlab-Velocity-Flat-MicroDuck \
  --env.scene.num-envs 16 \
  --agent.max_iterations 5

# 3. 小规模吞吐测试
uv run train Mjlab-Velocity-Flat-MicroDuck \
  --env.scene.num-envs 64 \
  --agent.max_iterations 50
```

验证标准：

- 训练不是只跑神经网络 update，而是真的在 step environment；
- 没有偷偷把 BAM actuator 退回 XML actuator；
- 没有关闭关键 domain randomization；
- observation/action contract 仍是 `61 -> 14`；
- reward 曲线能正常增长；
- env steps/sec 足够支撑百万/千万级 timestep；
- ONNX export 成功，并能被 `microduck_local` 和 `robotd` contract 接收；
- 与同配置 CUDA 小规模 run 的 rollout、reward 和动作分布接近。

**保守解决方案：**

1. Mac 上做：
   - 源码开发；
   - `microduck_local` CPU/MPS 仿真；
   - viewer；
   - runtime Rust 单元测试；
   - 小规模 smoke training；
   - Apple fallback patch 的吞吐/正确性验证。
2. 正式基准训练仍保留：
   - Hugging Face Jobs：`uv run train ... --hf-jobs`；
   - Lambda/Vast/AWS/GCP 任一 NVIDIA GPU；
   - 如果是 linux-aarch64 NVIDIA，保留 `pyproject.toml` 里 torch CUDA wheel routing。
3. 每个长训练前必须先跑小 smoke：

```bash
cd microduck-lab/microduck_rl
uv run train Mjlab-Velocity-Flat-MicroDuck \
  --env.scene.num-envs 64 \
  --agent.max_iterations 5
```

NVIDIA/HF Jobs 正式训练示例：

```bash
cd microduck-lab/microduck_rl
uv run train Mjlab-Velocity-Flat-MicroDuck \
  --env.scene.num-envs 4096 \
  --agent.max_iterations 4000 \
  --hf-jobs \
  --run-name clone-hd1910-walk-v1
```

### R2. HD-1910 没有可靠 BAM M6 参数

**风险级别：高。**

XL330 的 BAM 参数在 repo 中很完整，且 `microduck_local` CPU port 直接编码 XL330 逻辑。HD-1910 不在当前 BAM 参数库中。

**解决方案：**

- 不要先假设“9kg.cm 比 XL330 强，所以能走”。腿部行为依赖速度、响应延迟、摩擦和电流限制，不只是峰值扭矩。
- 做单电机摆杆辨识，输出 BAM JSON。
- 最小测试矩阵：
  - P gain：低/中/高至少 3 档；
  - 电压：满电、中电、低电；
  - 轨迹：lift/drop、sine、step、hold under load；
  - 温升：持续 3–5 分钟。

更靠谱的 custom JSON 用法：

```python
# microduck_rl/src/mjlab_microduck/robot/microduck_constants.py
from pathlib import Path

_CUSTOM_MOTOR_JSON = Path(__file__).resolve().parents[3] / "params" / "hd1910" / "m6.json"

_BAM_ACTUATOR_KWARGS = dict(
    json_path=str(_CUSTOM_MOTOR_JSON),
    target_names_expr=(r"^(?!passive_).*",),
    kp_fw=YOUR_MEASURED_KP,
    vin_range=(6.5, 8.2),
    vin_drop_gain_range=(0.0, 0.2),
    vin_min=6.0,
    delay_min_lag=MEASURED_MIN_LAG,
    delay_max_lag=MEASURED_MAX_LAG,
)
```

不要把参数复制到 `.venv/site-packages/bam/params/...` 作为长期方案；HF Jobs / fresh uv sync 会丢失，且不可复现。

### R3. `microduck_local` 的 BAM actuator 需要泛化

**风险级别：高。**

现在的 `BamXL330Actuator` 可传 `params`，但控制律仍硬编码 XL330：encoder counts、P divisor、PWM limit、current limit 等。

**建议改法：**新增一个 `BamServoSpec`，不要把 Feetech 伪装成 XL330。

代码草案：

```python
# microduck_local/src/microduck_local/bam_actuator.py
from dataclasses import dataclass

@dataclass(frozen=True)
class BamServoSpec:
    error_gain: float
    max_pwm: float = 1.0
    max_current: float | None = None
    nominal_vin: float = 7.5
    q_target_rate_limit: float | None = None  # rad/s, Feetech STS3215-style if needed

XL330_SPEC = BamServoSpec(
    error_gain=XL330_ERROR_GAIN,
    max_pwm=XL330_MAX_PWM,
    max_current=XL330_MAX_CURRENT,
    nominal_vin=XL330_NOMINAL_VIN,
)
```

然后在 constructor 中加入：

```python
class BamXL330Actuator:
    def __init__(..., servo_spec: BamServoSpec = XL330_SPEC, ...):
        self.servo_spec = servo_spec
        self.error_gain = servo_spec.error_gain
        self.max_pwm = servo_spec.max_pwm
        self.max_current = servo_spec.max_current if max_current is None else max_current
```

Feetech STS3215 在 BAM 源码里的关键差异：

```python
# bam/feetech/actuator.py
kp=32
error_gain=0.166
max_pwm=0.97
q_target_smooth = clamp(q_target, prev ± max_velocity * dt)
```

所以 HD-1910 至少要确认是否也有类似内部目标速度限制。如果有，`microduck_local` 也要模拟这个 `q_target_smooth`。

### R4. Runtime 只支持 XL330/Dynamixel 寄存器

**风险级别：高。**

当前 `duck-control/src/bus.rs` 写死了 `Xl330Controller`、Dynamixel IDs、XL330 register semantics。Feetech 需要验证是否能被 `rustypot` 支持，或新写 IO。

建议抽象：

```rust
// 保留 RobotIo trait，不改 control loop
pub enum BusKind {
    DynamixelXl330,
    FeetechHd1910,
}

pub fn open_robot_io(kind: BusKind, port: &str) -> Result<Box<dyn RobotIo + Send>> {
    match kind {
        BusKind::DynamixelXl330 => Ok(Box::new(DynamixelIo::open(port)?)),
        BusKind::FeetechHd1910 => Ok(Box::new(FeetechIo::open(port)?)),
    }
}
```

`FeetechIo` 需要实现同一个 trait：

```rust
impl RobotIo for FeetechIo {
    fn read(&mut self) -> Result<Sensors> {
        // 1. sync/bulk read positions, velocities, currents
        // 2. read or merge IMU sample
        // 3. convert to radians / rad/s / mA
        todo!()
    }

    fn write(&mut self, targets: &JointTargets) -> Result<()> {
        // convert radians to Feetech position units and sync write
        todo!()
    }

    fn set_gain(&mut self, kp: u16) -> Result<()> {
        // map robotd gain to Feetech P/I/D registers
        todo!()
    }

    fn set_torque(&mut self, on: bool) -> Result<()> {
        todo!()
    }

    fn slow_sensors(&mut self) -> Result<SlowSensors> {
        todo!()
    }
}
```

如果 Feetech 不能把 IMU board 放进同一 Dynamixel transaction，则 `Sensors` 仍可保持不变，但 bus layer 要组合两个来源，并证明 50Hz jitter 可接受。

### R5. 连接板/主板对控制回路影响很大

**风险级别：高。**

Microduck 不是只跑 neural network。主板/连接板必须保障：

- 15 个舵机供电瞬态；
- 半双工 UART 1Mbps 稳定；
- IMU 更新时间和坐标系；
- CSI camera / ISP / encoder；
- ToF I2C；
- ONNX 推理不抢占 50Hz control loop；
- 热管理。

原 runtime 对 Radxa Zero 3W / RK3566 做了大量 board-specific 工作：UART overlay、NPU overlay、Rockchip MPP、GStreamer plugin、ONNX Runtime、systemd units。

如果换主板，建议按风险从低到高：

1. **最小改动**：继续用 Radxa Zero 3W 或同 RK3566/RK3568 生态板。
2. **中等风险**：换 Linux ARM 板，但保留 UART/CSI/NPU/VPU 能力；需要重做 deploy scripts。
3. **高风险**：ESP32/MCU + 外部 AI 板分离；需要重写 runtime 架构，不建议第一版。

### R6. 视觉/ToF 与自主行为是独立大风险

**风险级别：中高。**

当前机器人 runtime 的 `mediad`、`tofd`、NPU、camera calibration 都有不少 board-specific 陷阱。`docs/camera-hardware.md` 显示，仅 FOV/分辨率/畸变就能显著影响 tidy/soccer 行为。

如果第一版目标是“能走、能站、能被遥控”，建议：

- camera/ToF 先做机械预留和软件 stub；
- 不把 autonomous soccer/tidy 作为第一版交付目标；
- 后续再上 640px detector + lens calibration。

### R7. ONNX / observation contract 被破坏

**风险级别：高。**

训练、viewer、runtime 都围绕同一个 contract：

```text
obs[1,61] -> action[1,14]
[gyro(3), projected_gravity(3), joint_pos_rel(14), joint_vel(14), last_action(14), command(13)]
```

任何新增硬件都不要随便改 policy 输入维度。应该先保持 61/14 不变，额外传感器作为高级 brain 或 runtime feature，而不是塞进 locomotion policy。

### R8. 官方策略直接上 clone 可能会摔

**风险级别：高。**

官方 `alpha_walking.onnx` 是在 XL330 + 原机械参数上训练的。clone 的电机、质量、关节摩擦、脚底摩擦、电池 sag 变了，直接上机风险大。

解决：

1. 在 simulation 中重建 clone 参数；
2. 跑官方 policy under clone physics，作为敏感性测试；
3. 若不稳定，不要调 runtime 硬凑，应重训或 fine-tune；
4. 真机上先低 action_scale / 低 gain / 悬挂测试。

---

## 5. 推荐实施计划（按时间节点）

下面按 10 周规划。若你已有 CAD、电机样品、主板，时间可压缩；若 HD-1910 datasheet/协议不清楚，P0 会拉长。

### Week 0：定义目标与冻结第一版边界

**目标：** 明确第一版只追求什么。

建议第一版 MVP：

- 能站立；
- 能被 gamepad/命令控制前后左右；
- 能摔倒后低风险恢复或至少 limp；
- 能 OTA/ssh 部署新 policy；
- 不强求 soccer/tidy/autonomous vision。

交付物：

- `working-docs/hardware-assumptions.md`
- `working-docs/hd1910-datasheet-notes.md`
- 初版 BOM：电机、主板、电池、连接板、IMU、相机/ToF 是否保留。

必须回答的问题：

1. HD-1910-C001 的通信协议、波特率、寄存器表是否确定？
2. 是否能读 position/velocity/current/voltage/temp？
3. 供电是 2S Li-ion 6.6–8.4V 还是别的？
4. 是否保持 15 个舵机，其中 mouth 不进 policy？

### Week 1：硬件接口 spike：单电机 + 总线

**目标：** 证明主板能稳定控制一个 HD-1910。

任务：

- 建一个单电机测试架；
- 写最小 Python/Rust 读写脚本；
- 读 position/velocity/current/voltage/temp；
- 写 goal position；
- 改 P/I/D；
- 连续运行 5 分钟记录错误率和温升。

最小 Python log 格式建议：

```python
import json, time, math

entries = []
t0 = time.time()
while time.time() - t0 < 180:
    now = time.time() - t0
    goal = 0.5 * math.sin(2 * math.pi * 0.5 * now)
    servo.write_goal_position_rad(1, goal)
    s = servo.read_state(1)
    entries.append({
        "timestamp": now,
        "goal_position": goal,
        "position": s.position_rad,
        "speed": s.velocity_rad_s,
        "load": s.load_or_current,
        "input_volts": s.volts,
        "temp": s.temp_c,
        "torque_enable": True,
    })
    time.sleep(0.005)

json.dump({
    "mass": 0.0,
    "arm_mass": 0.0,
    "length": 0.0,
    "kp": 32,
    "vin": 7.4,
    "motor": "hd1910",
    "trajectory": "sine",
    "entries": entries,
}, open("raw_hd1910/sine.json", "w"))
```

通过标准：

- 单电机 100–200 Hz 采样可稳定；
- 15 电机模拟读写预算估算可满足 50 Hz；
- 没有大量 timeout；
- 单舵机温升可控。

### Week 2：机械参数测量与 MJCF 差异表

**目标：** 确定是否能复用原 Microduck MJCF。

任务：

- 称重：每个 servo、头部、躯干、电池、连接板；
- 测 CoM：trunk/head assembly 尤其重要；
- 测关节限位和零点；
- 测脚底摩擦；
- 测齿隙；
- 记录线缆走线造成的弹性/卡滞。

建议文件：

```text
working-docs/clone-mjcf-delta.csv
part, original_mass_g, clone_mass_g, delta_g, com_delta_mm, action
left_hip_servo, ..., ..., ..., ..., update inertial
battery, ..., ..., ..., ..., update trunk mass/com
```

判断规则：

- 总质量差 > 5%：必须更新 MJCF；
- trunk/head CoM 差 > 5–10 mm：必须更新 MJCF/DR；
- servo inertia 或 gear ratio 明显不同：必须改 actuator model；
- 关节限位不同：必须更新 XML + runtime clamp。

### Week 3：BAM 辨识与 actuator model 接入

**目标：** 得到可复现的 HD-1910 actuator JSON，并同时接入 `microduck_rl` 和 `microduck_local`。

流程：

```bash
# 安装 BAM fitting 额外依赖；当前 pyproject 没带这些
cd microduck-lab/microduck_rl
uv pip install optuna wandb pypot dynamixel-sdk

# raw -> processed
uv run python -m bam.process --raw ./raw_hd1910 --logdir ./processed_hd1910 --dt 0.005

# fit；actuator 名称要与 BAM actuators.py 支持的 key 一致
uv run python -m bam.fit \
  --logdir ./processed_hd1910 \
  --actuator sts3215 \
  --model m1 \
  --output params/hd1910/m1.json \
  --trials 100000
```

如果要 M6，不是所有 actuator 初值/模型都天然适配 Feetech，需要确认 BAM `model=m6` + `actuator=sts3215` 是否收敛且物理合理。

`microduck_rl` 推荐改成 `json_path`：

```python
# microduck_rl/src/mjlab_microduck/robot/microduck_constants.py
_BAM_ACTUATOR_KWARGS = dict(
    json_path="params/hd1910/m1.json",
    target_names_expr=(r"^(?!passive_).*",),
    kp_fw=32.0,  # 示例；用实测/固件值
    vin_range=(6.8, 8.4),
    vin_drop_gain_range=(0.0, 0.2),
    vin_min=6.0,
    delay_min_lag=MEASURED_MIN_LAG,
    delay_max_lag=MEASURED_MAX_LAG,
)
```

`microduck_local` 则需要先泛化 `BamXL330Actuator`，不要只替换 JSON。

### Week 4：Mac 本地仿真 smoke + viewer

**目标：** 在 Mac 上快速发现明显物理错误。

命令：

```bash
cd microduck-lab/microduck_local
uv run --with pytest pytest tests/test_env_contract.py tests/test_walk_env_physics.py tests/test_bam_actuator.py -q

# 官方策略在 clone physics 下回放，只作为敏感性测试
uv run render-rollout \
  --policy ../microduck/policies/alpha_walking.onnx \
  --behavior run \
  --out /tmp/clone-alpha-check

# viewer + lab
uv run duck-lab --world living-room --fresh ../microduck/policies/alpha_walking.onnx
cd ../duck-viewer && npm run dev
```

注意：官方 policy 跑不稳不代表 clone 不可行，只说明需要基于 clone physics 训练。

### Week 5：CPU 小规模训练，验证方向

**目标：** 不花 GPU 钱，先确认 reward/physics 没明显问题。

```bash
cd microduck-lab/microduck_local
uv run train-walk \
  --envs 16 \
  --steps 1_000_000 \
  --actuator bam \
  --run-name hd1910-smoke-v1

uv run export-walk runs/hd1910-smoke-v1
uv run render-rollout --policy runs/hd1910-smoke-v1/policy.onnx --behavior run --out /tmp/hd1910-smoke
```

如果想从官方 walking policy 获得 imitation 起点，用：

```bash
uv run distill \
  --teacher ../microduck/policies/alpha_walking.onnx \
  --run-name hd1910-distill-v1

uv run export-walk runs/hd1910-distill-v1
```

### Week 6：runtime 硬件抽象与 fake/bench 测试

**目标：** `microduck` runtime 支持你的电机/板子，同时不破坏 control loop。

任务：

- 新增 `FeetechIo` 或 `Hd1910Io`；
- 保持 `RobotIo` trait 不变；
- `robotd --fake` 保持可用；
- 加 bus conversion 单元测试；
- 加 15 电机 bus latency benchmark；
- 增加 `/etc/robot/robotd.toml` 配置项，如：

```toml
[bus]
kind = "feetech-hd1910"
port = "/dev/ttyS2"
baud = 1000000
```

### Week 7：真机 HIL 分阶段验证

**目标：** 不让第一只实体鸭在全策略下直接摔。

顺序：

1. 单电机台架：位置环、温度、电流、过载；
2. 单腿：慢速 pose interpolation；
3. 整机悬挂：低 gain，固定站姿；
4. 地面站立：`robotd init`，不跑 policy；
5. 低 action_scale 行走：0.2 → 0.4 → 0.6 → 0.9；
6. 开启 fall limp；
7. 记录 motor current / temp / loop hz / bus errors。

runtime 参数示例：

```toml
[policy]
action_scale = 0.3
standing_action_scale = 0.5
gain = 80
head_lowpass = 0.5
legs_lowpass = 0.7
voltage_adapt = true
nominal_voltage = 7.4

[safety]
limp_fall = true
gain_limp = 30
```

### Week 8–9：正式训练阶段：NVIDIA 基准路线 + Apple Silicon fallback 验证

**目标：** 用 clone physics 训练可部署 gait。推荐仍把 NVIDIA/CUDA 作为最终基准路线，同时允许 Apple Silicon 作为 fallback/实验路线，但必须通过验证后才能替代。

#### 路线 A：NVIDIA GPU / HF Jobs 基准训练

```bash
cd microduck-lab/microduck_rl
uv run train Mjlab-Velocity-Flat-MicroDuck \
  --env.scene.num-envs 4096 \
  --agent.max_iterations 4000 \
  --hf-jobs \
  --run-name hd1910-walk-v1
```

#### 路线 B：Apple Silicon fallback 训练验证

如果已经把 `microduck_rl` 改到了 CPU/MPS backend，先不要直接跑大训练，按顺序验证：

```bash
cd microduck-lab/microduck_rl
uv run python -c "import torch; print('mps=', torch.backends.mps.is_available())"

uv run train Mjlab-Velocity-Flat-MicroDuck \
  --env.scene.num-envs 16 \
  --agent.max_iterations 5

uv run train Mjlab-Velocity-Flat-MicroDuck \
  --env.scene.num-envs 64 \
  --agent.max_iterations 50
```

如果上面都通过，再尝试较长 run，例如：

```bash
uv run train Mjlab-Velocity-Flat-MicroDuck \
  --env.scene.num-envs 64 \
  --agent.max_iterations 1000 \
  --run-name hd1910-apple-fallback-v1
```

Apple fallback 合格标准：

- 没有绕开或弱化 BAM actuator；
- 没有关闭关键 domain randomization；
- rollout 确实在 step environment；
- 61D observation / 14 action contract 不变；
- reward 曲线正常增长；
- env steps/sec 可支撑目标训练量；
- 导出的 ONNX 在 `microduck_local` viewer 和 runtime contract 下可用；
- 与 CUDA 小规模 baseline 行为接近。

#### 导出

```bash
uv run scripts/export.py Mjlab-Velocity-Flat-MicroDuck \
  --wandb-run-path <entity/project/run_id>
```

注意：必须用 `scripts/export.py`，因为它会 bake observation normalizer。不要手工把 checkpoint 转 ONNX。对于 Apple fallback run，也要确认 export 后的 ONNX 与官方 `robotd` contract 兼容。

### Week 10：部署与回归

**目标：** 形成可重复发布流程。

任务：

- 把 ONNX 放入 release 或 model channel；
- `robotctl update apply` 部署；
- `robotctl health` 检查；
- `robotctl monitor` 观察 5–10 分钟；
- 记录每个版本的硬件参数、policy hash、BAM JSON hash、runtime config。

上线 checklist：

```text
[ ] 61D/14 action shape checked
[ ] DEFAULT_POSITION matches training HOME_FRAME
[ ] joint order matches JOINT_NAMES
[ ] motor bus 50Hz stable
[ ] voltage/temp/current readable
[ ] action_scale/gain conservative
[ ] fall limp enabled and tested
[ ] policy exported through official script
[ ] sim rollout video saved
[ ] HIL log saved
[ ] rollback path tested
```

---

## 6. 建议补充到项目里的代码改动

### 6.1 `microduck_local`：支持 custom actuator JSON + servo spec

建议新增 CLI 参数：

```python
# train.py
ap.add_argument("--bam-json", default=None, help="custom BAM params JSON")
ap.add_argument("--servo-kind", default="xl330", choices=("xl330", "sts3215", "hd1910"))
ap.add_argument("--kp-fw", type=float, default=None)
ap.add_argument("--max-current", type=float, default=None)
```

传到 env：

```python
if args.bam_json:
    kw["bam_json"] = args.bam_json
if args.servo_kind:
    kw["servo_kind"] = args.servo_kind
if args.kp_fw is not None:
    kw["kp_fw"] = args.kp_fw
if args.max_current is not None:
    kw["max_current"] = args.max_current
```

在 `MicroduckWalkEnv.__init__`：

```python
self.bam = BamServoActuator(
    self.model, self.data, C.JOINT_NAMES,
    dt=C.PHYSICS_DT,
    rng=np.random.default_rng(seed),
    servo_spec=servo_spec_for(servo_kind),
    params=json.load(open(bam_json)) if bam_json else None,
    kp_fw=kp_fw or servo_spec.default_kp,
    max_current=max_current if max_current is not None else servo_spec.max_current,
    delay_min_lag=measured_delay_min,
    delay_max_lag=measured_delay_max,
)
```

### 6.2 `microduck_rl`：用 `json_path`，不要改 site-packages

```python
# microduck_rl/src/mjlab_microduck/robot/microduck_constants.py
_BAM_ACTUATOR_KWARGS = dict(
    json_path=str(Path(__file__).resolve().parents[3] / "params" / "hd1910" / "m1.json"),
    target_names_expr=(r"^(?!passive_).*",),
    kp_fw=32.0,
    vin_range=(6.8, 8.4),
    vin_drop_gain_range=(0.0, 0.2),
    vin_min=6.0,
    delay_min_lag=3,
    delay_max_lag=6,
)
```

### 6.3 `microduck` runtime：抽象 bus backend

保持 control/safety/policy 不动，只替换 IO backend。

```rust
pub enum BusBackend {
    DynamixelXl330(DynamixelIo),
    FeetechHd1910(FeetechIo),
}

impl RobotIo for BusBackend {
    fn read(&mut self) -> Result<Sensors> {
        match self {
            Self::DynamixelXl330(x) => x.read(),
            Self::FeetechHd1910(x) => x.read(),
        }
    }
    fn write(&mut self, targets: &JointTargets) -> Result<()> { /* same pattern */ }
    fn set_gain(&mut self, kp: u16) -> Result<()> { /* same pattern */ }
    fn set_torque(&mut self, on: bool) -> Result<()> { /* same pattern */ }
    fn slow_sensors(&mut self) -> Result<SlowSensors> { /* same pattern */ }
}
```

---

## 7. 我需要你确认的问题

为了把 plan 从“风险地图”变成“可执行工程任务”，需要你确认：

1. **HD-1910-C001 协议/寄存器手册**：图片已提供机械/电气规格，但还缺 TTL 串行总线协议、寄存器、速度单位、电流单位、P/I/D、ID/baud 配置、同步读写能力、温度/电压读数。
2. **你准备使用的主板**：是否就是 Radxa Zero 3W？如果不是，型号是什么？是否有 CSI、NPU/VPU、可用 UART、Linux 支持？
3. **连接板目标**：是复刻原 Microduck HAT，还是自己设计一块电源+总线+IMU/ToF 连接板？
4. **第一版行为目标**：只要走路/站立，还是要 camera/ToF/autonomous soccer/tidy？
5. **训练资源**：是否愿意用 HF Jobs/云 NVIDIA GPU？如果只能 Apple Silicon，本地训练可做 MVP，但最终 sim2real 风险会更高。
6. **机械 CAD**：是否已经有 clone 的 CAD/BOM？能否导出每个部件质量、惯量和 joint frames？

---

## 8. 建议更新原 `custom-motor-guide.md` 的要点

如果继续保留那份 guide，我建议至少改这几条：

1. 把“外形尺寸一致，MJCF 无需修改”改成“可先不改碰撞几何，但必须复核质量/惯量/CoM/限位/齿隙”。
2. 把 XL330 参考电压和力矩改成 repo 实际使用的 `6.5–8.2V`、`kt*1.75A≈0.640Nm`、`vin=7.5V nominal`。
3. BAM 内置 Feetech 写成：`sts3215` actuator + `feetech_sts3215_7_4V/m1.json` 参数；不要暗示 HD-1910 可直接用。
4. 自定义参数用 `json_path` 纳入 repo，而不是复制到 `.venv/site-packages`。
5. 加上 `bam.process` 重采样步骤和额外依赖：`optuna`, `wandb`, `pypot` 或 `dynamixel_sdk`。
6. `microduck_local` 章节说明：仅 `params=` 不足以完整换电机，必须泛化 servo control constants。
7. 删除或修正 `train-walk --init-from <onnx>`；`--init-from` 是 run dir，不是 ONNX。
8. 把 `infer_policy.py` 标成 MuJoCo rehearsal，不是真机部署。

---

## 9. 推荐总体路线图一句话版

**先不要围绕 HD-1910 直接做整机。** 先用一周把 HD-1910 的协议、50Hz bus、读数、温升和 BAM 可辨识性验证掉；如果它过关，再做 connector board 和 MJCF delta；Mac 上用 `microduck_local` 做快速验证，NVIDIA/HF Jobs 做最终 `microduck_rl` 训练；真机部署保持 61D/14 action contract，通过 runtime 的 `RobotIo` 后端适配新电机，而不是改 policy 接口。
