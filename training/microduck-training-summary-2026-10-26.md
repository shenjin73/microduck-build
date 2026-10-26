# Microduck 训练实验总结与迁移说明

> 日期：2026-10-26
> 工作区根目录：`./microduck-build`
> 项目目录：`./microduck-build/reference/microduck-lab`
> 隐私说明：本文仅使用相对路径和占位符，不包含本机用户 ID、用户名或个人绝对路径。

## 1. 今日工作概览

### 1.1 项目启动与训练界面

- 启动并验证了 `duck-lab` 后端与 `duck-viewer` 前端。
- 明确了三个页面：
  - `/`：普通 Lab、Teach 动作训练。
  - `/sim`：房间、足球等世界模拟。
  - `/train`：查看已有 brain 训练曲线。
- 通过 Teach 面板启动训练，并确认训练鸭子真实出现在 WebSocket 舞台帧中。

### 1.2 单腿向前跳实验

新增 `one_leg_hop` 行为，目标包括：

- 左腿支撑。
- 连续向前跳。
- 允许双脚落地。
- 使用周期信号区分蓄力、腾空和落地。
- 增加真实腾空、向前移动、右脚抬起、软着陆、防旋转和防侧移奖励。
- 使用 XML 到 BAM 的物理课程。

结果：失败。

策略主要学会了踏步、转圈和扩大绕圈半径，没有形成可靠腾空。随着起跳辅助减弱，`get_air` 得分接近零。

### 1.3 两脚交替跳实验

新增 `alternate_hop`：

```text
左脚支撑 → 腾空 → 右脚支撑 → 腾空 → 左脚支撑
```

同时加入：

- 下蹲蓄力奖励。
- 向上蹬腿奖励。
- 起跳辅助逐步撤除。
- 转向和横向移动惩罚。
- 只有最近真实腾空后，才能获得完整前进奖励。

结果：失败。

辅助存在时能出现少量腾空；辅助减弱后，策略退化成平移、原地晃动和转圈。

### 1.4 双脚同时跳实验

新增 `bunny_hop`：

```text
双脚下蹲 → 双腿同时伸展 → 双脚腾空 → 双脚落地缓冲
```

关键奖励：

- `bunny_cycle`：双脚蓄力、腾空、双脚落地。
- `get_air`：双脚真实离地。
- `spring_height`：明显下蹲后重新伸展。
- `push_up`：起跳阶段产生向上速度。
- `forward_hop`：真实腾空且保持直行后才支付完整前进奖励。
- `no_yaw` / `no_sideways`：限制旋转和侧滑。

结果：失败，并确认存在奖励漏洞。

| 阶段 | 起跳辅助 | 实际腾空 | 现象 |
|---|---:|---:|---|
| Stage 1 | 强 | 约 12% | 能看到部分跳跃 |
| Stage 2 | 弱 | 约 2% | 跳跃基本消失 |
| Stage 3 | 无 | 约 1–2% | 双脚长期着地、头部下垂 |

最终策略约 98% 时间双脚着地，但训练奖励继续上升。策略通过“不跳、站稳、低头配重”获得更高总收益。

头部奖励也明显失效：`head_up` 从第一阶段约 `0.28` 降到最终约 `0.012`。低头可以移动重心，稳定双脚站立，因此成为奖励漏洞。

## 2. 跳跃物理可行性研究

### 2.1 参数扫描脚本

新增：

```text
reference/microduck-lab/microduck_local/scripts/probe_bunny_jump.py
```

扫描内容：

- 下蹲深度和时间。
- 蹬腿时间。
- 关节伸展过冲。
- 头部摆动。
- 腾空保持时间。
- 落地缓冲深度。
- XML 与 BAM 执行器。
- 双脚离地高度、腾空时间、垂直速度、倾斜角和稳定落地。

结果：BAM 舵机能够让双脚离地约 `2.3～2.5 cm`，腾空约 `0.04～0.14 s`，但简单开环轨迹无法稳定落地。

结果文件：

```text
reference/microduck-lab/microduck_local/runs/bunny-feasibility.jsonl
reference/microduck-lab/microduck_local/runs/bunny-feasibility-head-scan.jsonl
```

### 2.2 全身轨迹优化器

新增：

```text
reference/microduck-lab/microduck_local/scripts/optimize_bunny_jump.py
```

使用无额外依赖的 CEM 优化器搜索四个全身关键姿态：

```text
下蹲 → 蹬腿 → 空中姿态 → 落地缓冲
```

稳健搜索规模：

```text
25 代 × 96 个候选 × 3 个训练 seed ≈ 7200 次物理跳跃
```

