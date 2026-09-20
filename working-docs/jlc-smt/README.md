# elec_RPI_Robot_HAT — 嘉立创（jlc.com 国内站）下单清单

来源：`reference/elec_RPI_Robot_HAT` 本地参考副本 @ `88d51fa`，production/ 为原厂 C1 批次量产文件
（原厂提交：`[update] Release C1 (for Grabette), now qtty 20 @JLCPCB`）

## 上传文件（共 3 个）

本目录即完整下单包，三个文件与上游 `elec_RPI_Robot_HAT/production/` 中对应文件
逐字节相同（BOM 除外，为修正版）。

| 上传位置 | 本目录文件 | 说明 |
|---|---|---|
| PCB 下单（Gerber） | `PCB01186-C1_elec_RPI_Robot_HAT_PCB.zip` | 直接用，4 层板 |
| SMT：BOM 栏 | `elec_RPI_Robot_HAT_BOM_jlc.csv` | **已修正**，见下 |
| SMT：坐标栏 | `ASE01187-C1_elec_RPI_Robot_HAT_POS.csv` | 原文件即合规，直接用 |

`README.md` 与 `.DS_Store` 无需上传。

不用上传：`STEP.zip`、两个 PDF、所有 `.kicad_pcb` / `.kicad_sch`。

## BOM 相对原文件改了什么

原 `ASE01187-C1_..._BOM.csv` **不能直接上传**，国内站规范有硬性要求：

1. **删除 9 个 DNP 位号**（国内站明确要求：「不贴的位置不能出现在材料清单中」）
   `C25`、`R10`、`R11`、`R16`、`R17`、`R41`、`R36`、`R37`、`U4`
2. **删除 `H2`** —— `Library_Pollen:Logo_HF_2025`，画在 F.Cu 铜层上的 logo，
   无实体元件、不在坐标文件中，留着会变成匹配异常项
3. **列名改为国内站模板**：`Designator,Footprint,Quantity,Value,LCSC Part #`
   → `Comment,Designator,Footprint,JLCPCB Part #`
4. **去掉 UTF-8 BOM 头**（Excel 有时不认）
5. **欧洲小数逗号** `6,8u 2A` → `6.8u 2A`（避免被当成字段分隔符）

结果：41 行 / 113 个位号。已与原坐标文件交叉核对，位号完全对应。

## 下单要点

- **双面贴片**：bottom 67 件、top 50 件，按两个面收贴片费 + 2 次钢网
- **4 层板**：铜层 F/In1/In2/B，板框 65.00 × 30.90 mm
- **未选料提示**：坐标文件里的 `FID1`/`FID2`/`FID3`（基准点）、`H3`（安装孔）
  不在 BOM 中，会显示为未匹配 —— **不要给它们选料**
- **`TP2`/`TP3`/`TP4`**（测试点）和 `H2` 无料号；测试点有坐标会被要求选料，
  若不贴请手工删除
- **库存**：上传后逐个核对红黄标记，重点看 U2 / U11 / U3 / U10 / Wago / J4

## 已知上游待办（影响后续版本，不影响本次下单）

最新提交 `88d51fa` 只在原理图加了 ToDo 文字，元件未变，Gerber 与 BOM 一致：

> ToDo: - update IMU for LSM6DSV16XTR - check compatibility with Radxa boards

即上游计划把 IMU 从 **BMI088 换成 LSM6DSV16X**，并适配 Radxa 板。
另外 `U4` 是 DNP 的 CAT24C32 EEPROM —— 若要做符合 HAT+ 规范、
能被系统自动识别的版本，需要把它打开并补料（docs 内有规格书，
料号为 `C233772`）。

## 参考

- [BOM 清单格式规范解读（国内站）](https://www.jlc.com/portal/server_guide_19337.html)
- [坐标文件格式规范解读（国内站）](https://www.jlc.com/portal/server_guide_53182.html)
- [坐标文件（BOM）格式说明（国内站）](https://www.jlc.com/portal/q7i49654.html)
