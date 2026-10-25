#!/usr/bin/env python3
"""生成 insert_demo.gif: NP-F550 电池装入底座的演示动画（沿中线剖视图）。
依赖: trimesh manifold3d numpy pillow, 同目录 npf550_holder.py
"""
import os
import numpy as np
import trimesh
from PIL import ImageDraw, ImageFont
from npf550_holder import build_parts, render, box, P

OUT = os.path.dirname(os.path.abspath(__file__))
static, moving, cuts, meta = build_parts()
body = trimesh.boolean.difference(
    [trimesh.boolean.union(static, engine='manifold')] + cuts, engine='manifold')
latch = trimesh.boolean.union(moving, engine='manifold')

bl, bw, bt = P['batt_l'], P['batt_w'], P['batt_t']
z0 = meta['z_base']
x_catch = meta['x_catch']
pivot = [meta['x_anchor'], meta['z_arm_bot'], 0]
contact_x = x_catch + P['catch_h']
x_snap = x_catch - bl

HOLDER = (0.55, 0.72, 0.86)
LATCH = (0.95, 0.60, 0.22)
BATT = (0.30, 0.32, 0.36)

half = box(-20, 200, -100, 0.0, -20, 100)
body = trimesh.boolean.difference([body, half], engine='manifold')
latch = trimesh.boolean.difference([latch, half], engine='manifold')


def frame(x_f, text, font, note_font):
    batt = box(x_f, x_f + bl, -bw / 2, bw / 2, z0, z0 + bt)
    batt = trimesh.boolean.difference([batt, half], engine='manifold')
    lift = min(max(contact_x - x_f, 0.0), P['catch_h'])
    if x_f <= x_snap:
        lift = 0.0
    theta = np.arctan2(lift, meta['arm_l'])
    moved = latch.copy()
    moved.apply_transform(trimesh.transformations.rotation_matrix(
        theta, [0, 1, 0], pivot))
    im = render([(body, HOLDER), (moved, LATCH), (batt, BATT)],
                elev=14, azim=-90, W=720, H=480)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 720, 42], fill=(255, 255, 255))
    d.text((16, 8), text, font=font, fill=(30, 30, 30))
    d.text((16, 452), '沿电池中线的剖面演示；橙色为弹性卡扣', font=note_font,
           fill=(110, 110, 110))
    return im


try:
    font = ImageFont.truetype('/System/Library/Fonts/Hiragino Sans GB.ttc', 22)
    note_font = ImageFont.truetype('/System/Library/Fonts/Hiragino Sans GB.ttc', 15)
except OSError:
    font = note_font = ImageFont.load_default()

frames = []
for x in np.linspace(96, contact_x, 7):
    frames.append(frame(x, '1. 电池平放，从开口端水平推入', font, note_font))
for x in np.linspace(contact_x, x_snap, 22)[1:]:
    frames.append(frame(x, '2. 继续推：45° 斜面把卡扣向上顶起', font, note_font))
for x in np.linspace(x_snap, 3.0, 3)[1:]:
    frames.append(frame(x, '3. 推到底，卡扣落下，钩住电池尾端', font, note_font))
for _ in range(6):
    frames.append(frame(3.0, '已锁定。取出：上抬手柄，再水平滑出', font, note_font))

gif = os.path.join(OUT, 'insert_demo.gif')
frames[0].save(gif, save_all=True, append_images=frames[1:],
               duration=120, loop=0, optimize=True)
print('GIF:', gif, len(frames), 'frames,', os.path.getsize(gif) // 1024, 'KB')
frames[14].save(os.path.join(OUT, 'demo_frame.png'))
frames[-1].save(os.path.join(OUT, 'demo_frame_locked.png'))
