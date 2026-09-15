# 路线图：用第三方舵机复刻 Microduck 并重训

**目标**：用飞特 HD-1910-C001 替代 Dynamixel XL330-M288-T，把鸭子从站立训到走路，再做更多动作。

约定：`[ ]` 未开始 · `[~]` 进行中 · `[x]` 完成 · `[!]` 卡住。
**每一项都写下"什么数字能判定它完成"** —— 这个项目的历史里全是"曲线看着对、看图是错的"。

---

## 两个必须先接受的前提

### ① 官方没有"跑"这个任务

官方 13 个 task：

| Task | 说明 |
|---|---|
| `Mjlab-Velocity-{Flat,Rough}` | **主任务**：速度指令走路 + 头部姿态 |
| `Mjlab-VelStand` | 走路 + 跌倒恢复合一 |
| `Mjlab-StandUp` / `SitStand` | 站起来 / 坐下站起 |
| `Mjlab-GroundPick` | 蹲下用嘴尖触地 |
| `Mjlab-BallKick` | 踢 70 mm 球（actor 看不见球） |
| `Mjlab-Roulade` | 前滚翻 |
| `Mjlab-Velocity-*-Rollers` / `Swizzle` / `RollerCrouch` / `RollerSlope` / `RollerStandUp` / `Spin` | 轮滑系列 |

**没有 run。**

> "从站立 → 走路 → 跑"里，**前两步是移植，第三步是新研究**。
> 对 737 g、25 cm、18–21 g 舵机的平台，跑步（需要腾空相）是边际目标。
> **止损线**：L3 做不出来就停在 L2，不要把项目拖死。

### ② 最大的风险不是通信，是执行器模型

官方 9 个策略和 **BAM M6** 模型都是在**实物 XL330** 上台架辨识出来的。

换电机 → **BAM 模型失效** → sim2real 无从谈起。而且**没法从官方策略蒸馏**
（老师本身就是错的），所以直接进入"从零训练"区间 —— 已实测：从零 30M 步只会往前扑。

> **整个路线图的重心因此是阶段 2。跳过它，后面全是赌博。**

---

## 阶段 0 · 选型决策 ✅

| | **飞特 HD-1910-C001** ⭐ | 飞特 STS3215 | 宇树 S288 |
|---|---|---|---|
| 电压 | **4–8.4 V（2S 原生匹配）** | 7.4 V | 12.6 V（要改 3S） |
| 重量 | 21±2 g | 55–60 g | 19.5 g |
| 堵转 | 1.47 N·m @7.4V | 1.86 N·m | 0.6 N·m @12.6V |
| 机械 | 需改件（已有人做过） | 整机重做 | 尺寸几乎相同 |
| 结果 | **还是同一只鸭子**（+45 g） | 变成 2.1 kg / 42 cm 的别的东西 | 供电系统重做 |

**决定：HD-1910-C001。** 详细理由与数据来源的置信度见
[`docs/decisions.md`](docs/decisions.md)。

两个已知事实：

- ✅ **电压反而是优势**：XL330 被超压运行（额定 6.0 V，实跑 6.6–8.2 V）；
  HD-1910 的 4–8.4 V **完整覆盖 2S 带载区间**，在额定内工作。
- ⚠️ **电流预算要重算**：HD-1910 堵转 **2.0 A** vs XL330 约 1.5 A → 15 颗 **30 A** vs 22.5 A。
  官方 HAT 每个舵机接口旁注 **「3A max」**，线径和接口分配**必须重新核算**。

> ⚠️ **下单前自己核这三个数**（见 decisions.md · 未核实项）：
> 电压区间、**额定负载力矩**（堵转 1.47 与额定 0.363 N·m 差 4 倍）、出厂运行模式。

---

## 阶段 1 · 通信打通 ⬜

**目标：`robotd` 能驱动 15 颗舵机并读出遥测。不做任何训练。**

| # | 任务 | 说明 |
|---|---|---|
| 1.1 | `[ ]` 协议层 | `rustypot` 有 feetech 模块；`duck-control/src/bus.rs` 现在是 `Xl330Controller`，换模块 |
| 1.2 | `[ ]` 寄存器表 | Dynamixel：124 块 / 144 电压 / 146 温度。飞特完全不同，`READ_LEN` / `SLOW_READ_ADDR` 都要重写 |
| 1.3 | `[ ]` `imu_to_dxl` 固件 | **硬件不变、固件双协议** —— 物理层相同（半双工单线 TTL / 1 Mbps / 3 线），只差包格式 |
| 1.4 | `[ ]` 出厂参数 | 出厂 ID 1、1 Mbps、模式 4；**过流/过压保护默认关闭，装机前必须打开** |
| 1.5 | `[ ]` 总线时序实测 | 官方 20 ms tick 装 16 个设备；飞特 return delay 出厂是 0，但**必须实测，不能假定** |
| 1.6 | `[ ]` 电流与线径 | 按 30 A 峰值重算；四个接口 × 3 A max 的分配 |

