# Apple Silicon 吞吐基准（Week 0.5 Go/No-Go）

日期：2026-09-16
范围：回答 `microduck-clone-validation-risk-plan.md` Week 0.5 的唯一问题——
**Apple Silicon 能不能替代 NVIDIA 做正式训练？**
交付物对应计划里要求的决策表与明确 Go/No-Go 结论。

---

## 0. 结论：**No-Go**（不依赖任何硬件的部分已经测完）

在这台 M5 Max 上，官方 `microduck_rl` 的 MicroDuck velocity 任务可以真实运行
（物理、奖励、域随机化、61→14 contract 全部完好），但**吞吐只有约 950 env steps/sec**，
比 CUDA 路线低约两个数量级：

| | 单次正式训练（4096 envs × 4000 iters ≈ 3.93 亿 env steps） |
|---|---:|
| **本机 Mac（M5 Max，CPU 物理）** | **约 115 小时 ≈ 4.8 天** |
| 云 NVIDIA（官方 README 口径） | 约 1–2 小时 |

> **红线（沿用计划 Week 0.5）：** 本结论及任何「Mac 上能训练」的说法都必须注明当时的
> `num-envs`。本次最优档是 **1024 envs**；`--num-envs 16` 能跑 ≠ 能做正式训练。

**建议路线：** Mac 保留作为开发 / 验证 / smoke / viewer 机（这条完全没问题），
正式训练走 NVIDIA（`--hf-jobs` 或租卡）。与计划 R1、Week 8–9 的默认假设一致。

> **但这个建议在 9.5 节被放宽了：** `microduck_local` 与 `microduck_rl` 的 DR 缺口只有
> **3 个可闭合的 obs 级项**，而它在 Mac 上快 20 倍——官方那套 step 预算过夜（~6–8 h）就能跑完。
> 所以正式训练是**云 GPU（保真度基准）** 或 **Mac 过夜（零成本 MVP）** 两条路，
> 不是「必须租卡」。见 9.5。

> **No-Go 的范围（重要，见第 9 节）：** 上表 950 steps/s 是 **`microduck_rl`** 在 Mac 上的数字。
> 计划 Week 4/5 实际使用的 **`microduck_local`** 在同一台机器上是 **~19,000 steps/s（快 20 倍）**，
> 全部命令实测通过、迭代约 82 秒。**否掉的是「在 Mac 上跑 `microduck_rl` 正式训练」，
> 不是「Mac 能不能做开发」。**

---

## 1. 测试环境

| 项目 | 值 |
|---|---|
| 机型 | Apple M5 Max |
| CPU | 18 核（6 性能 + 12 能效） |
| GPU | 40 核（**本基准中未被使用，原因见第 4 节**） |
| 内存 | 128 GB |
| 系统 | macOS 26.6.2 (25G83) |
| `microduck_rl` | `badc4e7ffe5507fd7acb1a21487bd2925c1afe5a`（CI pinned） |
| 任务 | `Mjlab-Velocity-Flat-MicroDuck` |
| `warp-lang` | 1.12.0 |
| `torch` | 2.9.1（MPS 可用） |
| 日志 | `working-docs/apple-silicon-bench/logs/` |

---

## 2. 决策表（计划 Week 0.5 要求的那张）

| 平台 | 峰值 num-envs（不 OOM） | 峰值 env steps/sec | 折算单次正式训练 | 单次成本 |
|---|---:|---:|---:|---:|
| **本机 Mac（M5 Max）** | **4096**（内存 8.1 GB，远未触顶） | **953** | **≈ 115 h ≈ 4.8 天** | 电费 ~0 |
| 云 NVIDIA | 待补测 | 待补测 | README 口径 ~1–2 h | 待你补测 |

**关于「峰值 num-envs」这一列要特别注意：** 它填 4096 是因为 `4096` **跑得起来**
（峰值 RSS 仅 8.1 GB / 128 GB），**不是因为它快**。吞吐在 1024 envs 就到顶，
之后 env 越多越慢——env 数不提升并行度，只增加调度开销。所以：

- 计划的「不 OOM」判据在这台机器上**不构成约束**（内存从不是瓶颈）；
- 真正的约束是 **CPU 并行度**，它决定了 ~950 steps/s 的天花板。

---

## 3. 吞吐阶梯原始数据