候选通常能够离地，但对初始扰动极其敏感。5 个验证 seed 中没有候选全部稳定落地，因此优化器没有生成可用的 `bunny-hop-once.json`，避免把失败动作交给模仿训练。

结果文件：

```text
reference/microduck-lab/microduck_local/runs/bunny-trajectory-search.json
reference/microduck-lab/microduck_local/runs/bunny-trajectory-search-robust.json
```

结论：当前瓶颈不是纯粹的舵机起跳力量，而是双脚离地后的俯仰控制和跨 seed 稳定落地。

## 3. 奔跑实验

### 3.1 稳定蒸馏模型

先蒸馏官方 `alpha_walking`，得到：

```text
reference/microduck-lab/microduck_local/runs/fast-run-clone/
```

评测结果：

| 命令速度 | 实际速度 | 回合长度 | 摔倒 |
|---:|---:|---:|---:|
| 0.4 m/s | 0.201 m/s | 1000 步 | 0 |
| 0.9 m/s | 0.339 m/s | 1000 步 | 0 |

可用模型：

```text
reference/microduck-lab/microduck_local/runs/fast-run-clone/policy.onnx
```

### 3.2 PPO 奔跑微调

从稳定蒸馏模型启动：

```text
teach-run-4a13df
```

原计划 20M 步，在约 10.8M 步时停止，因为策略已经退化成原地站立。

对比：

| 策略 | 实际速度（命令 0.4） | 双脚同时着地 | 摔倒 |
|---|---:|---:|---:|
| `fast-run-clone` | 0.201 m/s | 约 8% | 0 |
| `teach-run-4a13df` | 0.000 m/s | 约 98% | 0 |

训练过程中：

```text
keep_pace：约 0.96 → 0.35～0.62
air_time：约 1.11 → 0.00
总奖励：约 9109 → 约 7797
```

策略放弃速度奖励，改为持续领取直立、头部、姿态和转向奖励。长时间 PPO 覆盖了原有的优秀步态。

结论：

- `fast-run-clone` 是当前可用成果。
- `teach-run-4a13df` 是失败实验，不应部署。
- 对高质量 teacher 继续长时间 PPO 微调会造成灾难性遗忘。
- 若继续追求速度，应每 100k～150k 步保存独立 checkpoint，并用确定性 ONNX 的真实地面速度进行早停和选择。

## 4. 源代码修改

当前修改尚未提交 Git。

### 4.1 新文件

```text
reference/microduck-lab/microduck_local/src/microduck_local/behaviors/hop.py
reference/microduck-lab/microduck_local/scripts/probe_bunny_jump.py
reference/microduck-lab/microduck_local/scripts/optimize_bunny_jump.py
```

### 4.2 修改文件

```text
reference/microduck-lab/microduck_local/src/microduck_local/behaviors/__init__.py
reference/microduck-lab/microduck_local/src/microduck_local/behaviors/core.py
reference/microduck-lab/microduck_local/src/microduck_local/behaviors/env.py
reference/microduck-lab/microduck_local/src/microduck_local/train_behavior.py
reference/microduck-lab/microduck_local/tests/test_behaviors.py
reference/microduck-lab/microduck_local/tests/test_teach_robots.py
```

框架修改包括：

- 为 `Behavior` 增加 `pre_step_fn` 物理课程钩子。
- `BehaviorEnv.step()` 在控制步前调用行为的物理课程钩子。
- 允许课程阶段通过 `MICRODUCK_ACTUATOR` 覆盖默认执行器。
- 注册单腿跳、交替跳、双脚跳三个实验行为。
- 增加行为匹配、奖励符号、课程、时序和辅助撤除测试。

专项测试结果：

```text
153 passed
```

这些跳跃行为应视为研究失败记录和调试工具，不是生产可用策略。

## 5. 如何迁移到另一台电脑

本次代码已随 `microduck-build` 仓库提交到以下目录：

```text
training/microduck-lab-experiment-code/
```

由于主仓库明确忽略 `reference/`，另一台电脑应先取得上游 `microduck-lab`，再覆盖代码包：

```bash
git clone <microduck-build-repository-url> microduck-build
cd microduck-build
mkdir -p reference
git clone https://github.com/jonathanhawkins/microduck-lab reference/microduck-lab

rsync -av \
  training/microduck-lab-experiment-code/ \
  reference/microduck-lab/

cd reference/microduck-lab
./scripts/setup.sh
cd microduck_local
uv run --with pytest pytest -q tests/test_behaviors.py tests/test_teach_robots.py
```

详细文件清单和注意事项见：

```text
training/microduck-lab-experiment-code/README.md
```

建议将“源代码”和“训练产物”分开迁移。

### 5.1 推荐：Git 分支

