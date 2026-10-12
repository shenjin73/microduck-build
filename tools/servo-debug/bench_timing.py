# -*- coding: utf-8 -*-
"""HD-1910 总线时序测试：单颗 sync_read 15 字节连发，测单包往返耗时，外推 16 设备 50 Hz 预算。

  python bench_timing.py [--port /dev/cu.usbmodemXXX] [--id 1] [--n 500]

50 Hz 控制要求 15 舵机 + 1 IMU 一轮读写 < 20 ms。总线上每颗设备一个应答包，
一轮耗时 ≈ 单包耗时 × 设备数（写只有 1 个广播包）。
"""
import argparse
import statistics
import time

import feetech


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/cu.usbmodem5C842873721")
    ap.add_argument("--id", type=int, default=1)
    ap.add_argument("--n", type=int, default=500)
    a = ap.parse_args()
    bus = feetech.FeetechBus(a.port, baud=1_000_000)

    ts = []
    fails = 0
    for _ in range(a.n):
        t0 = time.monotonic()
        r = bus.sync_read([a.id], 56, 15)
        ts.append((time.monotonic() - t0) * 1000)
        if r[a.id] is None:
            fails += 1
        time.sleep(0.001)

    ts.sort()
    avg = statistics.mean(ts)
    p99 = ts[int(len(ts) * 0.99)]
    print(f"sync_read 15 字节 × {a.n} 次（失败 {fails}）：")
    print(f"  min {ts[0]:.2f}  avg {avg:.2f}  p99 {p99:.2f}  max {ts[-1]:.2f} ms")
    print(f"总线统计: {bus.stats}")
    for dev in (1, 15, 16):
        est = avg * dev + 1.0        # +1ms 给 1 个广播写包和间隔
        print(f"  {dev:2d} 设备一轮 ≈ {est:5.1f} ms → 上限 {1000/est:4.0f} Hz"
              + ("   ✓ 50 Hz 有" + f" {20 - est:.1f} ms 余量" if est < 20 else "   ✗ 超 20 ms"))
    bus.close()


if __name__ == "__main__":
    main()
