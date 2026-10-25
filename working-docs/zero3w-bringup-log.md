# Radxa Zero 3W 主板 bring-up 日志与选型结论

日期：2026-09-20 起（最后更新 2026-10-14）
状态：**板子在线，跑 kissqy 整合镜像（Public Image R1），中控已连上并修好 ZERO 温度通道；
舵机未接 → robotd 卡在第 2/4 步。原 Armbian 基线所在 TF 卡已被覆盖（§2 → §6）。**

> 快速导航：现状与待办看 **§3**；今天做的三件事看 **§6**（重刷 / 控制台修复 / 2 个坑）。

## 0. 选型结论（已定案）

主板定为 **Radxa Zero 3W（RK3566）**——即官方 MicroDuck 原板，runtime 的全部
board-specific 工作（UART/NPU overlay、MPP、GStreamer、rkaiq、systemd units）零适配复用。

- **未来加图像/声音识别的主板要求**（调研结论）：
  - 算力必须与 50 Hz 控制回路隔离：重活推给 NPU/VPU/RGA，`robotd` 用 CPU 亲和性独占核；
  - 内存带宽/容量比算力先触顶：官方量产机 1GB 可跑，开发机建议 4GB 余量；
  - 散热是实测瓶颈（media-bringup 记录过 97°C 降频事件），结构阶段就要考虑。
- **轻量感知（检测 2–5 Hz + 关键词唤醒）RK3566 够用**（yolo11n@320 实测 p50 25.7ms）；
  语义级视觉留给未来 RK3588S/RK3576 档位（RKNN 生态内平移，成本=重新 provisioning +
  模型按 target_platform 重转，不是重写）。
- **命名陷阱备忘**：
  - `Radxa Zero 3W` = RK3566 ✅（本项目的板子）
  - `Orange Pi Zero 3W` = 全志 A733 ❌（2026-04 发布，生态完全不同）
  - `Orange Pi Zero 3` = 全志 H618 ❌（无 NPU 无 CSI）
  - `Orange Pi 3B` = RK3566（自设计结构时的备选，¥300 现货；本次未选，因机身拟复刻原版）
  - `Orange Pi 5/5B` = RK3588S（语义视觉阶段再议；2026 内存涨价周期 8G+64G 已 ¥2000+，不追）
  - Raspberry Pi 5 ❌（无 NPU、无硬件 H.264 编码器、缺货涨价）

## 1. 已购硬件

| 项 | 配置 | 备注 |
|---|---|---|
| 主板 | Radxa Zero 3W，**2GB RAM / 无 eMMC / 带排针** | 京东现货；开发期够用（官方量产机为 1GB+32GB eMMC）。量产前建议换带 eMMC 版本（SD 卡在走路震动下是故障源） |
| 启动介质 | 64GB microSD（A2） | 板载卡槽在背面 |
| 舵机 | 飞特 HD-1910-C001 × **1**（验证用） | 在途（截至 2026-10-14 未接上总线）。红线不变：协议验证前不批量下单 |
| 调试板 | 飞特 FE-URT-2 | 在途；用于烧 ID/波特率 + Week 1 spike，不进最终架构 |

## 2. 历史：原 Armbian 基线（2026-09-20 完成，该卡已被 §6 覆盖）