`64 / 256 / 512` 各跑 50 iteration（计时基准），`1024 / 2048 / 4096` 各跑 10 iteration
（峰值扫描）。全部 0 error、0 traceback。`steps/s = num_envs × 24 ÷ 平均 iteration 耗时`
（`NUM_STEPS_PER_ENV = 24`）。

| envs | iterations | 平均 s/iter | **env steps/sec** | 峰值 RSS |
|---:|---:|---:|---:|---:|
| 64 | 50 | 2.06 | 746 | – |
| 256 | 50 | 6.77 | 908 | – |
| 512 | 50 | 13.04 | 943 | – |
| **1024** | 10 | 25.78 | **953 ← 峰值** | 1.99 GB |
| 2048 | 10 | 54.16 | 908 | 3.46 GB |
| 4096 | 10 | 119.14 | 825 | 8.13 GB |

原始日志（每档完整输出，含逐 iteration 耗时）：
`logs/envs-64.log`、`logs/envs-256.log`、`logs/envs-512.log`、
`logs/peak-1024.log`、`logs/peak-2048.log`、`logs/peak-4096.log`。

按各档吞吐折算的正式训练耗时（3.93 亿 env steps）：

> ⚠️ **口径说明（重要，避免误读）：** 下表用的 **4000 iterations 是「收敛预算」口径**，
> 来源是 `microduck_rl/AGENTS.md:208-209`：*"gaits and curriculum-heavy recovery need
> 4000–6000"*，与 README 的 *"~1-2 h for a usable gait at 4096 envs"* 一致。
>
> **它不是代码里的默认值。** walk 任务的 `MicroduckRlCfg` 配的是
> **`max_iterations=50_000`**（`microduck_velocity_env_cfg.py:948`）——即不加
> `--agent.max_iterations` 跑官方命令，它会一直跑到 5 万次迭代才停。
>
> **三个口径 × 三条路线**（第 2、3 列都是**本机实测**吞吐；第 4 列为反推）：
>
> | 口径 | env steps | `microduck_rl`<br>Mac @950/s | `microduck_local`<br>Mac @19,000/s | 云 NVIDIA<br>@~73,000/s **[反推]** |
> |---|---:|---:|---:|---:|
> | 4000 iters（收敛估算，本报告采用） | 3.9 亿 | 4.8 d | **5.8 h** | 1.5 h |
> | 6000 iters（curriculum-heavy 上限） | 5.9 亿 | 7.2 d | **8.6 h** | 2.3 h |
> | 50,000 iters（`rl` 代码默认上限） | 49.2 亿 | 59.9 d | **3.0 d** | 18.8 h |
>
> **三条必须一起读的注意事项：**
>
> 1. **第 3 列是「step 数折算」，不是「等效质量」。** `microduck_local` 原生的单位是
>    `--steps`（`train-walk` 默认 3M），**没有「iteration」这个概念**；
>    第 3 行用 50,000 iters 只是拿 rl 的口径换算成等量 step 数做算力比较。
>    两个 harness 的步数**不可等价**（见 9.5）。
> 2. **不要因此删掉第 2 列。** 本节（第 3 节）的主题就是「`microduck_rl` 在这台 Mac 上有多慢」，
>    4.8 天 / 60 天是那个问题的正确答案。第 3 列是**补充**，不是替换。
> 3. **云 GPU 那一行仍然保留为保真度基准**——因为「`local` 能不能替代 `rl` 出可上真机的策略」
>    是**未证命题**（9.5 节）。算力上 Mac 够用，保真度上仍是 rl 的默认推荐。
>
> 所以 **No-Go 的表述要更精确**：否掉的是「用 `microduck_rl` 在 Mac 上做正式训练」
> （4.8–60 天，不可行）；没有否掉「Mac 用 `microduck_local` 过夜跑完同量级 step 预算」
> （5.8–8.6 h，可行）。

| envs | 折算耗时 |
|---:|---:|
| 64 | 146.4 h = 6.10 天 |
| 256 | 120.3 h = 5.01 天 |
| 512 | 115.9 h = 4.83 天 |
| 1024 | 114.6 h = **4.77 天** |
| 2048 | 120.4 h = 5.01 天 |
| 4096 | 132.4 h = 5.52 天 |

> 若预算取 `6000 iterations`（计划 AGENTS.md 里 curriculum-heavy gait 的上限），
> 最优档约 **7.2 天**。

---

## 4. 为什么「改成 MPS / 用 Apple GPU」不解决问题 ⭐

这是本次最重要的结论之一，因为 Mac 上「有 GPU」这个事实很容易让人误判。

