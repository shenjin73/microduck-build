# Microduck Lab 实验代码包

本目录保存 2026-10-26 训练实验涉及的源代码。`reference/` 在主仓库中被忽略，因此这些文件以可复制代码包的形式提交到 GitHub。

详细实验结论见：

```text
../microduck-training-summary-2026-10-26.md
```

## 包含内容

- `behaviors/hop.py`：单腿跳、交替跳、双脚跳实验行为。
- `behaviors/routines.py`：深蹲/站立循环、专用直行及分阶段课程。
- `behaviors/core.py` / `env.py`：课程钩子、教师蒸馏和 checkpoint 配置。
- `train_behavior.py`：行为默认蒸馏、checkpoint 和课程执行器覆盖。
- `compose_policy.py`：按阶段组合蹲站、起步过渡和直行 ONNX。
- `compose_lie_stand.py`：组合趴卧策略与 `alpha_stand`，形成躺下/站立循环。
- `probe_bunny_jump.py`：跳跃物理可行性扫描。
- `optimize_bunny_jump.py`：无额外依赖的 CEM 全身轨迹优化器。
- 行为、Teach 建议和组合模型测试。

跳跃策略均为研究失败记录，不应直接部署。可用组合模型位于：

```text
training/models/crouch-stand-walk-composite/
training/models/lie-stand-cycle/
```

每个模型目录中的 `policy.onnx` 和 `behavior.json` 必须一起复制；缺少 sidecar 会导致 Lab 使用错误的环境、时钟和跌倒条件。

## 导入另一台电脑

先克隆工作区仓库并准备参考项目：

```bash
git clone <microduck-build-repository-url> microduck-build
cd microduck-build
mkdir -p reference

git clone https://github.com/jonathanhawkins/microduck-lab \
  reference/microduck-lab
```

将代码包覆盖到参考 checkout：

```bash
rsync -av \
  training/microduck-lab-experiment-code/ \
  reference/microduck-lab/
```

安装并验证：

```bash
cd reference/microduck-lab
./scripts/setup.sh

cd microduck_local
uv run --with pytest pytest -q \
  tests/test_behaviors.py \
  tests/test_teach_robots.py \
  tests/test_compose_policy.py
```

当前上游版本的预期专项测试结果：

```text
206 passed
```

## 注意

- 不要复制 `.venv/`、`node_modules/` 或本机绝对路径。
- 若目标电脑的 `microduck-lab` 版本不同，覆盖前先提交或备份目标电脑的本地修改。
- `runs/` 训练产物与 ONNX 模型需按总结文档第 6 节单独迁移。
