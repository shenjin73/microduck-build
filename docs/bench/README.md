# 台架数据

阶段 2（执行器辨识）的原始数据与对比图。命名约定：

| 文件 | 是什么 |
|---|---|
| `sim-<日期>.npz` | MuJoCo 侧 rollout（BAM 模型） |
| `real-<日期>.npz` | 实物侧 rollout（`--port /dev/cu.usbserial-*`） |
| `cmp-<日期>.png` | `--compare` 出的 sim-vs-real 对比图 ← **这张图是 Gate 2 的判据** |
| `real-<日期>.json` | `--to-bam` 转出的 BAM log 格式 |

**每次实验都留档**，并在
[`../actuator-identification.md`](../actuator-identification.md) 的记录表里追加一行。

日期前缀用 `YYYY-MM-DD`，同一实验的多个版本加后缀 `-v2`、`-v3`。

> ⚠️ 这个目录**会变大**（每次 rollout 的完整轨迹）。如果以后 `microduck-build` 加了 git，
> 这一条要进 `.gitignore` —— 原始数据不进版本库，只进图和结论。
