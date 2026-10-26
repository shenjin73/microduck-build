# Microduck Lab 实验代码包

本目录保存 2026-10-26 训练实验涉及的源代码。`reference/` 在主仓库中被忽略，因此这些文件以可复制代码包的形式提交到 GitHub。

详细实验结论见：

```text
../microduck-training-summary-2026-10-26.md
```

## 包含内容

- `behaviors/hop.py`：单腿跳、交替跳、双脚跳实验行为。
- `behaviors/core.py` / `env.py`：`pre_step_fn` 课程物理钩子。
- `train_behavior.py`：允许课程阶段覆盖 XML/BAM 执行器。
- `probe_bunny_jump.py`：跳跃物理可行性扫描。
- `optimize_bunny_jump.py`：无额外依赖的 CEM 全身轨迹优化器。
- 行为与 Teach 建议测试。

这些跳跃策略均为研究失败记录，不应直接部署。当前稳定成果是本地训练产物 `runs/fast-run-clone/policy.onnx`，模型文件未包含在本代码包内。

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
  tests/test_teach_robots.py
```

预期专项测试结果：

```text
153 passed
```

## 注意

- 不要复制 `.venv/`、`node_modules/` 或本机绝对路径。
- 若目标电脑的 `microduck-lab` 版本不同，覆盖前先提交或备份目标电脑的本地修改。
- `runs/` 训练产物与 ONNX 模型需按总结文档第 6 节单独迁移。
