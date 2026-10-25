#!/usr/bin/env python3
"""Offline verification for the local `system`-channel patch in raw_telemetry.py.

Exercises the whole path - ssh spawn, block framing, parsing, emit - against a
local stand-in for the board, so no robot access is needed. Also replays the
real remote script on this machine (where /proc is absent) to prove the parser
degrades gracefully instead of raising.
"""
import subprocess
import sys
import threading
import time

CONSOLE = ("/Users/jin/Projects/microduck-build/reference/Microduck-kissqy/"
           "release-assets/Microduck-Console-R17-V167")
sys.path.insert(0, CONSOLE)

import raw_telemetry as rt  # noqa: E402

# Same key=value protocol as the real script, with /proc-like fixed values and
# a monotonically moving /proc/stat line so cpu_percent is non-degenerate.
FAKE_BOARD = r"""
while :; do
  printf 'hostname=%s\n' radxa-zero3
  printf 'boot_id=%s\n' 11111111-2222-3333-4444-555555555555
  printf 'uptime_s=%s\n' 1234.56
  printf 'memory_total=%s\n' 2000000000
  printf 'memory_available=%s\n' 1500000000
  N=$(date +%s); printf 'cpu_stat=%s\n' "cpu  $((N*10)) 0 0 $((N*3)) 0 0 0 0"
  printf 'cpu_temp_milli=%s\n' 46789
  printf 'robotd_identity=%s\n' "$(printf '{"revision":"1fa8438","channel":"control.40"}' | base64 | tr -d '\n')"
  printf 'END\n'
  sleep 1
done
"""

failures = []


def check(name, condition, detail=""):
    print(f"  [{'ok' if condition else 'FAIL'}] {name}{'  ' + detail if detail else ''}")
    if not condition:
        failures.append(name)


print("1. 假板子端到端（ssh 进程 → 分帧 → 解析 → emit）")
real_script, real_command, real_options = rt.SYSTEM_SCRIPT, rt.ssh_command, rt.ssh_process_options
rt.SYSTEM_SCRIPT = FAKE_BOARD
rt.ssh_command = lambda target: ["sh", "-c"]
rt.ssh_process_options = lambda target: {}

events, stop = [], threading.Event()
worker = threading.Thread(target=rt.system_loop,
                          args=("radxa@fake", events.append, stop), daemon=True)
worker.start()
time.sleep(4.5)
stop.set()
worker.join(timeout=10)
rt.SYSTEM_SCRIPT, rt.ssh_command, rt.ssh_process_options = real_script, real_command, real_options

samples = [e for e in events if isinstance(e.get("data"), dict)]
errors = [e for e in events if "error" in e]
check("循环收到 >=2 个 system 事件", len(samples) >= 2, f"收到 {len(samples)}")
check("没有 error 事件", not errors, str(errors[:1]))
check("stop 后线程退出（无泄漏）", not worker.is_alive())

if samples:
    first = samples[0]["data"]
    check("hostname", first.get("hostname") == "radxa-zero3", repr(first.get("hostname")))
    check("cpu_temp_c 毫摄氏度→摄氏度", first.get("cpu_temp_c") == 46.789, repr(first.get("cpu_temp_c")))
    check("memory_total 为整数", first.get("memory_total") == 2000000000, repr(first.get("memory_total")))
    check("uptime_s", first.get("uptime_s") == 1234.56, repr(first.get("uptime_s")))
    check("robotd identity 已解出", (first.get("identities") or {}).get("robotd", {}).get("channel") == "control.40",
          repr(first.get("identities")))
    check("首帧无 cpu_percent（需要两个采样点）", "cpu_percent" not in first)
    percents = [s["data"].get("cpu_percent") for s in samples if "cpu_percent" in s["data"]]
    check("后续帧有 cpu_percent 且在 0-100", bool(percents) and all(0 <= p <= 100 for p in percents),
          repr(percents[:3]))
    check("事件通道名为 system", all(s.get("channel") == "system" for s in samples))

print("\n2. 真实远端脚本在本机重放（无 /proc，验证不崩）")
proc = subprocess.Popen(["sh", "-c", real_script], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
block = []
try:
    deadline = time.time() + 10
    while time.time() < deadline:
        line = proc.stdout.readline().decode("utf-8", "replace").rstrip("\n")
        if line == "END":
            break
        block.append(line)
finally:
    proc.kill()
data, counters = rt.system_sample("\n".join(block))
check("解析未抛异常且返回 dict", isinstance(data, dict), repr(block[:3]))
check("无 /proc 时不产生假温度", "cpu_temp_c" not in data)
check("hostname 仍可读出", data.get("hostname") == subprocess.run(
    ["hostname"], capture_output=True, text=True).stdout.strip(), repr(data.get("hostname")))

print("\n3. 解析器边界")
check("空块", rt.system_sample("")[0] == {})
check("缺 END 的残块不崩", isinstance(rt.system_sample("hostname=x")[0], dict))
check("非法数字被忽略", rt.system_sample("uptime_s=abc\nmemory_total=\ncpu_temp_milli=NaN")[0] == {})
check("温度已是摄氏度时不再除 1000", rt.system_sample("cpu_temp_milli=47.5")[0]["cpu_temp_c"] == 47.5)
check("坏 base64 被忽略", "identities" not in rt.system_sample("robotd_identity=!!!not-base64!!!")[0])
check("cpu_counters 拒绝非 cpu 行", rt.cpu_counters("intr 1 2 3") is None)
check("cpu_counters 正常", rt.cpu_counters("cpu 1 2 3 4 5 6 7 8 9") == (36, 9))

print()
if failures:
    print(f"失败 {len(failures)} 项: {failures}")
    sys.exit(1)
print("全部通过")