### 4.1 Apple GPU 对物理仿真**根本不可用**

两处独立证据：

```text
$ uv run python -c "import warp as wp; wp.init(); print(wp.get_devices())"
devices: [('arm', 'cpu')]                              # 只有 CPU，没有 Metal

$ uv run python -c "import warp as wp; wp.get_device('metal')"
ValueError: Invalid device identifier: metal           # Warp 里根本没有 metal 设备
```

- **`warp-lang` 的 macOS wheel 里没有任何 Metal 后端文件**（实测 glob `*metal*` 为空）；
- **`mujoco_warp` 是 CUDA-only**：`mujoco_warp/_src/io.py:86` 会*「check for compatible
  cuda toolkit and driver versions」*；
- 因此 MuJoCo Warp 的物理步进在这台 M5 Max 上**只能走 CPU**，与是否有人写 MPS 移植无关。

### 4.2 就算把 MPS 接上，收益也只有 ~1.4%

物理之外唯一能上 MPS 的是 PPO 的 MLP 更新。用真实网络形状实测
（actor `61→512→256→128→14`，critic `76→…→1`，`24 steps/env`、
`5 epochs × 4 minibatches`、batch 12288；脚本 `mps_ceiling.py`）：

| | 每次 iteration 的网络计算耗时 |
|---|---:|
| CPU | 215.1 ms |
| **MPS** | **31.4 ms**（网络本身快 **6.85×**） |

但把这个数字放回真实的 13.04 s/iteration（512 envs）里：

| | 占 iteration 比例 |
|---|---:|
| **物理（只能 CPU，MPS 碰不到）** | **98.35%** |
| 网络计算 | 1.65% |
| **完美 MPS 移植后的最佳结果** | **快 1.41%**（13.04 s → 12.86 s） |

**结论：** 「改成 MPS」最多省 1.4%，因为它加速的那 1.65% 本来就不是瓶颈。
计划 R1 预判的*「MPS 只能加速那个小 MLP 的 policy update，加速不了 Warp 的物理 backend」*
现在有了数字：**98.35% vs 1.65%**。

### 4.3 真正能改变数量级的选项

| 选项 | 是否能提速 | 说明 |
|---|---|---|
| 换 MPS | ❌ ~1.4% | 见上 |
| 换 Apple GPU / Metal | ❌ 不可行 | Warp 无 Metal 后端 + mujoco_warp CUDA-only |
| 调 `num-envs` | ❌ 已测 | 1024 是峰值，再堆只会更慢 |
| **云 NVIDIA GPU** | ✅ **~2 个数量级** | 官方路径，Week 8–9 路线 A |
| MJX/JAX Metal 或自研 vectorized backend | ⚠️ 理论可行 | 工程量大，sim2real 需重新验证（计划 R1 已列） |

### 4.4 「那把 MuJoCo Warp 移植到 Metal 呢？」

这个方向不是错的，但**成本结构是决定性的**，而且障碍在两层，第一层根本不在
`mujoco_warp` 里。

**第一层：Warp 自己就没有 Metal 后端（NVIDIA 的代码，不是 mujoco_warp 的）**

NVIDIA Warp 官方 README 原文：

> The Windows x86-64 and Linux wheels support CPU execution and CUDA acceleration.
> **The macOS wheels support CPU execution but not Metal acceleration.**

本机实测一致——Warp 里**没有任何 Metal 后端痕迹**：

```text
find warp/native -iname "*metal*" -o -iname "*.metal" -o -iname "*.msl"   → 空
libwarp.dylib symbols:   metal 0 个   /   cuda 100 个
整个 warp 包里唯一的 "metal" 字符串 → _src/thirdparty/dlpack.py 的 kDLMetal = 8（DLPack 枚举常量）
```

要动这一层，等于给 Warp 新写一个后端：

| 组件 | 规模 |
|---|---:|
| `context.py`（运行时/设备管理） | 10,018 行 |
| `codegen.py`（代码生成） | 4,896 行 |
| native 源码 | 75 个文件：7,972 行 `.cu` + 7,128 行 `.cpp` + 51,856 行 `.h` |
| CUDA 专属符号 | `__device__` 382、`__global__` 51、`cudaGraph` 101、`cudaStream` 59、`cudaMalloc` 11 |

即：MSL 代码生成 + 内核启动 + 内存管理 + autodiff + Warp 的高级特性
（尤其 `wp.tile`，它映射到 shared memory / tensor-core 级原语）。

