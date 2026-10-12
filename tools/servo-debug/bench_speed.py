# -*- coding: utf-8 -*-
"""HD-1910 空载转速 + 指令延迟台架测试（单颗舵机，URT-2 接 Mac）。

  python bench_speed.py [--port /dev/cu.usbmodemXXX] [--id 1]

延迟：写目标位置（带应答）返回的时间戳 → 位置寄存器第一次动 ≥2 步的时间戳，重复 50 次。
转速：1024 → 3072 大阶跃，途中高频读位置，对 10%–90% 行程段做线性拟合得斜率。
注意：电压近似 4.5V（USB 供电），转速和电压近似成正比，7.4V 时要重测。
原始数据写 ../../docs/bench/。
"""
import argparse
import csv
import statistics
import struct
import sys
import time

import feetech

LAT_REPS = 50
LAT_AMP = 150        # 延迟测试：2048 ± 150 交替
SPEED_FROM, SPEED_TO = 1024, 3072
HERE_DOCS = "../../docs/bench"


def read_pos(bus, sid):
    return feetech.sign15(bus.read_u16(sid, 56))


def settle(bus, sid, target, tol=3, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if abs(read_pos(bus, sid) - target) <= tol:
            return True
        time.sleep(0.02)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/cu.usbmodem5C842873721")
    ap.add_argument("--id", type=int, default=1)
    a = ap.parse_args()
    bus = feetech.FeetechBus(a.port, baud=1_000_000)
    sid = a.id
    volt = bus.state(sid)["volt"]
    print(f"舵机 ID {sid}，电压 {volt} V")

    # 扭矩开、加速度最大、速度放开（相位 BIT3=0：速度 0=停，要写大值）
    bus.write_u8(sid, 40, 1)
    bus.write_u8(sid, 41, 254)
    bus.write_u16(sid, 46, 3000)
    bus.write_u16(sid, 42, 2048)
    assert settle(bus, sid, 2048), "回 2048 不到位"

    # ---- 指令延迟 ----
    rows = []
    for rep in range(LAT_REPS):
        target = 2048 + (LAT_AMP if rep % 2 == 0 else -LAT_AMP)
        base = statistics.mean(read_pos(bus, sid) for _ in range(3))
        t0 = time.monotonic()
        bus.write(sid, 42, struct.pack("<H", target))       # 带应答的写
        moved_at = None
        while time.monotonic() - t0 < 0.2:
            if abs(read_pos(bus, sid) - base) >= 2:
                moved_at = time.monotonic()
                break
        if moved_at is None:
            rows.append((rep, None))
        else:
            rows.append((rep, (moved_at - t0) * 1000))
        settle(bus, sid, target)
    lat = [r[1] for r in rows if r[1] is not None]
    with open(f"{HERE_DOCS}/latency-2026-09-26.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["rep", "latency_ms"]); w.writerows(rows)
    print(f"\n指令延迟（{len(lat)}/{LAT_REPS} 次有效，写应答后 → 位置动 ≥2 步）：")
    print(f"  min {min(lat):.1f}  avg {statistics.mean(lat):.1f}  "
          f"p95 {sorted(lat)[int(len(lat)*0.95)]:.1f}  max {max(lat):.1f} ms")
    print(f"  ≈ 200 Hz 控制步 {statistics.mean(lat)/5:.1f} 步")

    # ---- 空载转速 ----
    bus.write_u16(sid, 42, SPEED_FROM)
    assert settle(bus, sid, SPEED_FROM), "回起点不到位"
    time.sleep(0.5)
    samples = []
    t0 = time.monotonic()
    bus.write(sid, 42, struct.pack("<H", SPEED_TO))
    while time.monotonic() - t0 < 3.0:
        samples.append(((time.monotonic() - t0) * 1000, read_pos(bus, sid)))
        if len(samples) > 30 and all(abs(p - SPEED_TO) <= 3 for _, p in samples[-30:]):
            break
    with open(f"{HERE_DOCS}/speed-2026-09-26.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["t_ms", "pos"]); w.writerows(samples)
    span = SPEED_TO - SPEED_FROM
    seg = [(t, p) for t, p in samples if SPEED_FROM + 0.1 * span <= p <= SPEED_FROM + 0.9 * span]
    if len(seg) >= 5:
        n = len(seg)
        sx = sum(t for t, _ in seg); sy = sum(p for _, p in seg)
        sxx = sum(t * t for t, _ in seg); sxy = sum(t * p for t, p in seg)
        slope = (n * sxy - sx * sy) / (n * sxx - sx * sx)          # 步/ms
        rpm = slope * 1000 / 4096 * 60
        peak = max((samples[i+1][1]-samples[i][1])/(samples[i+1][0]-samples[i][0])
                   for i in range(len(samples)-1) if samples[i+1][0] > samples[i][0])
        print(f"\n空载转速 @ {volt} V（{len(samples)} 采样，拟合段 {len(seg)} 点）：")
        print(f"  平台斜率 {slope*1000:.0f} 步/s = {rpm:.1f} RPM；瞬时峰值 {peak*1000:.0f} 步/s = {peak*1000/4096*60:.1f} RPM")
        print(f"  行程 {span} 步用时 {samples[-1][0]:.0f} ms（含起停）")
    else:
        print("\n采样太少，转速拟合失败")

    bus.write_u8(sid, 40, 0)
    bus.close()
    print("\n已关扭矩。原始数据：docs/bench/latency-2026-09-26.csv、speed-2026-09-26.csv")


if __name__ == "__main__":
    main()