**✅ Gate 1**：`robotctl health` 能报出 15 颗舵机的电压/温度，`robotctl monitor` 画得出关节角。
**在这一步之前不要碰训练。**

---

## 阶段 2 · 台架辨识 ⬜ ← 关键路径

**这是最重要、也最容易被跳过的一步。** 官方 BAM M6（`motor_name="xl330", model="m6"`）就是这样来的。

**方法现成**：`microduck_rl/scripts/testbench_sim2real.py` 就是那个台架 ——
一颗舵机 + 已知惯量臂，跑固定目标序列，sim（BAM M6 作为起点）vs 实测对比。

```bash
cd ~/Projects/microduck-lab/microduck_rl
uv run python scripts/testbench_sim2real.py --mode sim  --onnx p.onnx --out sim.npz
uv run python scripts/testbench_sim2real.py --mode real --onnx p.onnx --out real.npz \
    --port /dev/cu.usbserial-XXXX      # macOS 不是 /dev/ttyUSB0
uv run python scripts/testbench_sim2real.py --compare sim.npz real.npz --out-plot cmp.png
```

**必须辨识出来的量**（对照官方 M6 参数表；飞特按 4.8 / 6 / 7.4 V 三档给参数，2S 带载区间最接近 7.4 V 那列）：

| 参数 | 官方 XL330 | HD-1910 |
|---|---|---|
| `kp_fw` 固件位置环刚度 | 200 | **要测** |
| `vin_range` | (6.5, 8.2) | (6.5, 8.2)（同 2S，可先沿用） |
| 堵转力矩 vs 电压曲线 | 0.52–0.60 N·m | 标称 1.47 N·m @7.4V，**要实测** |
| 齿轮箱摩擦（库仑 + Stribeck） | 已辨识 | **要辨识**（sim2real 不确定性的主要来源） |
| 回差 backlash | 建模 ±1.0° | **要测**（标称 ≤0.5°） |
| 减速比 | 288.4:1 | **1/320**（不同！） |
| 指令延迟 lag | 3–6 控制步 | **要测** |
| 电流限幅 | 1.75 A | 标称 2.0 A 堵转，**实测** |

**✅ Gate 2**：拿到自己的 `hd1910/m6.json`，且**同一份 ONNX 在 sim 和实物上的关节轨迹对得上**（台架图叠得上）。

> 💡 官方用 `--to-bam` 把 rollout 转成 BAM log 格式喂给 `bam.plot`，这条工具链直接复用。
> 记录写进 [`docs/actuator-identification.md`](docs/actuator-identification.md)。

---

## 阶段 3 · 机械与模型对齐 ⬜

| # | 任务 | 说明 |
|---|---|---|
| 3.1 | `[ ]` 改打印件 | **已确认要改**：HD-1910 与 XL330 在"压腿那一处"结构不同（社区已改并重打成功） |
| 3.2 | `[ ]` 重测质量/惯量 | 737 g → 约 782 g（+45 g），重心位置也变了 |
| 3.3 | `[ ]` 更新 MJCF | 质量、惯量、CoM、关节限位、减速比、backlash 模型 |
| 3.4 | `[ ]` 接线 | 2.0 mm PH vs 2.5 mm JST EH **插不进对方，且脚序相反**（1=Signal/2=Vcc/3=GND vs 1=GND/2=Vcc/3=Signal）。中间那根一定是 Vcc，**接反才烧** |

**✅ Gate 3**：MJCF 里的质量和**实测**一致（上秤验证），基线评测跑得通。

---

## 阶段 4 · 分阶段训练 ⬜

**两套架构，别混：**

| | 本地 `microduck-lab` | 云端 `microduck_rl` |
|---|---|---|
| 用途 | **reward 设计、课程、快速试错** | **正式训练** |
| 反馈 | 分钟级 | 小时级 |
| 引擎 | CPU MuJoCo + SB3 | MuJoCo Warp + rsl_rl（**要 CUDA**） |
| 产出 | 值得移植的 env 设计 | 上真机的策略 |