**第二层：`mujoco_warp` 自己适配（这才是「移植」本体）**

| 项目 | 数量 |
|---|---:|
| 规模 | 69 个文件、54,813 行 |
| kernel | **242 个** |
| `wp.launch` 调用点 | 260 |
| **`wp.tile` 使用** | **143**（最难移植的特性） |
| `wp.atomic` | 128 |
| CUDA graph capture | 15 处（9 `wp.capture` + 6 `wp.ScopedCapture`） |
| `wp.sync` | 43 |

其中 **CUDA graph 是 mujoco_warp 性能的核心**（几千个 world 的并行步进靠 graph 压低
launch 开销），Metal 没有对等物，得用 indirect command buffer 重新架构。

**第三层（容易被忽略）：验证成本**

`microduck_rl` 的整个价值就是 sim2real 保真度。换物理后端后，
BAM actuator、friction DR、backlash、接触求解的数值都要和 CUDA 版逐一对照，
否则训出来的 policy 不能上真机——计划 R7/R8 的风险会全部重新打开。

**决策：算经济账**

| 方案 | 成本 | 单次正式训练 |
|---|---|---:|
| 移植 Warp→Metal（估） | **1–2 人年**（Warp 后端 6–18 人月 + mujoco_warp 适配 + 验证），非本人可估的准确值 | 之后才可能到小时级 |
| 租云 GPU | **$2–4/次**（A100 1–2 h） | 1–2 小时 |

即使按 100 次训练算，租卡约几百美元；移植是 5 个数量级的差距。
**只有当「Apple 原生训练」本身就是产品/研究目标时，这个移植才划算。**

**如果真要走 Apple 原生，正确的目标不是 `mujoco_warp`，而是 MJX（MuJoCo XLA / JAX）**——
因为 JAX 已经有（实验性的）Metal 后端，不必从零写一个 Warp 后端。
但 `jax-metal` 目前维护状态不佳，且同样要重做上述第三层的 sim2real 验证。

**务实的中间路线：** 你其实并不需要 Apple 原生才能开发。这台 Mac 已经能做
开发、viewer、contract 测试、BAM/actuator 参数验证、以及计划 Week 4/5 那种
1M steps 的小规模冒烟（1M ÷ 950 steps/s ≈ **18 分钟**）——只有最后那次
4000 iteration 的正式训练需要 GPU。

---

## 5. 两个必须先知道的坑

### 5.1 官方命令在 Apple Silicon 上**开箱即死**（早于 iteration 0）

```bash
uv run train Mjlab-Velocity-Flat-MicroDuck --env.scene.num-envs 16 --agent.max_iterations 5
# → IndexError: list index out of range
#   mjlab/utils/gpu.py:70, in select_gpus
#       selected_gpus = [available_gpus[i] for i in gpu_ids]
```

原因：torch 为 CPU-only（`torch.cuda.device_count() == 0`），`select_gpus()` 对空列表取下标。
这与 `microduck_rl/AGENTS.md` 里记录的 linux-aarch64 失效模式同源，
只是触发点不同（那里是 `torch.cuda.device_count()==0`，这里是同一个 `select_gpus`）。

**修正：** 计划里预判的「功能上能跑」需要先补一个前提——
**不是「改 `device="cuda"` 为 `"mps"`」，而是必须走 mjlab 自带的 CPU 模式。**

### 5.2 官方自带 CPU 模式，一行环境变量即可

`mjlab/utils/gpu.py:56` 的注释写明了这条路径：

```python
# Empty CUDA_VISIBLE_DEVICES means CPU mode.
if not available_gpus:
    return None, 0
```

```bash
CUDA_VISIBLE_DEVICES="" WANDB_MODE=disabled \
  uv run train Mjlab-Velocity-Flat-MicroDuck --env.scene.num-envs 1024 --agent.max_iterations 10
```

- `CUDA_VISIBLE_DEVICES=""` → 触发 CPU 模式（**无需改任何源码**）；
- `WANDB_MODE=disabled` → 本机未配 wandb API key；wandb 只是 logging sink，
  不影响物理与吞吐。

另外两个环境事实（记录以免下次踩）：

- `uv sync` 在 macOS arm64 上**成功**（装下 `warp-lang`/`torch`/`mjlab`），
  计划里担心的「Warp/CUDA 依赖直接卡住 uv sync」**没有发生**；
- 本仓库无 `cargo`，`microduck` Rust runtime 目前只能克隆不能构建（后续做 R4/`FeetechIo` 时需要装）。

