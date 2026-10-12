# -*- coding: utf-8 -*-
"""FD 风格舵机调试台后端（界面仿飞特 FT SCServo Debug，见同目录 index.html）。

  python server.py                                    # 自动选第一个 usbmodem 串口，1 Mbps
  python server.py --port /dev/cu.usbmodemXXX --baud 1000000
  python server.py --http-port 8081

浏览器开 http://127.0.0.1:8081 。协议层见 feetech.py（从 microduck-replica 原样复制）。
数据分析「导出」写在同目录 record.txt（CSV）。
"""
import argparse
import asyncio
import csv
import json
import os
import threading
import time

import uvicorn
from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocketDisconnect

import feetech

HERE = os.path.dirname(os.path.abspath(__file__))
BUS = None            # feetech.FeetechBus，没打开是 None
SELECTED = None       # 选中的舵机 ID
FOUND = []            # 上次搜索到的 ID
TORQUE = {}           # id -> 0/1，选中时读一次，之后跟着操作走
LAST_SET = {"acc": 50, "speed": 1000, "time": 0}   # 自动调试沿用上次「设置」的参数
CLIENTS = set()
LOOP = None           # uvicorn 的 event loop，第一个 WS 客户端连上时拿到
POLL_DT = 0.05        # 状态轮询 20 Hz
_stop_auto = threading.Event()
_auto_thread = None
_rec = {"fp": None, "writer": None, "deadline": 0.0, "rows": 0, "path": os.path.join(HERE, "record.txt")}


# ---- 串口 ----
def list_ports():
    try:
        from serial.tools import list_ports as lp
        return [{"device": p.device, "desc": p.description or ""} for p in lp.comports()]
    except Exception:
        return []


def close_bus():
    global BUS, SELECTED, FOUND
    stop_auto()
    stop_record()
    if BUS:
        try:
            BUS.close()
        except Exception:
            pass
    BUS, SELECTED, FOUND = None, None, []


def open_bus(port, baud, timeout_ms):
    close_bus()
    global BUS
    BUS = feetech.FeetechBus(port, baud=baud, timeout=max(0.005, timeout_ms / 1000.0))
    return True


# ---- 异步写（REG_WRITE + ACTION），feetech.py 只有常量，这里补包装 ----
def reg_write(sid, addr, data):
    with BUS._io:
        BUS._send(sid, feetech.REG_WRITE, bytes([addr]) + bytes(data))
        try:
            BUS._read_status(sid)
        except feetech.BusError:
            pass


def action(sid):
    with BUS._io:
        BUS._send(sid, feetech.ACTION)
        try:
            BUS._read_status(sid)
        except feetech.BusError:
            pass


# ---- 广播 ----
async def _send_all(text):
    dead = []
    for ws in list(CLIENTS):
        try:
            await ws.send_text(text)
        except Exception:
            dead.append(ws)
    for ws in dead:
        CLIENTS.discard(ws)


def broadcast(obj):
    if LOOP and CLIENTS:
        asyncio.run_coroutine_threadsafe(_send_all(json.dumps(obj, ensure_ascii=False)), LOOP)


# ---- 记录 ----
def stop_record():
    if _rec["fp"]:
        try:
            _rec["fp"].close()
        except Exception:
            pass
    _rec.update(fp=None, writer=None, deadline=0.0)
    broadcast({"type": "record", "active": False, "rows": _rec["rows"], "path": _rec["path"]})


def start_record(seconds):
    stop_record()
    fp = open(_rec["path"], "w", newline="", encoding="utf-8")
    w = csv.writer(fp)
    w.writerow(["time", "id", "pos", "speed", "load", "volt", "temp", "current_ma"])
    _rec.update(fp=fp, writer=w, deadline=time.time() + seconds, rows=0)
    broadcast({"type": "record", "active": True, "seconds": seconds, "path": _rec["path"]})


# ---- 自动调试 ----
def stop_auto():
    _stop_auto.set()


def _auto_loop(lo, hi, steps, delay_ms):
    seq = [lo, hi] if steps <= 1 else \
        [round(lo + (hi - lo) * i / steps) for i in range(steps + 1)] + \
        [round(hi - (hi - lo) * i / steps) for i in range(1, steps)]
    while not _stop_auto.is_set():
        for p in seq:
            if _stop_auto.is_set() or not BUS or SELECTED is None:
                return
            try:
                write_goal_block(SELECTED, p, LAST_SET["acc"], LAST_SET["speed"], LAST_SET["time"])
            except feetech.BusError:
                pass
            _stop_auto.wait(delay_ms / 1000.0)


