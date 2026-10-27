# Microduck 启动训练操作说明

## 1. 启动后端

本机目前没有可加载的 ONNX 模型，因此训练前使用 `--world playroom` 启动 Lab：

```bash
cd /Users/jin/Projects/microduck-build/reference/microduck-lab/microduck_local
uv run duck-lab --world playroom
```

保持这个终端运行。不要只执行 `uv run duck-lab`，否则在没有模型时会提示：

```text
no ducks — pass run dirs or .onnx paths (or --world <scenario>)
```

## 2. 启动前端

另开一个终端：

```bash
cd /Users/jin/Projects/microduck-build/reference/microduck-lab/duck-viewer
npm run dev
```

打开：

```text
http://localhost:63317/
```

## 3. 在网页中开始训练

1. 进入首页的 **🎓 Teach** 面板。
2. 选择要训练的行为。
3. 点击开始训练。
4. 训练启动后，Lab 会创建训练鸭子，并显示实时动作和训练进度。

本次新增的实验行为：

| 行为 ID | 动作 |
|---|---|
| `one_leg_hop` | 单腿向前跳 |
| `alternate_hop` | 两脚交替跳 |
| `bunny_hop` | 双脚同时跳 |
| `crouch_walk_cycle` | 下蹲 5 秒 → 站起 1 秒 → 静止 2 秒 → 直行 5 秒 → 停步 1 秒 → 静止 2 秒，循环执行 |
| `crouch_stand_cycle` | 下蹲 5 秒 → 停站 2 秒 → 直行 5 秒 → 停站 2 秒，循环执行，全程抬头 |

建议从 `bunny_hop` 开始。三个跳跃行为都是研究实验，已有实验均未得到可部署的稳定跳跃策略。

`crouch_stand_cycle` 的完整周期为 14 秒，训练回合包含两个周期。下蹲目标比完整站立低 5.5 cm；站好后先停稳 2 秒再直行，走完 5 秒后先停站 2 秒再下蹲。行走使用 `alpha_walking` 蒸馏起点，命令速度为 0.4 m/s，通过转向命令修正方向、保持直线，并加入抬脚和防滑奖励。全程要求头部平视，每 15 万步保存独立 checkpoint。

为解决只站不走、从不下蹲的问题，训练采用三阶段课程：第一阶段 85% 回合从真实深蹲姿态开始并使用 XML 执行器；第二阶段改用 BAM 执行器并将深蹲起步降到 50%；最后阶段全部从站立开始。各阶段奖励保持不变，只撤除物理和起始姿态辅助。

`crouch_walk_cycle` 的完整周期为 16 秒，训练回合包含两个周期。下蹲目标比完整站立低 5.5 cm；站起后和行走结束后各有 2 秒静止停顿。行走使用 `alpha_walking` 蒸馏模型作为训练起点，命令速度为 0.4 m/s，并通过转向命令修正方向、保持直行。训练时每 15 万步保存独立 checkpoint，防止只保留退化的最终模型。

## 4. 使用命令行训练（可选）

不使用网页时，可以直接运行：

```bash
cd /Users/jin/Projects/microduck-build/reference/microduck-lab/microduck_local
uv run train-behavior bunny_hop
```

其他行为对应：

```bash
uv run train-behavior one_leg_hop
uv run train-behavior alternate_hop
uv run train-behavior crouch_walk_cycle
uv run train-behavior crouch_stand_cycle
```

命令行训练不会自动在网页中展示训练过程，因此日常使用推荐 Teach 面板。

## 5. 训练结果与观看模型

训练结果保存在：

```text
reference/microduck-lab/microduck_local/runs/
```

训练完成后，用生成的模型启动 Lab：

```bash
cd /Users/jin/Projects/microduck-build/reference/microduck-lab/microduck_local
uv run duck-lab runs/<训练目录名>/policy.onnx
```

`fast-run-clone/policy.onnx` 等既有模型没有包含在源代码迁移包中，需要单独迁移后才能使用。

## 6. 直接观看组合模型

GitHub 已附带最终模型：`training/models/crouch-stand-walk-composite/`。复制到本机运行目录：

```bash
cd /Users/jin/Projects/microduck-build
mkdir -p reference/microduck-lab/microduck_local/runs/crouch-stand-walk-composite
cp training/models/crouch-stand-walk-composite/* \
  reference/microduck-lab/microduck_local/runs/crouch-stand-walk-composite/
```

`runs/crouch-stand-walk-composite/policy.onnx` 是按阶段切换的组合 ONNX，不是重新 PPO 训练出来的单一策略：

- 下蹲和站立：`head-forward-eval-v2/001056768.onnx`，经过头部朝前奖励微调
- 起步前 2 秒：`alpha_walking`
- 后 3 秒直行：专用 `straight_walk` 的 `000507904` checkpoint

组合时会将专用直行模型的两个周期时钟输入置零，避免它收到训练时没有的观测。蹲站策略通过训练学会头部朝前，没有强制截断动作；头部仍允许正常左右摇晃。多个验证 seed 均完成完整周期，包括此前摔倒的 seed 1。

重新生成：

```bash
cd /Users/jin/Projects/microduck-build/reference/microduck-lab/microduck_local
uv run python -m microduck_local.compose_policy \
  runs/head-forward-eval-v2/001056768.onnx \
  runs/straight-eval/000507904.onnx \
  runs/crouch-stand-walk-composite/policy.onnx \
  --transition-walker ../microduck/policies/alpha_walking.onnx \
  --transition-seconds 2.0
```

观看组合模型：

```bash
uv run duck-lab runs/crouch-stand-walk-composite/policy.onnx
```

如果在已有 Lab 上重启，也可以从仓库根目录执行：

```bash
bash .claude/skills/restart-servers/restart.sh --backend-only --fresh \
  runs/crouch-stand-walk-composite/policy.onnx
```
