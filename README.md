# microduck-build

复刻 Microduck，用**第三方舵机**（飞特 HD-1910-C001），并重新训练从站立到走路以及更多动作的策略。

这个目录是**我们自己的项目根** —— 不是任何一个上游仓库。三个上游 checkout 放在
`reference/` 下（原因见 [`docs/decisions.md`](docs/decisions.md)）。

## 目录

```
microduck-build/
├── ROADMAP.md                    路线图与执行计划 ← 从这里开始
├── ISSUE-DRAFT.md                待提交给 reference/microduck-lab 的 bug 报告
├── docs/
│   ├── decisions.md              决策日志：每个选择的理由和置信度
│   ├── actuator-identification.md 阶段 2 的台架记录 ← 全项目最关键
│   └── bench/                    台架数据：sim-vs-real 的 npz 与对比图
├── reference/                    上游参考 checkout（本地副本，gitignore）
│   ├── microduck-lab/            社区训练 harness + 其内部两份上游 checkout
│   ├── microduck-replica/        社区复刻资料：CAD / BOM / 电控 / 踩坑
│   └── elec_RPI_Robot_HAT/       Pollen 官方 RPI HAT（IMU / Dynamixel / audio）
└── runs/                         训练产物
```

## 上游依赖（`reference/` 下，不纳入版本管理）

| 路径 | 是什么 | 版本 |
|---|---|---|
| `~/Projects/microduck` | 官方运行时 + 文档（**会话工作目录**） | 未钉 |
| `~/Projects/microduck-build/reference/microduck-lab` | 社区训练 harness（CPU MuJoCo + SB3） | `3f788f3` |
| `~/Projects/microduck-build/reference/microduck-lab/microduck_rl` | 官方训练栈（mjlab + MuJoCo Warp） | `badc4e7`（钉） |
| `~/Projects/microduck-build/reference/microduck-lab/microduck` | 官方运行时的第二份 checkout | `2c61dcc`（钉） |
| `~/Projects/microduck-build/reference/microduck-replica` | 社区复刻资料：CAD / BOM / 电控 / 踩坑 | 待克隆 |
| `~/Projects/microduck-build/reference/elec_RPI_Robot_HAT` | Pollen 官方 RPI HAT 原理图 / Gerber / BOM | `88d51fa` |

> ⚠️ **不要拆开 `microduck-lab/` 内部那四份并排的 checkout。** `microduck_local` 按
> **兄弟目录**找模型（`../microduck_rl`），是硬编码的相对路径 —— 把 `microduck_local/`
> 或 `microduck_rl/` 单独挪走会直接破坏运行。整个 `microduck-lab/` 作为整体移动是安全的。

## 当前状态

| 阶段 | 状态 |
|---|---|
| 0 · 选型决策 | ✅ 已定：飞特 HD-1910-C001（含一条未核实项，见 decisions） |
| 1 · 通信打通 | ⬜ 未开始 |
| 2 · 台架辨识 | ⬜ 未开始 ← **关键路径** |
| 3 · 机械与模型对齐 | ⬜ 未开始 |
| 4 · 分阶段训练 | ⬜ 未开始 |
| 5 · sim2real 落地 | ⬜ 未开始 |