---

## 6. 功能正确性核查（计划要求「不能只看代码能跑」）

计划 Week 0.5 要求区分「功能正确性」与「吞吐可行性」。CPU 模式下逐条核对：

| 检查项 | 结果 | 证据 |
|---|---|---|
| 真的在 step environment | ✅ | 每 iteration 打印完整 reward/metrics 块，`Episode_Termination/fell_over` 等按物理演化 |
| 没有偷偷换回 XML actuator | ✅ | 仍用 `FrictionDRBamActuatorCfg`，`motor_name="xl330"`, `model="m6"`, `kp_fw=200`, `vin_range=(6.5,8.2)`, `delay_min/max_lag=3/6`（`robot/microduck_constants.py:132`） |
| 关键域随机化仍开着 | ✅ | `Curriculum/com_range`、`head_pose_range`、`body_pose_range`、`action_rate_weight`、`standing_envs` 等逐 iteration 输出 |
| observation contract 仍是 61 | ✅ | 日志：`Active Observation Terms in Group: 'actor' (shape: (61,))`、`Linear(in_features=61, …)` |
| action contract 仍是 14 | ✅ | 日志：`Active Action Terms (shape: 14)` |
| obs normalizer 在位（必须 bake 进 ONNX） | ✅ | 日志：`(obs_normalizer): EmpiricalNormalization()` |
| reward 曲线能增长 | ⚠️ 未验证 | 只跑了 10–50 iteration 的 smoke/吞吐，未做长训练 |
| ONNX export 成功且被下游接收 | ✅ **已验证**（`microduck_local` 路径） | `export-walk` rc=0 → 793,935 B；`onnxruntime` 读回：新导出的与官方 `alpha_walking.onnx` **签名完全一致** `input=obs[1,61] output=actions[1,14]`，喂零观测前向推理成功、输出有限。**注意：`microduck_rl` 的 `scripts/export.py`（需 wandb run path）仍未验证。** |
| 与 CUDA 小规模 run 行为接近 | ⚠️ 未验证 | 需要云 GPU 对照，见第 8 节 |

**小结：** 功能侧的核心不变量（物理、BAM、DR、61→14、normalizer）在 CPU 模式下**全部成立**，
没有出现计划警告的「偷偷退化物理模型」。所以 No-Go 的理由**纯粹是吞吐**，不是正确性。

---

## 7. 复现方式

```bash
# 一次性环境（本仓库根目录）
cd microduck-lab && ./scripts/setup.sh

# 计时基准（64/256/512，各 50 iters，顺序执行避免互相抢 CPU）
cd ../working-docs/apple-silicon-bench && ITERS=50 ./run.sh 64 256 512

# 峰值扫描（1024/2048/4096，各 10 iters，附带内存采样）
ITERS=10 ./probe-peak.sh 1024 2048 4096

# MPS 收益上限
cd ../../microduck-lab/microduck_rl && uv run python \
  ../../working-docs/apple-silicon-bench/mps_ceiling.py
```

⚠️ **阶梯必须顺序跑。** 并发跑会互相抢 CPU，steps/sec 直接失去意义。

---

## 8. 未完成 / 待你补测

1. **云 NVIDIA 对照行**（决策表第 2 行）——需要你的云账号：
   计划要求「Vast/Lambda 租 1h 4090 或 A100 跑同样 smoke 做对照」。
   本机无法代跑。也可以直接用官方路径：
   ```bash
   uv run train Mjlab-Velocity-Flat-MicroDuck \
     --env.scene.num-envs 4096 --agent.max_iterations 4000 \
     --hf-jobs --flavor a100-large --run-name clone-throughput-baseline
   ```
   （`--hf-jobs` 需要先 `hf auth login`；flavor 可选 `l4x1`(默认)/`a10g-large`/`a100-large`，
   默认 `--timeout 12h`。见 `microduck_rl/scripts/hf/README.md`。）
2. **`microduck_rl` 的 ONNX export**——`microduck_local` 的 `export-walk` 已闭环验证（见第 6 节），
   但官方栈的 `scripts/export.py` 需要 `--wandb-run-path`，本次没跑。补测方式：
   产出 checkpoint 后走 `scripts/export.py`（必须走它，它会 bake normalizer）。
3. **长训练 reward 曲线**——本次只验证了能跑与吞吐，没有验证学得会。

---

## 9. Mac 的能力边界：Week 4/5 每条命令实测

