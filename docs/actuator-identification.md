# 执行器辨识 —— 飞特 HD-1910-C001

> **状态：未开始。** 这是全项目的关键路径 —— 官方 9 个策略和 sim2real 全部建立在
> BAM M6 这个在**实物 XL330** 上台架辨识出来的模型之上。换电机 = 这个模型失效。
>
> **没有这份文档，后面所有训练都是在错误的物理上做的。**

---

## 为什么必须做

| | 官方 | 我们 |
|---|---|---|
| 舵机 | Dynamixel XL330-M288-T | 飞特 HD-1910-C001 |
| 执行器模型 | **BAM M6，台架辨识**（`Rhoban/bam`） | ❌ **不存在，要自己辨识** |
| 官方 9 个策略 | 在这些模型上训出来的 | ❌ 对我们的舵机无效 |
| 能否蒸馏 | — | ❌ **不能** —— 老师本身就是错的 |

**后果**：直接进入"从零训练"区间。已实测：从零 30M 步只会往前扑
（22.5M 时 0.265 m/s 但 100% 摔倒，之后还退化）。

**所以：这一阶段的产出质量，直接决定后面能不能成。**

---

## 方法：官方台架现成

`microduck_rl/scripts/testbench_sim2real.py` 就是那个台架：
一颗舵机 + 已知惯量臂，跑固定目标序列，**sim（以 BAM M6 为起点）vs 实测**对比。

```bash
cd ~/Projects/microduck-build/reference/microduck-lab/microduck_rl

# 1) sim 侧（BAM M6，200 Hz 日志）
uv run python scripts/testbench_sim2real.py --mode sim --onnx policy.onnx --out sim.npz

# 2) 实物侧（插 USB；macOS 不是 /dev/ttyUSB0）
uv run python scripts/testbench_sim2real.py --mode real --onnx policy.onnx --out real.npz \
    --port /dev/cu.usbserial-XXXX --motor-id 1 --baudrate 1000000

# 3) 对比出图 ← 这张图决定项目成败
uv run python scripts/testbench_sim2real.py --compare sim.npz real.npz --out-plot cmp.png

# 4) 转成 BAM log 格式，喂给 bam.plot
uv run python scripts/testbench_sim2real.py --to-bam real.npz real.json
python -m bam.plot --logdir <dir> --actuator hd1910
```

**硬件**：

- 1 颗 HD-1910-C001（先用一颗，不要上整机）
- FE-URT-2 调试板 + 转接线（HD-1910 是 2.0 mm AMP2.0-3P，调试板的口更大，插不上）
- 台架臂：已知长度和质量的摆臂（官方用 `TESTBENCH_ARM_MASS` / 长度 0.1 m）
- 可调电源，**设 7.4 V、限流 2 A**（**不要用满电 8.4 V 的电池做堵转测试** —— 那是电压上限，零余量）
- 示波器（测总线时序和反电动势）

---

## 要辨识的量

对照官方 XL330 的 M6 参数（来源：`microduck_rl` 的 `microduck_constants.py`）。

| # | 参数 | 官方 XL330 | HD-1910 实测 | 状态 |
|---|---|---|---|---|
| 1 | `kp_fw` 固件位置环刚度 | `200` | | `[ ]` |
| 2 | `vin_range` 母线电压范围 | `(6.5, 8.2)` | | `[ ]` |
| 3 | `vin_min` 压降后硬下限 | `6.0` | | `[ ]` |
| 4 | `vin_drop_gain_range` 负载压降增益 | `(0.0, 0.2)` | | `[ ]` |
| 5 | `friction_scale_range` 摩擦缩放 | `(0.9, 1.1)`（本地） | | `[ ]` |
| 6 | `delay_min_lag` / `delay_max_lag` 指令延迟 | `3` / `6` 控制步 | | `[ ]` |
| 7 | 堵转力矩 vs 电压曲线 | 0.52–0.60 N·m | | `[ ]` |
| 8 | **额定**负载力矩 | — | | `[ ]` |
| 9 | 齿轮箱摩擦（库仑 + Stribeck） | 已辨识 | | `[ ]` |
| 10 | 回差 backlash | 建模 ±1.0° | | `[ ]` |
| 11 | 减速比 | `288.4:1` | **1/320**（待核） | `[ ]` |
| 12 | 电流限幅 | `1.75 A` | | `[ ]` |
| 13 | 空载转速 | ~103 RPM @5V | | `[ ]` |
| 14 | 静态电流 | — | | `[ ]` |

> ⚠️ **第 7 和第 8 项差 4 倍，不要混。** 官方给的 1.47 N·m 是**堵转**；
> 社区解读的额定负载是 **0.363 N·m**。训练时的力矩模型用哪个是两个完全不同的机器人。
>
> ⚠️ **第 11 项减速比不同**（1/320 vs 288.4:1）—— BAM 辨识里减速比是关键项，
> 它会改变力矩、回差和惯量的换算。

---

## 验收判据（Gate 2）

`[ ]` **同一份 ONNX 在 sim 和实物上的关节轨迹对得上**（台架图上两条线叠得住）

具体到数字：

| 指标 | 目标 | 现状 |
|---|---|---|
| 位置轨迹 RMSE（稳态段） | ≤ ？ rad | 待测 |
| 阶跃响应的上升时间误差 | ≤ ？ % | 待测 |
| 力矩估计误差（堵转保持） | ≤ ？ % | 待测 |
| 复现官方 M6 对 XL330 的拟合质量 | 同量级 | 待测 |

> 官方数据点：`distill` 的克隆达到 `mse 0.00017 rad²`，且 **mse < 0.00011 rad² 时摔倒直接停止**。
> 这可以作为"辨识够不够好"的参照量级。

---

## 记录（每次实验追加）

| 日期 | 做了什么 | 结果 | 文件 |
|---|---|---|---|
| | | | |

**文件放** `docs/bench/`：`sim-<日期>.npz`、`real-<日期>.npz`、`cmp-<日期>.png`。

---

## 已知的坑（来自社区复刻记录）

1. **2.0 mm vs 2.5 mm**：HD-1910 原装线是 AMP2.0-3P，调试板插不上 → 剪一根舵机线飞线，或买转接线
2. **脚序与 Dynamixel 完全相反**：飞特 `1=Signal / 2=Vcc / 3=GND`，Dynamixel `1=GND / 2=Vcc / 3=Signal`。
   **中间那根一定是 Vcc；S 和 G 接反不会烧，V 接错才会烧**
3. **调试板供电**：拨动开关在 USB 侧时，又往 V1 灌外接电压 = **把 7.4 V 反灌进电脑 USB 口**。先量 G–V1
4. **出厂 ID 全是 1**：15 颗一起接上去全都应答 → **设 ID 时一次只接一颗**，改完贴标签
5. **过流/过压保护出厂关闭** → 装机前用 FD 调试软件打开
6. **别拿 HL-2915 当参考**：那是 9–14 V 舵机，2S 带不动，且脚序又跟 HD-1910 相反
