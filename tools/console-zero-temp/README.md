# 控制台 ZERO 温度瓦片修复（R17 V167）

## 问题

中控「硬件观测台」总览页的 **ZERO 温度** 一直显示 `—` + 「等待主板温度回读」，
即使板子在线、SSH 已连接。同一页的「控制循环 / 关节反馈 / 舵机总线电压 / 最高舵机温度」
是空的属于**另一回事**（robotd 卡在第 2/4 步，未接舵机），四个瓦片要接了舵机才可能亮。

## 根因

`system` 通道（`cpu_temp_c` / 内存 / CPU / uptime / hostname 都在里面）在随包构建里
**没有任何产出方**：

| 事实 | 位置 |
|---|---|
| `cpu_temp_c` 与 `channel:"system"` 全仓唯一产出方 | `agent.py:221`、`agent.py:245` |
| 唯一会注入 `agent.py` 到板子的函数 | `console.py:66` 的 `ssh_loop` |
| `ssh_loop` 的调用点 | **0 个**（死代码） |
| `console.py:352` 的 `import agent` | 在非 dashboard 分支，且 `run()` 在 `if __name__ == "__main__":` 内 → 空操作 |
| `start.command` / `start.cmd` 启动的模式 | `--dashboard --feetech` → `mode = service` → 只跑 `raw_loop` |

所以 `raw_loop`（只转发 `/run/robotd.sock`、`/run/tofd/tof.sock`）永远不会发出 `system`，
网页 `static/app.js:79` 的 `sy ? s.system.cpu_temp_c : '—'` 永远是 `—`。
会话日志里「采集 SSH」（agent 注入成功）计数为 **0**，与之吻合。

## 修复

在 `raw_telemetry.py` 增加 `system_loop()`，并挂到 `raw_loop()` 里成为 `system` 通道的产出方：

- 一条**常驻** SSH 会话执行固定的只读 shell 循环（`SYSTEM_PERIOD = 3` 秒一轮），
  读取板子上的 `/proc/uptime`、`/proc/meminfo`、`/proc/stat`、
  `/sys/class/thermal/thermal_zone*/temp`、`/run/robotd/identity.json`；
- 输出 `key=value` 分块、`END` 结尾；`system_sample()` 解析成
  `agent.py` 原有的同名契约字段（`hostname`/`cpu_temp_c`/`memory_*`/`cpu_percent`/`uptime_s`/`identities.robotd`），
  再 `emit({'channel':'system','data':…})` 进 store；
- **连接只在失败后才重建**，并且指数退避（2s→6s 封顶）。板子 sshd 在未认证连接堆积时
  会丢新连接（`MaxStartups`），因此这里刻意不引入重连抖动；
- 失败时只在这一个通道上报错（`error_source: 'zero'`），不会把整条连接标成异常；
- 遵守 `connection_pause`（安装交接时暂停），`stop` 后由 `raw_loop` 的 `finally` 收尾。

## 文件

| 文件 | 用途 |
|---|---|
| `system-channel.patch` | 相对 R17 V167 原始 `raw_telemetry.py` 的 unified diff（`patch -p1` 可用） |
| `raw_telemetry.py.r17v167.orig` | 原始文件备份（回滚用） |
| `raw_telemetry.py.patched` | 打补丁后的完整文件（重新解压 ZIP 后可直接覆盖） |
| `test_system_loop.py` | 离线验证脚本（不需要真机） |

## 安装

控制台目录内执行：

```bash
cd reference/Microduck-kissqy/release-assets/Microduck-Console-R17-V167
patch -p1 < ../../../tools/console-zero-temp/system-channel.patch   # 或直接覆盖 raw_telemetry.py
```

`reference/` 是第三方参考 checkout（已在 `.gitignore`），且该目录是从 Release ZIP 解压的
未跟踪文件，因此这个改动不会进入本项目版本库；**重新解压 ZIP 会丢失补丁**，用上表任一文件恢复。

## 回滚

```bash
cp tools/console-zero-temp/raw_telemetry.py.r17v167.orig \
   reference/Microduck-kissqy/release-assets/Microduck-Console-R17-V167/raw_telemetry.py
```

## 验证记录（2026-10-14）

1. `python3 -m py_compile raw_telemetry.py` 通过。
2. `test_system_loop.py`：用本地假板子跑通「ssh 进程 → 分帧 → 解析 → emit」全链路，
   20 项断言全过（含毫摄氏度换算、cpu_percent 需要两个采样点、坏 base64/NaN/缺 `/proc` 的降级）。
3. 补丁可干净套用到原始文件，套用结果与 `raw_telemetry.py.patched` 逐字节一致。
4. **回归对照**：作者自带 `verification/test_*.py` 在打补丁前后各跑一遍，结果完全一致
   （6 PASS / 5 FAIL；5 个 FAIL 是包内缺少 `test_upgrade_units` 等辅助模块导致的既有问题）。
5. **实机确认（2026-10-14 21:45，Radxa Zero 3W @ 10.181.1.27）**：重启中控后
   ZERO 温度瓦片出数 **52.5 °C**、说明文字变为「ZERO 主板 CPU 实测」；
   新会话日志 `logs/system-20261014-214439-29f064.log` 中 `Zero 系统信息` 失败条目 **0** 条，
   那条常驻 SSH 一次就建立成功；同一日志里旧会话的 `原始遥测` SSH 重置风暴也不再出现。

## 已知边界

- 不修 robotd 第 2/4 步失败（未接舵机时本来就该失败）。
- `system` 通道里的摄像头统计（`camera` / `camera_capture`）未纳入，只补温度与主机指标。
- service 模式下「运行标识」一行由 `s.bus.build` 覆盖显示，与本补丁的 `identities.robotd` 无关。