在当前电脑，从工作区根目录执行：

```bash
cd ./microduck-build/reference/microduck-lab

git switch -c experiment/hop-and-run

git add \
  microduck_local/src/microduck_local/behaviors/__init__.py \
  microduck_local/src/microduck_local/behaviors/core.py \
  microduck_local/src/microduck_local/behaviors/env.py \
  microduck_local/src/microduck_local/behaviors/hop.py \
  microduck_local/src/microduck_local/train_behavior.py \
  microduck_local/scripts/probe_bunny_jump.py \
  microduck_local/scripts/optimize_bunny_jump.py \
  microduck_local/tests/test_behaviors.py \
  microduck_local/tests/test_teach_robots.py

git commit -m "Add hop experiments and jump feasibility tools"
git push -u origin experiment/hop-and-run
```

在另一台电脑：

```bash
git clone <repository-url> microduck-build
cd microduck-build/reference/microduck-lab
git fetch origin
git switch experiment/hop-and-run
./scripts/setup.sh
```

如果另一台电脑已有工作区：

```bash
cd ./microduck-build/reference/microduck-lab
git fetch origin
git switch experiment/hop-and-run
cd microduck_local
uv sync
```

验证：

```bash
uv run --with pytest pytest -q \
  tests/test_behaviors.py \
  tests/test_teach_robots.py
```

### 5.2 无远程 Git：打包源代码

从 `./microduck-build` 执行：

```bash
tar -czf training/microduck-experiment-code.tar.gz \
  reference/microduck-lab/microduck_local/src/microduck_local/behaviors/__init__.py \
  reference/microduck-lab/microduck_local/src/microduck_local/behaviors/core.py \
  reference/microduck-lab/microduck_local/src/microduck_local/behaviors/env.py \
  reference/microduck-lab/microduck_local/src/microduck_local/behaviors/hop.py \
  reference/microduck-lab/microduck_local/src/microduck_local/train_behavior.py \
  reference/microduck-lab/microduck_local/scripts/probe_bunny_jump.py \
  reference/microduck-lab/microduck_local/scripts/optimize_bunny_jump.py \
  reference/microduck-lab/microduck_local/tests/test_behaviors.py \
  reference/microduck-lab/microduck_local/tests/test_teach_robots.py
```

复制压缩包到另一台电脑的 `microduck-build` 目录后：

```bash
tar -xzf microduck-experiment-code.tar.gz
cd reference/microduck-lab/microduck_local
uv sync
```

该方式会覆盖同名文件，要求两台电脑使用相同基础版本。

## 6. 如何迁移训练模型

### 6.1 只迁移可用 ONNX

推荐只复制：

```text
reference/microduck-lab/microduck_local/runs/fast-run-clone/policy.onnx
```

示例使用隐私占位符：

```bash
scp reference/microduck-lab/microduck_local/runs/fast-run-clone/policy.onnx \
  <remote-user>@<remote-host>:<remote-workspace>/reference/microduck-lab/microduck_local/runs/fast-run-clone/
```

`policy.onnx` 已包含 observation normalizer，可直接用于部署或 Lab 观看。

### 6.2 需要继续训练

复制整个目录：

```bash
cd ./microduck-build
tar -czf training/fast-run-clone.tar.gz \
  -C reference/microduck-lab/microduck_local runs/fast-run-clone
```

另一台电脑：

```bash
cd ./microduck-build/reference/microduck-lab/microduck_local
tar -xzf <path-to>/fast-run-clone.tar.gz
```

继续训练需要：

```text
model.zip
vecnormalize.pkl
run.json
```

部署和观看使用：

```text
policy.onnx
```

### 6.3 不建议迁移的失败策略

除非用于研究对比，不建议迁移：

```text
teach-one_leg_hop-*
teach-alternate_hop-*
teach-bunny_hop-*
teach-run-4a13df
```

## 7. 在另一台电脑上观看稳定模型

后端：

```bash
cd ./microduck-build/reference/microduck-lab/microduck_local
uv run duck-lab runs/fast-run-clone/policy.onnx
```

前端：

```bash
cd ./microduck-build/reference/microduck-lab/duck-viewer
npm run dev
```

打开：

```text
http://localhost:63317/
```

## 8. 最终建议

- 保留 `fast-run-clone` 作为当前稳定基线。
- 不部署任何跳跃实验策略。
- 不部署 `teach-run-4a13df`。
- 后续速度实验必须保存独立 checkpoint，并根据确定性 ONNX 的真实速度和摔倒率选择，不再用最终训练步作为默认结果。
- 若继续研究跳跃，应先解决跨 seed 稳定落地，再启动任何 PPO 模仿训练。