No-Go 的范围比听起来**窄得多**。上面第 3 节的 950 steps/s 是 **`microduck_rl`** 的数字；
计划 Week 4/5 真正用的是 **`microduck_local`**（CPU MuJoCo + SB3，另一套 harness），
它在同一台 M5 Max 上快 **约 20 倍**。

### 9.1 实测（本机空载，脚本 `apple-silicon-bench/bench-week45.sh`）

用计划 Week 5 的**原命令**跑，`train-walk`（`--actuator bam` + 域随机化 + obs 噪声）：

| 命令 | 实测耗时 |
|---|---:|
| `train-walk --envs 16 --steps 1_000_000` | **67.2 s**（≈14,900 steps/s） |
| `train-walk --envs 32 --steps 1_000_000` | **52.7 s**（≈19,000 steps/s） |
| `export-walk runs/...` | **0.9–2.5 s** |
| `distill --teacher ../microduck/policies/alpha_walking.onnx` | **66.3 s** |
| `render-rollout --policy ... --behavior run` | **15.3–22.5 s** |
| `pytest tests/test_env_contract.py test_walk_env_physics.py test_bam_actuator.py` | **5.0 s** |
| `pytest tests/`（全套，文档口径） | ~4–6 min |

全部 `rc=0`，无 Traceback。产出已验证：`policy.onnx`（793,935 B）+ `ep0.mp4` + `ep0_sheet.png`。

**注意 `train-walk` 用了 n_steps≈51/env**（不是 `BehaviorEnv` 的 256），
所以 1M steps 在 16 envs 下是 1220 次 update、32 envs 下是 610 次——两者总步数一致，
这正好交叉验证了「1M 步」确实跑满。

### 9.2 一次完整的原型迭代 ≈ **82 秒**

```
改 reward → train-walk 1M 步 (67 s) → export (2 s) → render-rollout (15 s) → 看 sheet.png
```

这正是 `microduck_local` README 承诺的「minutes-long feedback loop」，实测成立。
32 envs 下更快：`53 + 2 + 15 ≈ 70 s`。

### 9.3 两个 harness 在这台 Mac 上的对比

| harness | steps/s | 来源 |
|---|---:|---|
| **`microduck_local`**（train-walk，BAM+DR） | **~19,000** | 本次实测 |
| `microduck_local`（train-behavior，README 口径） | ~17,100 | README |
| `microduck_rl`（CPU 模式） | **950** | 本次实测（第 3 节） |
| `microduck_rl`（CUDA，官方 1–2 h / 3.93 亿步） | ~55,000–109,000 | **[由 README 口径反推，非实测]** |

**结论：在 Mac 上做原型应该用 `microduck_local`，永远不要用 `microduck_rl`。**
后者在 Mac 上比前者慢 20 倍——它的存在意义是 CUDA 上的最终训练。

按 ~19,000 steps/s 外推 `microduck_local`（同一台机器）：

| 训练量 | 耗时 |
|---:|---:|
| 1M steps（计划 Week 5） | ~1 min |
| 10M steps | ~9 min |
| 100M steps | ~1.5 h |
| 1B steps | ~15 h |

### 9.4 边界在哪里

| 计划阶段 | Mac 能否闭环 | 依据 |
|---|---|---|
| **Week 0.5** Apple 吞吐 Go/No-Go | ✅ 已完成 | 本报告 |
| **Week 4** 仿真 smoke + viewer | ✅ 能（5 s + 22 s + 实时 viewer） | 实测 |
| **Week 5** CPU 小规模训练 + 导出 | ✅ 能（迭代 ~82 s） | 实测 |
| Week 1 单电机 + 总线 spike | ❌ 需硬件（HD-1910 + 主板） | 非算力问题 |
| Week 2 机械参数测量 / MJCF delta | ❌ 需实物称重测量 | 非算力问题 |
| Week 3 BAM 辨识 | ❌ 需真电机采集数据 | 非算力问题 |
| Week 6 runtime `FeetechIo` | ⚠️ 需硬件；且**本机无 `cargo`**，Rust 也构建不了 | 见第 5.2 节 |
| Week 7 真机 HIL | ❌ 需整机 | 非算力问题 |
| **Week 8–9 正式训练** | ⚠️ **两条路**：云 GPU（官方栈，推荐）；或 Mac 上 `microduck_local` 过夜跑（~6–8 h，零成本） | 见 9.5 |