def start_auto(lo, hi, steps, delay_ms):
    global _auto_thread
    stop_auto()
    if _auto_thread:
        _auto_thread.join(timeout=1)
    _stop_auto.clear()
    _auto_thread = threading.Thread(target=_auto_loop, args=(lo, hi, steps, delay_ms), daemon=True)
    _auto_thread.start()


def write_goal_block(sid, goal, acc, speed, time_ms):
    """41..47 = 加速度(1) 目标位置(2) 时间(2) 速度(2)，跟 servo-web 同一套写法。"""
    import struct
    data = bytes([max(0, min(254, acc))]) + struct.pack("<H", goal & 0xFFFF) \
        + struct.pack("<H", time_ms & 0xFFFF) + struct.pack("<H", speed & 0xFFFF)
    BUS.write(sid, 41, data)


# ---- 状态轮询线程 ----
def poll_loop():
    while True:
        time.sleep(POLL_DT)
        bus, sid = BUS, SELECTED
        if not bus or sid is None:
            continue
        try:
            st = bus.state(sid)
            msg = {"type": "state", "t": round(time.time(), 3), "id": sid,
                   "torque": TORQUE.get(sid, 0), **st}
        except feetech.BusError as e:
            msg = {"type": "state", "t": round(time.time(), 3), "id": sid, "error": str(e)}
        broadcast(msg)
        if _rec["writer"]:
            if time.time() < _rec["deadline"] and "pos" in msg:
                _rec["writer"].writerow([msg["t"], sid, msg["pos"], msg["speed"], msg["load"],
                                         msg["volt"], msg["temp"], msg["current_ma"]])
                _rec["rows"] += 1
            else:
                stop_record()


# ---- REST ----
async def index(request):
    return FileResponse(os.path.join(HERE, "index.html"), headers={"Cache-Control": "no-store"})


def api_ports(request):
    return JSONResponse({"ports": list_ports(), "open": bool(BUS)})


def api_open(request):
    q = request.query_params
    try:
        open_bus(q["port"], int(q.get("baud", 1_000_000)), int(q.get("timeout", 25)))
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"{type(e).__name__}: {e}"}, status_code=400)


def api_close(request):
    close_bus()
    return JSONResponse({"ok": True})


def api_scan(request):
    if not BUS:
        return JSONResponse({"error": "串口没打开"}, status_code=400)
    global FOUND
    servos = []
    for sid in range(0, 21):
        if BUS.ping(sid) is not None:
            try:
                fw = f"{BUS.read_u8(sid, 0)}.{BUS.read_u8(sid, 1)}"
            except feetech.BusError:
                fw = "?"
            servos.append({"id": sid, "model": f"固件 {fw}"})
    FOUND = [s["id"] for s in servos]
    return JSONResponse({"servos": servos})


