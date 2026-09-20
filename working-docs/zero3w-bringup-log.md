# Radxa Zero 3W 主板 bring-up 日志与选型结论

日期：2026-09-20（最后更新）
状态：**板子已点亮、系统基线验证通过；provisioning 未跑**

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
| 舵机 | 飞特 HD-1910-C001 × **1**（验证用） | 在途。红线不变：协议验证前不批量下单 |
| 调试板 | 飞特 FE-URT-2 | 在途；用于烧 ID/波特率 + Week 1 spike，不进最终架构 |

## 2. 已完成

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

## 3. 待办（按顺序）

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
- 重刷后同一 IP ssh 报 host key 变化：`ssh-keygen -R <IP>`。

## 5. 性能信息查看命令（日常用）

```bash
uptime && free -h && df -h /
cat /sys/class/thermal/thermal_zone0/temp   # 千分之一摄氏度
htop
```

## 相关文档

- `hardware-open-questions.md` — B1 主板项（已由本日志定案）
- `reference/microduck-lab/microduck/docs/robot/install-dev.md` — 官方 provisioning 流程
- `reference/microduck-lab/microduck/docs/project/media-bringup.md` / `npu-bringup.md` — 媒体/NPU 验证记录