**阶梯**（每一级都有判据）：

| 级 | 目标 | 参考 | 判据 |
|---|---|---|---|
| **L0** | `[ ]` **站立** | `StandUp` / `alpha_stand` 的 cfg | `ep_len` 跑满、0 摔倒 |
| **L1** | `[ ]` **走路** | **主任务** `Velocity` | `select-run` 按**实际地速**打分，`--max-falls` 通过 |
| **L2** | `[ ]` 抗扰动走路 | `VelStand` | 开 `push_robot` 后仍不摔 |
| **L3** | `[ ]` **跑步** | ⚠️ **无参考，新研究** | contact sheet 里 `airborne > 0` 且不摔 |
| **L4** | `[ ]` 更多动作 | `Roulade` / `BallKick` / `GroundPick` / 轮滑 | 逐项对齐官方 task |

**本地原型 → 云端正式的循环：**

```bash
# 本地：分钟级试 reward
cd ~/Projects/microduck-lab/microduck_local
uv run train-behavior run --envs 24 --steps 3_000_000 --run-name proto
uv run render-rollout --policy runs/proto/policy.onnx --out /tmp/rr   # 看图，别看曲线

# 云端：正式训练（本地没有 CUDA）
cd ../microduck_rl && uv run train Mjlab-Velocity-Flat-MicroDuck \
    --env.scene.num-envs 4096 --hf-jobs
```

> ⚠️ **这个仓库的铁律：数字说会走不算，得看图。**
> 已实测：`falls: 0/20`、回合跑满 1000 步的"完美"策略 —— 接触表一看两脚 100% 着地，站着不动。

---

## 阶段 5 · sim2real 落地 ⬜

| # | 任务 |
|---|---|
| 5.1 | `[ ]` 单关节：台架图上 sim 和实物叠得上（阶段 2 已做） |
| 5.2 | `[ ]` 整机站立：真机先只跑 stand；`limp_fall` 的 `gain_limp` 按新舵机重调 |
| 5.3 | `[ ]` 走路：短距离、平地、有人看着开始 |
| 5.4 | `[ ]` 重标电压自适应：`robotd.toml` 的 `nominal_voltage = 7.4` 和钳位 6.0–9.5 V 是按 XL330 的力矩-电压关系设的 |

---

## 算力与预算

| 用途 | 平台 | 量级 |
|---|---|---|
| reward 原型 / 评测 / 渲染 | 本地 M5 Max | 免费，分钟级 |
| 正式训练 | HF Jobs 或一张 CUDA 卡 | **10–30 GPU 小时**出第一个能走的 |
| 台架数据采集 | 本地，插 USB | 数小时 |

**预期失败 3–5 轮。** 官方记录：从零 30M 步只买到"不往前扑"（实测 22.5M 时 0.265 m/s 但 100% 摔倒，之后退化）。
换电机等于把"执行器"这个变量重新打开，第一轮不出步态是正常的。

---

## 风险清单

| 风险 | 严重度 | 应对 |
|---|---|---|
| **执行器模型不对** | 🔴 致命 | 阶段 2 不可跳过 |
| 电流预算超（30 A vs 接口 3 A max） | 🔴 | 阶段 1 就重算线径和接口分配 |
| 跑步做不到 | 🟡 | L3 是研究不是移植；设止损停在 L2 |
| 机械改动引入新回差 | 🟡 | 阶段 3 实测，喂回 backlash 模型 |
| 从零训练烧钱不收敛 | 🟡 | 本地先用 `microduck-lab` 把 reward 调对再上云 |

---

## 具体的前两周

| 天 | 做什么 |
|---|---|
| **1** | **不要买东西，先读代码。** `git clone https://github.com/fanhao375/microduck-replica` —— CAD、HD-1910 改件、`imu_to_dxl` 设计、BOM、踩坑全在里面，能省掉几个月 |
| **2–3** | 下单（15 × HD-1910-C001 + FE-URT-2 调试板 + NP-F550 + Radxa Zero 3W 2G/16G）；同时读 `duck-control/src/bus.rs`（要改的就是它）和 `testbench_sim2real.py` |
| **第 1 周** | 阶段 1：`rustypot` 换 feetech，先用**一颗**舵机把寄存器表和时序打通 |
| **第 2 周** | 阶段 2 开工：一颗舵机装上台架臂，跑第一组 sim-vs-real 对比。**这一组的图，决定整个项目能不能成** |