# ---- WebSocket ----
def handle(cmd):
    """WS 指令，同步执行（starlette 把 sync 路由跑在线程池，这里直接被 WS 协程调，操作都是毫秒级）。"""
    global SELECTED
    op = cmd.get("op")
    if not BUS and op not in ("ports",):
        return {"type": "error", "msg": "串口没打开"}
    if op == "select":
        sid = int(cmd["id"])
        SELECTED = sid
        try:
            TORQUE[sid] = BUS.read_u8(sid, 40)
        except feetech.BusError:
            TORQUE[sid] = 0
        return {"type": "selected", "id": sid, "torque": TORQUE[sid]}
    if op == "set":
        goal, acc = int(cmd["goal"]), int(cmd.get("acc", LAST_SET["acc"]))
        speed, tms = int(cmd.get("speed", LAST_SET["speed"])), int(cmd.get("time", LAST_SET["time"]))
        LAST_SET.update(acc=acc, speed=speed, time=tms)
        ids = FOUND if cmd.get("sync") and FOUND else [SELECTED]
        import struct
        data = bytes([max(0, min(254, acc))]) + struct.pack("<H", goal & 0xFFFF) \
            + struct.pack("<H", tms & 0xFFFF) + struct.pack("<H", speed & 0xFFFF)
        if cmd.get("sync") and len(ids) > 1:
            BUS.sync_write(41, 7, [(i, data) for i in ids])
        else:
            for i in ids:
                BUS.write(i, 41, data)
        return {"type": "ok", "what": f"set {ids} goal={goal}"}
    if op == "goal":    # 滑块拖动：只写目标位置
        import struct
        BUS.write(SELECTED, 42, struct.pack("<H", int(cmd["goal"]) & 0xFFFF))
        return None
    if op == "torque":
        on = int(cmd["on"])
        ids = FOUND if cmd.get("sync") and FOUND else [SELECTED]
        for i in ids:
            BUS.write_u8(i, 40, on)
            TORQUE[i] = on
        return {"type": "ok", "what": f"torque {on} {ids}"}
    if op == "reg_write":
        import struct
        goal, acc = int(cmd["goal"]), int(cmd.get("acc", LAST_SET["acc"]))
        speed, tms = int(cmd.get("speed", LAST_SET["speed"])), int(cmd.get("time", LAST_SET["time"]))
        data = bytes([max(0, min(254, acc))]) + struct.pack("<H", goal & 0xFFFF) \
            + struct.pack("<H", tms & 0xFFFF) + struct.pack("<H", speed & 0xFFFF)
        reg_write(SELECTED, 41, data)
        return {"type": "ok", "what": "异步写入（待发 ACTION）"}
    if op == "action":
        action(SELECTED)
        return {"type": "ok", "what": "ACTION 已发"}
    if op == "auto_scan":
        start_auto(int(cmd["from"]), int(cmd["to"]), 1, int(cmd["delay"]))
        return {"type": "auto", "active": True}
    if op == "auto_step":
        start_auto(int(cmd["from"]), int(cmd["to"]), int(cmd["steps"]), int(cmd["delay"]))
        return {"type": "auto", "active": True}
    if op == "auto_stop":
        stop_auto()
        return {"type": "auto", "active": False}
    if op == "record":
        start_record(max(1, int(cmd.get("seconds", 30))))
        return None
    if op == "record_stop":
        stop_record()
        return None
    return {"type": "error", "msg": f"未知指令 {op}"}


async def ws_endpoint(ws):
    global LOOP
    LOOP = asyncio.get_running_loop()
    await ws.accept()
    CLIENTS.add(ws)
    try:
        await ws.send_text(json.dumps({
            "type": "hello", "ports": list_ports(), "open": bool(BUS),
            "selected": SELECTED, "found": FOUND}, ensure_ascii=False))
        while True:
            cmd = json.loads(await ws.receive_text())
            try:
                r = handle(cmd)
                if r:
                    if cmd.get("op") == "select":
                        broadcast(r)      # 选中状态所有页面同步
                    else:
                        await ws.send_text(json.dumps(r, ensure_ascii=False))
            except feetech.BusError as e:
                await ws.send_text(json.dumps({"type": "error", "msg": str(e)}, ensure_ascii=False))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        CLIENTS.discard(ws)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", help="串口，不给就自动选第一个 usbmodem/usbserial")
    ap.add_argument("--baud", type=int, default=1_000_000)
    ap.add_argument("--timeout", type=int, default=25, help="串口读超时 ms")
    ap.add_argument("--http-port", type=int, default=8081)
    a = ap.parse_args()

    port = a.port
    if not port:
        for p in list_ports():
            if "usbmodem" in p["device"] or "usbserial" in p["device"]:
                port = p["device"]
                break
    if port:
        try:
            open_bus(port, a.baud, a.timeout)
            print(f"串口 {port} @ {a.baud} 已打开")
        except Exception as e:
            print(f"串口 {port} 打不开（{e}），页面里可以重选")
    else:
        print("没找到串口，页面顶栏选一个再「打开」")
    threading.Thread(target=poll_loop, daemon=True).start()
    print(f"FD 风格调试台 · 浏览器开 http://127.0.0.1:{a.http_port}")
    uvicorn.run(Starlette(routes=[
        Route("/", index),
        Route("/api/ports", api_ports),
        Route("/api/open", api_open, methods=["POST"]),
        Route("/api/close", api_close, methods=["POST"]),
        Route("/api/scan", api_scan, methods=["POST"]),
        WebSocketRoute("/ws", ws_endpoint),
    ]), host="127.0.0.1", port=a.http_port, log_level="warning")


if __name__ == "__main__":
    main()