1. **镜像**：Armbian **26.8.1** Minimal / Debian 13 (trixie) / **Vendor 6.1.115**，
   用 [armbian.com/radxa-zero-3](https://www.armbian.com/radxa-zero-3/) 的 imager 烧录。
   （`install-dev.md` 写 26.2.1，但内核与底座一致，26.8.1 可用；**必须选 Vendor 内核**，
   Current/mainline 内核没有 CSI/VPU/NPU 驱动。）
2. **系统基线验证**：
   - `uname -r` = `6.1.115-vendor-rk35xx` ✅（正是 media-bringup 验证的内核）
   - 内存识别 1.92G；CPU 57°C 正常；根分区 58G
   - 时区 Asia/Shanghai；locale en_US.UTF-8（机器人板保持英文，避免中文输出坑脚本）
3. **网络**：DHCP 拿到 `10.181.1.27`（profile 里设的静态 IP 未生效，见 §4 经验）。
   静态绑定暂未做，计划 provisioning 跑完后再去路由器做 DHCP-MAC 绑定。
4. **账户**：`radxa`（sudo 已启用）。ssh 密钥尚未安装（下一步第一件）。

> 本节是**历史记录**：这张 TF 卡已于 2026-10-14 被 kissqy 整合镜像覆盖（§6），
> 因此下面原本计划的 provisioning 步骤与 UART/NPU/VPU 验收项**不再执行**；
> 需要这份 Armbian 基线时另备一张卡重烧。当前进度见 §3。

## 3. 当前待办（2026-10-14 重刷后重新基线化）

> 原「按顺序」待办是照着**原始 Armbian + 官方 `provision-board.sh`** 写的；重刷 kissqy 整合镜像后，
> 前三条（`ssh-copy-id` / provisioning / UART·NPU·VPU 四件套验收）已不适用。原文见本节末尾归档。

| # | 待办 | 说明 / 前置 |
|---|---|---|
| 1 | **接舵机，让 robotd 过完四步启动** | 现卡在第 2/4 步：`Feetech Sync Read timeout; missing IDs [10,11,12,13,14,20,…,34]`。到货后先用 FE-URT-2 烧 ID/波特率再上总线；验收 `robotctl health`（无舵机时报不健康是诚实答案） |
| 2 | **中控把 control.40 升到 control.43** | 镜像自带 control.40；在 V167 中控「系统维护」里安装随包固件即可，不需要自己编译 |
| 3 | **IMU 板单独刷 Feetech FT6 `.bin`** | 刷系统镜像、升级 ZERO 服务都**不会**烧录 IMU（见 `hardware/IMU-FIRMWARE.md`） |
| 4 | 恢复免密登录（可选） | 现在用密码登录；`ssh-copy-id radxa@10.181.1.27` 即可装回公钥（§5 有连接信息） |
| 5 | 要 Armbian 基线时另备一张卡 | Vendor 6.1.115 / NPU / VPU 那套验收只在原基线上有效（§2 历史记录） |

**本次重刷未复核的原计划项**（按需取用）：Mac 交叉编译回路（`cargo board --bins` → scp 上板）、
`robotd --fake` 全链路冒烟、duck-bench NPU 基线、供应商 24 问清单。

<details>
<summary>归档：原定待办（2026-09-20，已不适用，保留备查）</summary>

```text
1. Mac: ssh-copy-id radxa@10.181.1.27
2. Mac: export DUCK_TOKEN=github_pat_xxx（pollen-robotics/microduck 读权限）
   ./scripts/provision-board.sh --pause-btd-on-pair --name Ducky radxa@10.181.1.27
   （中途 ssh 断开=预期行为，脚本会等板子重启回来）
3. 验收四件套：
   ls /dev/ttyS2                    # UART2 overlay
   dmesg | grep rknpu               # NPU 驱动绑定
   gst-inspect-1.0 mpph264enc       # VPU 编码链路
   robotctl health                  # 无舵机时报不健康是诚实答案，不算失败
4. robotd --fake 全链路冒烟
5. Mac 交叉编译回路：cargo board --bins → scp 上板
6. duck-bench NPU 基线（用录制帧，不需要相机）
7. URT-2 + 舵机到货 → Week 1 单电机 spike（采集脚本提前写好 mock 自测）
8. 供应商 24 问清单发出（hardware-open-questions.md A6 有现成稿）
```

</details>

## 4. 踩坑与经验（下次直接照抄）

- **Armbian imager 的 autoconfig profile 不可靠**：本次 WiFi、用户、静态 IP **全部没生效**，
  板子停在出厂初始化状态。兜底路径：`ssh root@<IP>` 密码 `1234`，会被强制改 root 密码并
  创建用户。**若烧完板子不上网，先走这条路，别反复重烧。**
- **ping 显示 `Host is down`** = ARP 无应答 = 该 IP 上没有设备（区别于 `Request timeout`）。
- **ssh `Permission denied` 但密码"正确"** → 先怀疑用户是否存在（`ls /home/`），
  profile 没生效时用户根本没建。
- **mDNS（radxa-zero3.local）不可靠**，找板子用路由器 DHCP 列表，或
  `ping -c2 <网段>.255 && arp -a`。
- **`armbian-config` 首启卡在 "Initializing"**（联网自检，国内网络下明显）——本项目不需要它。
- 首次启动扩分区，**上电后等满 3–5 分钟**再下结论。
- 重刷后同一 IP ssh 报 host key 变化：`ssh-keygen -R <IP>`（2026-10-14 实操见 §6）。
  **但先验证再删**：核对反查主机名 / 开放端口 / SSH banner，确认是同一台设备；
  该整合镜像不预置主机密钥，重刷后换指纹是必然（判定方法见 §6.2）。

## 5. 连接与性能信息（日常用）

| 项 | 值 |
|---|---|
| SSH | `ssh radxa@10.181.1.27`（DHCP，重刷后仍是同一地址；配置时静态 IP 未生效，见 §4） |
| 密码 | 见 **[`local/secrets.md`](../local/secrets.md)**（`local/` 已加入 `.gitignore`，只存本机）。本仓库是公开的，凭据**不写进被跟踪的文件** |
| 中控「SSH / sudo 密码」栏 | 填同一个密码（重启中控后需重填） |

```bash
uptime && free -h && df -h /
cat /sys/class/thermal/thermal_zone0/temp   # 千分之一摄氏度
htop
```

## 6. 2026-10-14：TF 卡重刷 kissqy 整合镜像（Public Image R1）

### 6.1 动作与来源

| 项 | 值 |
|---|---|
| 镜像 | `microduck-zero3w-0.15.1-R1.img.xz`（`kissqy/Microduck-kissqy` Release `public-image-r1`） |
| 本机路径 | [`downloads/microduck-zero3w-0.15.1-R1.img.xz`](../downloads/microduck-zero3w-0.15.1-R1.img.xz)（736 MiB，另附 `.sha256`） |
| 校验 | SHA256 `75da978b…a7bce5`，与[镜像发布说明](../reference/Microduck-kissqy/docs/releases/public-image-r1.md)一致；`xz -t` 通过 |
| 下载 | 经本机 7897 代理，约 3 分钟（AGENTS.md 约定：GitHub 一律走代理） |

**副作用（重要）：** 这张 64GB TF 卡上原来的 Armbian 26.8.1 / Debian 13 trixie / Vendor 6.1.115 基线（§2）
**已被覆盖**。若还要复现 §2 的内核 / NPU / VPU 基线，需另备一张卡，或用 armbian imager 重新烧回。

### 6.2 首次 SSH 报 host key 变化 —— 是重刷的正常现象

刷完卡后 `ssh radxa@10.181.1.27` 报 `REMOTE HOST IDENTIFICATION HAS CHANGED`：

```text
The fingerprint for the ED25519 key sent by the remote host is
SHA256:spuGmnkVy0sLfMlf00MhZ84y2jYlDuu29RIV+ekz2Xg.
Offending ECDSA key in /Users/jin/.ssh/known_hosts:6
```

判定为**良性**（不是中间人），三条证据：

1. 反查主机名 = `radxa-zero3`（同一台鸭子板），22 端口开放，banner `OpenSSH_10.0p2 Debian-7`（Debian 13，与镜像底座同代）；
2. RSA / ECDSA / ED25519 **三把同时全换** —— 重装特征，而非单把被替换；
3. **镜像里不带任何预置主机密钥**：把 `img.xz` 全量解压（2.94 GiB）逐块扫描，
   OpenSSH 私钥的 base64 魔数 `b3BlbnNzaC1rZXktdjEA`（`openssh-key-v1\0`）命中 **0 次**。
   即密钥是板子首启 `ssh-keygen -A` 本地生成 —— 重刷后换指纹是必然，也没有可比对的权威来源。

> 告警文案里 “Offending **ECDSA** key” 是因为旧 `known_hosts` 把三种类型都记了：
> ssh 报了其中一条 ECDSA 行，同时打印服务端本次实际提供的 ED25519 指纹，指向同一件事。
>
> 反面教训：镜像里 `-----BEGIN OPENSSH PRIVATE KEY-----` 这类**二进制里的字符串常量**
> （ssh-keygen 等可执行文件自带）会产生大量假命中，光看字符串标记会误判。

### 6.3 处理结果与当前指纹

```bash
ssh-keygen -R 10.181.1.27                                   # 旧文件备份在 ~/.ssh/known_hosts.bak-20261014-212432
ssh-keyscan -T 8 -t rsa,ecdsa,ed25519 10.181.1.27 >> ~/.ssh/known_hosts
```

| 类型 | SHA256 指纹（2026-10-14 实测） |
|---|---|
| ED25519 | `spuGmnkVy0sLfMlf00MhZ84y2jYlDuu29RIV+ekz2Xg` |
| RSA | `XApbwepX0E52X6fs6uIyuU3kEe2YCP25+5YyGUfbbHU` |
| ECDSA | `UozvIutWcy4PAx84o1uKhaFLS7JeThf5Qa4F8UaIYcE` |

复测：`ssh` 不再报密钥告警，直接进入认证阶段。**免密登录失效属正常** —— 重刷清空 `authorized_keys`，
且该镜像明确不打包任何预置密钥（见其第三方声明）；用配网时（`http://10.42.0.1:8088`）设的系统密码登录。

### 6.4 登录后核对镜像生效（已完成 2026-10-14 21:45）

```bash
ssh radxa@10.181.1.27 'hostname; uname -r; grep PRETTY_NAME /etc/os-release; \
  systemctl is-active robotd padd configd btd 2>/dev/null'
```

核对结果：中控 `system` 通道报回 hostname = **`microduck`** → 跑的确实是 kissqy 镜像（详见 §6.6 附带确认）。

- 镜像预装 robot 服务与运动模型，中控连接方式见[机器人中控说明](../reference/Microduck-kissqy/microduck-hd1910/firmware/console/README.md)；
- 镜像自带 **control.40**；要升到 control.43 需在 V167 中控里安装随包固件；
- **IMU 是独立单片机**：刷系统镜像不会烧录它，新做的 IMU 板需单独刷 Feetech FT6 `.bin`（见 `hardware/IMU-FIRMWARE.md`）。

### 6.5 macOS 上控制台登录失败：发布 ZIP 丢了执行位（2026-10-14）

**现象**：控制台填 `radxa@10.181.1.27` + 密码，报

```text
SSH 登录失败，请检查地址、用户名和密码；原始错误：SSH 接口转发失败：
ssh_askpass: exec(.../Microduck-Console-R17-V167/ssh-askpass): Permission denied
radxa@10.181.1.27: Permission denied (publickey,password).
连接异常：SSH 密钥认证失败，请确认当前 Windows 账号可以免密登录 Zero。
```

**根因**：控制台靠 askpass 钩子把密码递给 SSH（`ssh_connect.py` 设 `SSH_ASKPASS` / `SSH_ASKPASS_REQUIRE=force` / `MICRODUCK_SSH_PASSWORD`），
而发布 ZIP 打包时把权限位写成了 `-rw-r--r--` —— 解压后 **217 个文件无一带执行位**，钩子 exec 失败，
密码压根没递进去，SSH 于是只剩 publickey 一条路 → 认证失败。

⚠ **与免密登录、密码是否正确都无关**：界面那句「请确认当前 Windows 账号可以免密登录 Zero」是 Windows 文案，会把人带偏。
排除干扰项的判据就是日志里那行 `ssh_askpass: exec ...: Permission denied`。

**修复**（解压目录内执行）：

```bash
cd reference/Microduck-kissqy/release-assets/Microduck-Console-R17-V167
chmod +x ssh-askpass start.command console.py
```

**验证方法**（不需要正确密码即可自证）：

```bash
# ① 钩子本身能回填密码
MICRODUCK_SSH_PASSWORD=x ./ssh-askpass

# ② 端到端：故意用错密码，应只剩 Permission denied，不再出现 askpass exec 报错
SSH_ASKPASS="$PWD/ssh-askpass" SSH_ASKPASS_REQUIRE=force MICRODUCK_SSH_PASSWORD=wrong DISPLAY=:0 \
  ssh -T -o BatchMode=no -o PreferredAuthentications=password -o NumberOfPasswordPrompts=1 \
      radxa@10.181.1.27 true

# ③ 对照实验：SSH_ASKPASS=/nonexistent 会复现 exec 报错 → 证明该命令行确实走 askpass
```

**打包侧问题（值得反馈作者）**：两个 ZIP 里带执行位的条目都是 **0** 个：

```text
Microduck-Console-R17-V167.zip          ssh-askpass, ssh-askpass.exe, start.command      均为 -rw-r--r--
Microduck-Training-Studio-R1.5.27.zip   start-training.command, training/server_prerequisites.sh 均为 -rw-r--r--
```

→ 解压训练中控后同样要 `chmod +x start-training.command training/server_prerequisites.sh`。
Windows 用户不受影响，所以作者侧没暴露出来。

> 附注：控制台用 `StrictHostKeyChecking=accept-new`，所以 §6.2 的主机密钥变化**不会**阻断它；
> 它在 macOS 上唯一缺的就是执行位。

### 6.6 ZERO 温度瓦片修复：给控制台补上 `system` 通道（2026-10-14）

**现象**：中控「硬件观测台」的 **ZERO 温度** 恒为 `—` +「等待主板温度回读」，板子在线、SSH 已连接也一样。

**根因**：`system` 通道（`cpu_temp_c` / 内存 / CPU / uptime / hostname 都在里面）在该构建里**没有产出方**。

| 事实 | 位置 |
|---|---|
| `cpu_temp_c` 与 `channel:"system"` 全仓唯一产出方 | `agent.py:221` / `agent.py:245` |
| 唯一注入 `agent.py` 到板子的函数 | `console.py:66` 的 `ssh_loop` |
| `ssh_loop` 调用点 | **0 个**（死代码） |
| `console.py:352` 的 `import agent` | 非 dashboard 分支，且 `run()` 在 `__main__` 保护内 → 空操作 |
| `start.command` 的模式 | `--dashboard --feetech` → `service` → 只跑 `raw_loop` |

会话日志里「采集 SSH」计数为 **0**，与「agent 从未运行」吻合。**同页另外四个空瓦片
（控制循环 / 关节反馈 / 总线电压 / 舵机温度）是另一回事**：robotd 卡在第 2/4 步，接了舵机才会亮。

**修复**：在 `raw_telemetry.py` 增加 `system_loop()` 并挂进 `raw_loop()`——一条**常驻** SSH 会话跑固定
只读 shell 循环（3 秒一轮）读板子的 `/proc/*`、`/sys/class/thermal/*`、`/run/robotd/identity.json`，
按 `agent.py` 原有契约产出 `system` 事件。连接**仅在失败后重建**并指数退避（2→6 s），
不引入重连抖动（板子 sshd 的 `MaxStartups` 已经在丢新连接，见 §6.7）。

**产物**：[tools/console-zero-temp/](../tools/console-zero-temp/README.md)（unified diff、原始备份、完整补丁文件、离线测试）

**验证**：`py_compile` 通过；离线测试 20 项断言全过（假板子跑通 ssh→分帧→解析→emit，
含毫摄氏度换算、首帧无 cpu_percent、坏 base64 / NaN / 缺 `/proc` 降级）；
补丁套用结果与完整补丁文件逐字节一致；作者自带 `verification/test_*.py` **打补丁前后各跑一遍结果完全一致**
（6 PASS / 5 FAIL，5 个 FAIL 为包内缺 `test_upgrade_units` 等辅助模块的既有问题）→ 无回归。

**注意**：`reference/` 是第三方 checkout（已 gitignore），且该控制台目录是从 Release ZIP 解压的未跟踪文件，
**重新解压 ZIP 会丢补丁**，用上述任一产物恢复；修改需重启中控生效（刷新网页不够——补丁改的是 Python 源码）。

**实机确认（2026-10-14 21:45，`radxa@10.181.1.27`）**：重启中控后 ZERO 温度显示 **52.5 °C**、
说明文字变为「ZERO 主板 CPU 实测」；新会话日志 `system-20261014-214439-29f064.log` 里
`Zero 系统信息` 失败条目 **0** 条（常驻 SSH 一次建成），旧会话那种 `原始遥测` SSH 重置风暴也没有再出现。

**附带确认（重要）**：`system` 通道报回的 hostname 是 **`microduck`**，不是旧 Armbian 的 `radxa-zero3`
——说明板子上跑的确实是 kissqy 镜像；§6.2 里反查到 `radxa-zero3` 是路由器 DHCP 里的旧 PTR 记录。
同一页另外四个空瓦片（控制循环 / 关节反馈 / 总线电压 / 舵机温度）仍按预期为空：robotd 卡在第 2/4 步，等接舵机。

### 6.7 附带发现：板子 sshd 在未认证连接堆积时丢弃新连接（2026-10-14）

排查温度通道时发现，旧会话日志里 **71 次「原始遥测」端口转发全部失败**，其中 48 次是
`kex_exchange_identification: read: Connection reset by peer`。从 Mac 做独立对照实验：

| 场景 | 结果 |
|---|---|
| 间隔 3 秒连 6 次 | **6/6** 走完握手（到达认证阶段） |
| 先占住 12 条空连接不发 kex，再连 6 次 | **2/6**，4 次被 `kex_exchange_identification` 重置 |

即板子 sshd 的 `MaxStartups`（Debian 默认 `10:30:100`）在未认证连接堆积时会丢新连接。
中控每约 2 秒就要开 2–3 条新 SSH（`/run/robotd.sock` + `/run/tofd/tof.sock` 端口转发），长期顶在高位，
所以旧会话里连接被反复重置。

缓解（需登录后 sudo，**尚未执行**）：

```bash
sudo sed -i 's/^#\?MaxStartups.*/MaxStartups 100:30:200/' /etc/ssh/sshd_config && sudo systemctl restart ssh
```

注：§6.6 补丁的常驻连接**只在失败后重建**，已刻意不加剧这个问题；实机验证时新会话日志里这类重置未再出现。

## 相关文档

- [tools/console-zero-temp/](../tools/console-zero-temp/README.md) — 中控 ZERO 温度通道补丁（§6.6，含原始备份与离线测试）
- [downloads/microduck-zero3w-0.15.1-R1.img.xz](../downloads/microduck-zero3w-0.15.1-R1.img.xz) — 本次重刷用的系统镜像（§6.1）
- [reference/Microduck-kissqy/](../reference/Microduck-kissqy/) — 镜像与中控的上游仓库（本地 checkout）
- `hardware-open-questions.md` — B1 主板项（已由本日志定案）
- `reference/microduck-lab/microduck/docs/robot/install-dev.md` — 官方 provisioning 流程（**已不适用**，见 §3 归档）
- `reference/microduck-lab/microduck/docs/project/media-bringup.md` / `npu-bringup.md` — 媒体/NPU 验证记录（对应 §2 历史基线）