**一句话边界：Mac 覆盖了「不需要硬件」的全部原型阶段（Week 0.5 / 4 / 5），
迭代循环是分钟级的；它缺的只有真机硬件。Week 8–9 的算力是**可绕过的**——见 9.5。**

### 9.5 `microduck_local` 与 `microduck_rl` 的差距有多大？（「不能替代」的两个常见理由需修正）

> **本节结论边界（先读）：** 本节只回答**两件事**——(a) 差距是否可枚举、可闭合；
> (b) 算力上 Mac 是否够。**它不主张 `microduck_local` 训出的策略等价于
> `microduck_rl` 的、或已验证能上真机。**「能替代出 sim2real 策略」目前是**未证命题**，
> 见本节末尾。

README 那句 *"What it is NOT for: the final policy you put on the robot"* 常被读成
「技术上不能部署」。**它没有这个意思**，理由有三：

1. 同一页第 42–43 行说导出 ONNX 是 **drop-in compatible**（61/14 contract + normalizer 已 bake）；
2. 它给的理由是「**DR 栈是子集**」+ 建议走 GPU，是对**风险**的建议，不是能力判定；
3. 本仓库自己的 `custom-motor-guide.md` 第 6 节就主张反过来做：
   *「没有 NVIDIA GPU 时，跳过 `microduck_rl`，完全在 `microduck_local` 上完成验证和训练，
   直接导出 ONNX 部署真机。策略质量比 GPU 版低，但足以验证新电机能不能走。」*

**那这个「子集」到底缺什么？从源码逐条比对：**

| microduck_rl velocity 任务的 DR 项 | microduck_rl | microduck_local | 是否缺口 |
|---|---|---|---|
| CoM 随机化（trunk，curriculum ±3→15 mm） | ✅ | ✅ `TRUNK_COM_STAGES` | — |
| Head CoM 随机化（±3→10 mm） | ✅ | ✅ `HEAD_COM_STAGES` | — |
| 质量+惯量 ×[0.95, 1.05] | ✅ | ✅ `MASS_SCALE_RANGE` | — |
| 关节摩擦 scale ×[0.9, 1.1] | ✅ | ✅ `DEFAULT_FRICTION_SCALE_RANGE` | — |
| Armature ×[0.9, 1.1] | ✅ | ✅ `ARMATURE_SCALE_RANGE` | — |
| 速度推挤 ±0.3 m/s | ✅ | ✅ `PUSH_VEL_RANGE` | — |
| **IMU 安装误差 ±6°** | ✅ | ❌ | **缺口 1** |
| **编码器 bias ±0.015 rad** | ✅ | ❌ | **缺口 2** |
| **IMU 延迟 0–1 步** | ✅ | ❌ | **缺口 3** |
| KP / KD / 关节阻尼 / 初始倾角 / symmetry | ❌ 本来就关 | – | 不是缺口 |
| Backlash（齿隙） | ⚠️ **是独立的可选任务**，**不在默认 velocity 任务里** | ❌ 无对应实现 | 只在选它时才是缺口 |

**所以对 base 的 velocity 任务，缺口是 3 个 obs 级 DR 项**——而 README 自己
（第 74–75 行）描述它们是：

> *Not mirrored: IMU misalignment, encoder bias and the 0–1 step IMU delay — obs-level terms,
> **each a small change to `_get_obs`**, left for a measured follow-up.*

即：**缺口是可枚举、可闭合的**，不是架构鸿沟。

#### 关于 backlash（一条常见的误判，需单独澄清）

「backlash 是 `microduck_rl` 独有、`microduck_local` 没有，所以后者不能替代」——
这个说法**对默认训练任务不成立**。源码证据链：

```python
# robot/microduck_constants.py
def get_walk_spec():          return MjSpec.from_file(MICRODUCK_WALK_XML)          # 无 backlash
def get_walk_backlash_spec(): return MjSpec.from_file(MICRODUCK_WALK_BACKLASH_XML) # 有 backlash

# tasks/__init__.py
"Mjlab-Velocity-Flat-MicroDuck"          -> MICRODUCK_WALK_ROBOT_CFG          -> get_walk_spec
"Mjlab-Velocity-Flat-Backlash-MicroDuck" -> MICRODUCK_WALK_BACKLASH_ROBOT_CFG -> get_walk_backlash_spec
```

计划 Week 8–9 跑的是 **`Mjlab-Velocity-Flat-MicroDuck`**（`microduck_rl/README.md:35`），
它用的是 `get_walk_spec`——**没有 backlash**。backlash 是另一个**按需注册的 A/B 变体**
（`microduck_rl/AGENTS.md`：*"so backlash A/B comparisons are unconfounded"*）。

