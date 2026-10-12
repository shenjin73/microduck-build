# 整机装配与首次上电记录（2026-10-12）

接续 `zero3w-bringup-log.md`（主板点亮、系统基线已过）和 `docs/actuator-identification.md`
（2026-09-26 单颗 HD-1910 经 URT-2 的第一轮台架数据）。本篇覆盖：**所有零件到齐后的
硬件互连关系、装配验证、以及第一次整机链路上电的计划**。

## 0. 零件状态：全部到齐

15×HD-1910-C001、FE-URT-2、Radxa Zero 3W（2GB/无 eMMC/带排针）、
elec_RPI_Robot_HAT（ASE01187-C1，与 `reference/elec_RPI_Robot_HAT` 生产包同版）、
imu_to_dxl（microduck-community-kit 版，CN2 JST PH 已由卖家焊好）、
Radxa Camera 8M 219、VL53L8CX ToF、NP-F550 电池。

## 1. 已确认的互连关系（含验证依据）

```
电池 NP-F550 ──► HAT 舵机口 J13/J14 pin2（+BATT 直通舵机；经 buck → 5V 回供 Radxa）
Radxa ──40pin──► HAT（pin8/10=UART2→舵机总线；pin3/5=I2C3→J5；pin2/4=5V回供；pin1/17=3V3进HAT）
Radxa ──MIPI CSI──► Radxa Camera 8M 219（不经 HAT）
HAT J5（Qwiic，唯一真 I2C）──► VL53L8CX ToF
舵机总线（1Mbps 半双工 TTL）══ 15×HD-1910（PH）+ imu_to_dxl（CN2，PH，ID 200）
```

- **Radxa↔HAT 方向**：Radxa pin 1 = 排针**远离 USB-C 的那端**（白色三角丝印，
  靠板中心一列）。官方装配手册 H09/H10 原话「确认 2×20 排针 Pin 1 方向后再压入」。
  标注图：`board-photos/radxa-pin1-annotated.jpg`
- **HAT 接口图**：J13/J14=TTL 舵机口+电池输入（1=GND/2=+BATT/3=DATA，两口并联）、
  J11/J3=RS-485（用不到）、J5~J8=Qwiic（只有 J5 真 I2C）、J1=喇叭（差分两脚都不是地）、
  J2/J9=外接麦、MK1=板载麦。40pin 逐脚网表已核对。
  标注图：`board-photos/hat-connectors-annotated.jpg`
- **imu_to_dxl CN2 脚序**（元件面朝上、座子在右缘的朝向）：上=GND(pin3)、
  中=+BATT(pin2)、下=DATA(pin1)。依据：kicad_pcb 焊盘坐标 + production/netlist.ipc
  交叉验证。CN1/CN2 是同一位置的两个备选封装，本板已焊 CN2，无需再焊。
  标注图：`board-photos/imu2dxl-cn2-annotated.jpg`
- **EH↔PH 转接规则**：HAT 侧 EH（1=GND/2=Vcc/3=DATA）↔ 飞特侧 PH
  （1=DATA/2=Vcc/3=GND）——两端外脚交叉、中间 Vcc 直连。舵机和 imu 板用同一种转接线。
- **供电策略**：USB-C 与电池**不并插**（Radxa 侧 5V 无隔离，会倒灌）。
  纯软件阶段用 USB；总线链路测试时电池/可调电源经舵机口供电，Radxa 走 HAT 回供，
  交互走 WiFi/ssh。

## 2. 装配与不通电检测（已完成）

- Radxa + HAT + imu_to_dxl（经转接线）已连接
- ✅ GND 蜂通：HAT 舵机口 GND 针 ↔ Radxa USB-C 外壳
- ✅ +BATT↔GND 无短路：12–20 MΩ（阻值缓慢漂移是电容+非线性负载的正常表现；
  判据是绝对值，个位数欧姆才是短路）
- ⬜ DATA 线蜂通（转接线交叉验证）：imu 板 CN2 最下针 ↔ HAT 舵机口 pin 3

## 3. 接下来（按顺序）

**阶段 A（USB 供电，不接电池）— 软件准备**

1. `ssh-copy-id` + 跑 `provision-board.sh`（需 DUCK_TOKEN；中途断线=预期）
2. 验收四件套：`ls /dev/ttyS2`、`dmesg|grep rknpu`、`gst-inspect-1.0 mpph264enc`、
   `robotctl health`（无舵机时报不健康是诚实答案）
3. `systemctl mask serial-getty@ttyS2`（Armbian 默认控制台会往总线吐垃圾）；
   U-Boot 控制台按 Radxa 文档处理（/etc/default/u-boot prompt/timeout=0）
4. WiFi IP 固定（路由器 DHCP-MAC 绑定）——阶段 B 没有 USB，ssh 全靠 WiFi
5. 装 pyserial，scp `tools/servo-debug/feetech.py` 上去

**阶段 B（电池/可调电源供电，拔 USB）— imu_to_dxl 链路测试**

6. 总线只挂 imu_to_dxl（先不接舵机）。有可调电源就 6–8V 限流 100–200mA 喂舵机口
   （中间 +BATT），没有就电池虚接、手捏插头准备秒拔
7. ping ID 200：`FeetechBus('/dev/ttyS2').ping(200)` 返回 0 = 全链路通
8. 读地址 56 起 15 字节（IMU 契约块），晃板子数据跟着变 = 端到端证据。
   协议细节：`reference/microduck-community-kit/firmware/v1/docs/imu_to_dxl_protocol.md`

**之后回到 ROADMAP 阶段 1 剩余项**

9. 15 颗舵机逐颗烧 ID（出厂全是 ID 1，一次只上一颗）+ 打开过流/过压保护
10. `robotctl health` 报 15 颗电压/温度、`robotctl monitor` 画关节角 = **Gate 1**
11. 然后进入阶段 2 台架辨识（关键路径，已有 09-26 第一轮数据打底）
