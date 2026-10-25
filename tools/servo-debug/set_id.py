#!/usr/bin/env python3
"""给一颗 HD-1910 改 ID（一次只接一颗，默认从 ID 1 改）。

机器人固定 ID：
  10-14 = 右腿，20-24 = 左腿，30-34 = 颈/头/嘴。

用法（Mac + FE-URT-2）：
  cd tools/servo-debug
  python3 set_id.py --port /dev/cu.usbmodemXXXX --new-id 10

用法（Zero 的 HAT 总线）：
  sudo systemctl stop robotd
  python3 set_id.py --port /dev/ttyS2 --new-id 10

前提：
  * 总线上只能有一颗 old-id（默认 1）的舵机；配好一颗再换下一颗。
  * 舵机供电 5-7.4V；HAT 总线还要 +BATT 有电。
  * 波特率出厂默认 1 Mbps（寄存器 6 = 0）；本脚本只改 ID，不改波特率。
"""

import argparse
import sys
import time

try:
    import feetech
except ImportError:
    sys.exit("找不到 feetech.py：请 cd 到 tools/servo-debug，或把 feetech.py 和本脚本放在同一目录。")

ROBOT_IDS = set(range(10, 15)) | set(range(20, 25)) | set(range(30, 35))


def region(i):
    if 10 <= i <= 14:
        return "右腿（10-14）"
    if 20 <= i <= 24:
        return "左腿（20-24）"
    if 30 <= i <= 34:
        return "颈/头/嘴（30-34）"
    return "非机器人 ID"


def show_u8(bus, sid, addr, label):
    try:
        v = bus.read_u8(sid, addr)
        print("  %-8s %d (0x%02x)" % (label, v, v))
        return v
    except Exception as e:
        print("  %-8s 读取失败：%s" % (label, e))
        return None


def show_u16(bus, sid, addr, label):
    try:
        v = bus.read_u16(sid, addr)
        print("  %-8s %d (0x%04x)" % (label, v, v))
        return v
    except Exception as e:
        print("  %-8s 读取失败：%s" % (label, e))
        return None


def main():
    ap = argparse.ArgumentParser(description="给一颗 Feetech HD-1910 改 ID（一次只接一颗）")
    ap.add_argument("--port", required=True,
                    help="串口：Mac 上是 /dev/cu.usbmodemXXXX，Zero 上是 /dev/ttyS2")
    ap.add_argument("--new-id", type=int, required=True, help="目标 ID（机器人：10-14/20-24/30-34）")
    ap.add_argument("--old-id", type=int, default=1, help="当前 ID，默认 1（出厂）")
    ap.add_argument("--baud", type=int, default=1_000_000, help="总线波特率，默认 1 Mbps")
    ap.add_argument("--timeout", type=float, default=0.05, help="单次应答超时，默认 0.05 s")
    ap.add_argument("--dry-run", action="store_true", help="只读，不写 ID")
    ap.add_argument("--force", action="store_true", help="允许写机器人范围以外的 ID")
    a = ap.parse_args()

    if not 0 <= a.new_id <= 253:
        sys.exit("new-id 必须在 0..253")
    if a.new_id == a.old_id:
        sys.exit("new-id 不能等于 old-id")
    if a.new_id not in ROBOT_IDS and not a.force:
        sys.exit("ID %d 不在机器人映射里（10-14/20-24/30-34）；确实要写请加 --force" % a.new_id)

    print("注意：总线上只能有一颗 ID %d 的舵机；配好一颗再换下一颗。" % a.old_id)
    print("      舵机供电 5-7.4V；/dev/ttyS2 上先 sudo systemctl stop robotd。")
    print("      目标：ID %d -> %d（%s）" % (a.old_id, a.new_id, region(a.new_id)))

    try:
        bus = feetech.FeetechBus(a.port, baud=a.baud, timeout=a.timeout)
    except Exception as e:
        sys.exit("打不开串口 %s：%s" % (a.port, e))

    try:
        err = bus.ping(a.old_id)
        if err is None:
            print("\nID %d 没应答。检查：" % a.old_id)
            print("  * 只接了这一颗 ID %d 的舵机；" % a.old_id)
            print("  * 供电 5-7.4V（HAT 总线要 +BATT 有电）；")
            print("  * /dev/ttyS2 上 robotd 已停；")
            print("  * 波特率 1 Mbps（出厂默认）；")
            print("  * URT-2 / 转接线 / J13/J14 接对。")
            return 1

        print("\nID %d 在线（err=%d）" % (a.old_id, err))
        show_u16(bus, a.old_id, 3, "型号")
        show_u8(bus, a.old_id, 0, "固件主")
        show_u8(bus, a.old_id, 1, "固件次")
        baud = show_u8(bus, a.old_id, 6, "波特率码")
        if baud is not None and baud != 0:
            print("  警告：波特率码 %d 不是 0（1 Mbps）；机器人要求 1 Mbps。" % baud)
            print("        请先用 FD/调试工具把它改成 1 Mbps，再用本脚本改 ID。")

        if a.dry_run:
            print("\n--dry-run：只读，不写 ID。")
            return 0

        print("\n正在把 ID %d 改成 %d ..." % (a.old_id, a.new_id))
        ok = False
        try:
            ok = bus.set_id(a.old_id, a.new_id)
        except Exception as e:
            print("set_id 抛异常：%s" % e)

        # set_id 内部已经 ping 过新 ID；这里再独立确认一次
        new_err = bus.ping(a.new_id)
        if new_err is not None:
            print("成功：ID %d 在线（err=%d，%s）" % (a.new_id, new_err, region(a.new_id)))
            show_u8(bus, a.new_id, 6, "波特率码")
            print("\n贴标签：ID %d（%s）。" % (a.new_id, region(a.new_id)))
            print("然后拔掉这颗，换下一颗 ID %d。" % a.old_id)
            return 0

        old_err = bus.ping(a.old_id)
        print("失败：新 ID %d 没应答；旧 ID %d %s。" % (
            a.new_id, a.old_id, "仍在" if old_err is not None else "也不在了"))
        print("如果旧 ID 仍在，EEPROM 可能没解锁或写入被拒；重试一次。")
        print("如果两个都不在，断电重上电，再用 FD/调试工具扫 ID。")
        return 1
    finally:
        bus.close()


if __name__ == "__main__":
    sys.exit(main())