准确表述应该是：**backlash 是 `microduck_rl` 提供的一个可选变体，`microduck_local` 没有对应实现。**
它对换 clone 舵机（未知齿隙）确实有工程价值——但它是「要不要额外做的一项实验」，
**不是「默认 GPU 训练有、Mac 训练没有」的能力差**。

#### 关于「local 是 single-env CPU」

README 第 46 行的 "single-env CPU" 指的是**架构**（CPU MuJoCo，非 GPU Warp 并行），
不是「只跑 1 个 env」——同一份 README 第 137–149 行的表就是 4 → 64 envs，
本次实测也用 32 envs 跑到 ~19,000 steps/s。把它读成「单环境」与 README 自己的数据矛盾。

**这改变了算力结论。** 若接受 `microduck_local` 作为训练器，官方那套 step 预算在 Mac 上是：

| 训练量 | microduck_local @ ~19,000 steps/s | microduck_rl（CPU 模式）@ ~950 steps/s |
|---:|---:|---:|
| 3.93 亿步（4096 envs × 4000 iters） | **~5.7 h** | ~115 h（4.8 天） |
| 5.90 亿步（6000 iters） | **~8.6 h** | ~172 h（7.2 天） |

**也就是说：一次过夜就能跑完，不需要云 GPU。** 这比 Week 0.5 原先设想的
「Mac 只能做小规模 smoke」宽松得多——瓶颈从**算力**变成了**sim2real 保真度**。

**但必须诚实标注两件尚未验证的事：**

1. **没有人验证过 `microduck_local` 训出的 policy 能上真机走。**
   上表是「缺口可闭合」的**推理**，不是实测。真正的证据需要 Week 7 的真机 HIL。
2. **step 数不可直接等价 —— 这是比第 1 条更根本的问题。**
   两个 harness 的 env 设计、n_steps（`train-walk` 51 vs 官方 24）、奖励细节都不同，
   连**单位口径都不一样**（SB3 的 `fps` vs rsl_rl 的 `steps/s`）。
   跑同样的 step 数**不保证**得到同样质量的 policy。
   所以上面那张表证明的**只是「算力够」**，**不是「结果等价」**。

> **因此「替代」的准确表述是：**
> - ✅ 已证：`microduck_local` 在 Mac 上**算力足够**过夜跑完同量级 step 预算（~6–8 h）。
> - ✅ 已证：与 `microduck_rl` base velocity 任务的 DR 差距是**3 个可闭合的 obs 项**。
> - ❌ **未证**：它能产出与 `microduck_rl` 等价、且能上真机的策略。
>   —— 这才是 `microduck_rl` 作为 sim2real recipe 不可替代的部分，也是**唯一真正需要 GPU 路径**的理由。

**修正后的建议：** 原先「Week 8–9 必须云 GPU」应放宽为**两条路**——
(a) 云 GPU 跑官方栈（保真度基准，默认推荐）；(b) Mac 上 `microduck_local` 过夜训练
（零成本，先补齐那 3 个 DR 项以缩小差距）。**建议先用 (b) 做 MVP 验证可行性，
需要最终量产质量时再上 (a)。**

---

## 10. 一句话回答

**MPS 救不了这件事：物理占 98.35% 且 Apple GPU 在这个技术栈里根本用不上
（Warp 无 Metal 后端、mujoco_warp 是 CUDA-only），把 MLP 搬到 MPS 最多快 1.4%。**

**但要分清 No-Go 的范围：**
- ❌ **`microduck_rl` 在这台 Mac 上**：950 steps/s（1.06 核）→ 正式训练 **4.8 天**（按代码默认
  50,000 iters 则是 **60 天**）。**不可行**。
- ✅ **`microduck_local` 在这台 Mac 上**：~19,000 steps/s → 同量级 step 预算 **5.8–8.6 h（过夜）**；
  Week 4/5 全部命令实测通过，一次「改 reward → 训 1M 步 → 渲染看片」的迭代 ≈ **82 秒**。

**所以 Mac 是这个项目的主要开发机，不是凑合用的备胎。** 它缺的只有真机硬件；
Week 8–9 的算力是**可选**的——云 GPU（保真度基准，1.5 h）或 Mac + `microduck_local`
（零成本，过夜）。**唯一未证的是：`local` 训出的策略能否等价上真机**（9.5 节）。
