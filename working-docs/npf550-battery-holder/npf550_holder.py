#!/usr/bin/env python3
"""NP-F550 电池底座（滑入托盘 + 端部机械限位 + 竖向弹性卡扣 + 绑带槽）。

用法:
  python npf550_holder.py            # 生成 npf550_holder.stl 和 preview.png
  python make_insert_gif.py          # 生成 insert_demo.gif 装电池演示
依赖: trimesh manifold3d numpy pillow

坐标: X = 电池长(70.8) 方向, 电池从 +X 端滑入, -X 端是限位挡墙;
      Y = 电池宽(38.6), Z = 电池厚(20.6), 电池平放在底板上。
卡扣是根部在 +X 端的水平悬臂, 插入时钩子的 45° 斜面把臂向上顶起,
电池尾端通过后弹下, 钩子挡住尾端面。解锁: 上抬手柄。
"""
import os
import numpy as np
import trimesh

P = dict(
    batt_l=70.8, batt_w=38.6, batt_t=20.6,
    clearance=0.45,        # 单边配合间隙
    base_t=3.0,            # 底板厚
    wall_t=2.4,            # 侧壁厚
    stop_t=3.0,            # 端部限位挡墙厚
    lip_w=2.0,             # 顶部压边内伸宽度
    lip_t=1.6,             # 压边厚
    lip_gap=0.3,           # 压边与电池顶面间隙
    latch_w=12.0,          # 卡扣宽度(Y)
    latch_t=1.2,           # 悬臂厚(Z)
    arm_l=14.0,            # 悬臂长(X)
    anchor_t=3.0,          # 尾端固定座厚(X)
    catch_h=1.6,           # 咬合面高(Z)
    flange=8.0,            # 底板两侧外伸(安装孔/绑带槽)
    mount_d=3.4,           # M3 过孔
    strap_x1=20.0, strap_x2=56.0,
    strap_l=13.0, strap_w=2.6,
    win_x0=12.0, win_x1=62.0,  # 底板窗口(默认关闭), 需要底部走线/减重时开
    win_halfw=0.0,
)


def box(x0, x1, y0, y1, z0, z1):
    m = trimesh.creation.box([x1 - x0, y1 - y0, z1 - z0])
    m.apply_translation([(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2])
    return m


def prism(poly, a0, a1, axis):
    """凸多边形沿轴拉伸. poly 为 (y,z) 或 (x,z) 坐标, axis='x' 或 'y'."""
    poly = np.asarray(poly, dtype=float)
    n = len(poly)
    if axis == 'x':
        v0 = np.column_stack([np.full(n, a0), poly[:, 0], poly[:, 1]])
        v1 = np.column_stack([np.full(n, a1), poly[:, 0], poly[:, 1]])
    else:
        v0 = np.column_stack([poly[:, 0], np.full(n, a0), poly[:, 1]])
        v1 = np.column_stack([poly[:, 0], np.full(n, a1), poly[:, 1]])
    verts = np.vstack([v0, v1])
    faces = []
    for i in range(1, n - 1):
        faces.append([0, i + 1, i])
        faces.append([n, n + i, n + i + 1])
    for i in range(n):
        j = (i + 1) % n
        faces.append([i, j, n + j])
        faces.append([i, n + j, n + i])
    m = trimesh.Trimesh(verts, faces, process=True)
    m.fix_normals()
    return m


def build_parts(p=P):
    bw, bt = p['batt_w'], p['batt_t']
    c = p['clearance']
    z_base = p['base_t']
    z_batt_top = z_base + bt
    half_cav = bw / 2 + c
    y_wall_out = half_cav + p['wall_t']
    y_out = y_wall_out + p['flange']
    x_stop = p['stop_t']
    x_batt_end = x_stop + p['batt_l']
    x_wall_end = x_batt_end + 0.6
    z_lip_bot = z_batt_top + p['lip_gap'] + p['lip_w'] - c
    z_lip_top = z_lip_bot + p['lip_t']
    z_wall_top = z_lip_top
    x_catch = x_batt_end + 0.15
    z_catch_lo = z_batt_top - p['catch_h']
    z_ramp_hi = z_catch_lo + 2.0
    z_arm_bot = z_batt_top + 1.4
    z_arm_top = z_arm_bot + p['latch_t']
    x_anchor = x_catch + p['arm_l']
    x_end = x_anchor + p['anchor_t']
    hw = p['latch_w'] / 2

    static = [box(0, x_end, -y_out, y_out, 0, z_base),
              box(0, x_stop, -y_wall_out, y_wall_out, z_base, z_wall_top)]
    for s in (-1, 1):
        y0, y1 = sorted([s * half_cav, s * y_wall_out])
        static.append(box(x_stop, x_end, y0, y1, z_base, z_wall_top))
        yi = s * half_cav
        yl = s * (half_cav - p['lip_w'])
        lip_poly = [(yi, z_lip_bot - p['lip_w']), (yi, z_lip_top),
                    (yl, z_lip_top), (yl, z_lip_bot)]
        static.append(prism(lip_poly, x_stop, x_wall_end, 'x'))
    static.append(box(x_anchor, x_end, -y_wall_out, y_wall_out,
                      z_batt_top + 0.6, z_arm_top))

    moving = [box(x_catch, x_anchor, -hw, hw, z_arm_bot, z_arm_top),
              box(x_catch - 4.0, x_catch, -hw, hw, z_arm_bot, z_arm_top)]
    hook_poly = [(x_catch, z_arm_bot), (x_catch, z_catch_lo),
                 (x_catch + 2.0, z_ramp_hi), (x_catch + 2.0, z_arm_bot)]
    moving.append(prism(hook_poly, -hw, hw, 'y'))

    cuts = []
    if p.get('win_halfw', 0) > 0:
        cuts.append(box(p['win_x0'], p['win_x1'], -p['win_halfw'], p['win_halfw'],
                        -1, z_base + 1))
    for x in (8.0, x_end - 8.0):
        for s in (-1, 1):
            cuts.append(trimesh.creation.cylinder(
                p['mount_d'] / 2, 2 * z_base + 2,
                transform=trimesh.transformations.translation_matrix(
                    [x, s * (y_out - 4.0), z_base / 2])))
    for x in (p['strap_x1'], p['strap_x2']):
        for s in (-1, 1):
            yc = s * (y_wall_out + p['flange'] / 2)
            cuts.append(box(x - p['strap_l'] / 2, x + p['strap_l'] / 2,
                            yc - p['strap_w'] / 2, yc + p['strap_w'] / 2,
                            -1, z_base + 1))

    meta = dict(x_stop=x_stop, x_batt_end=x_batt_end, x_catch=x_catch,
                x_anchor=x_anchor, z_arm_bot=z_arm_bot, z_batt_top=z_batt_top,
                z_base=z_base, arm_l=p['arm_l'])
    return static, moving, cuts, meta


def build(p=P):
    static, moving, cuts, _ = build_parts(p)
    body = trimesh.boolean.union(static + moving, engine='manifold')
    return trimesh.boolean.difference([body] + cuts, engine='manifold')


def render(colored, elev, azim, W=760, H=560):
    from PIL import Image
    e, a = np.radians([elev, azim])
    fwd = np.array([np.cos(e) * np.cos(a), np.cos(e) * np.sin(a), np.sin(e)])
    right = np.cross([0, 0, 1], fwd)
    right /= np.linalg.norm(right)
    up = np.cross(fwd, right)
    all_v = np.vstack([m.vertices for m, _ in colored])
    lo, hi = all_v.min(axis=0), all_v.max(axis=0)
    basis = np.stack([right, up, fwd], axis=1)
    all_p = (all_v - (lo + hi) / 2) @ basis
    cx, cy = all_p[:, 0].mean(), all_p[:, 1].mean()
    s = min(W * 0.86 / np.ptp(all_p[:, 0]), H * 0.80 / np.ptp(all_p[:, 1]))
    zbuf = np.full((H, W), -np.inf)
    img = np.full((H, W, 3), 255, dtype=np.uint8)
    for m, color in colored:
        Pr = (m.vertices - (lo + hi) / 2) @ basis
        xs = (Pr[:, 0] - cx) * s + W / 2
        ys = H / 2 - (Pr[:, 1] - cy) * s
        zs = Pr[:, 2]
        tri = m.vertices[m.faces]
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
        light = np.array([0.4, 0.5, 0.75])
        light /= np.linalg.norm(light)
        lam = np.abs(n @ light)
        for k, f in enumerate(m.faces):
            x, y, z = xs[f], ys[f], zs[f]
            x0, x1 = int(max(0, np.floor(x.min()))), int(min(W - 1, np.ceil(x.max())))
            y0, y1 = int(max(0, np.floor(y.min()))), int(min(H - 1, np.ceil(y.max())))
            if x1 < x0 or y1 < y0:
                continue
            gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5,
                                 np.arange(y0, y1 + 1) + 0.5)
            d = (y[1] - y[2]) * (x[0] - x[2]) + (x[2] - x[1]) * (y[0] - y[2])
            if abs(d) < 1e-9:
                continue
            w0 = ((y[1] - y[2]) * (gx - x[2]) + (x[2] - x[1]) * (gy - y[2])) / d
            w1 = ((y[2] - y[0]) * (gx - x[2]) + (x[0] - x[2]) * (gy - y[2])) / d
            w2 = 1 - w0 - w1
            mask = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
            zz = w0 * z[0] + w1 * z[1] + w2 * z[2]
            sub = zbuf[y0:y1 + 1, x0:x1 + 1]
            upd = mask & (zz > sub)
            if not upd.any():
                continue
            sub[upd] = zz[upd]
            col = np.array(color) * (0.35 + 0.65 * lam[k])
            img[y0:y1 + 1, x0:x1 + 1][upd] = (col * 255).astype(np.uint8)
    return Image.fromarray(img)


if __name__ == '__main__':
    out_dir = os.path.dirname(os.path.abspath(__file__))
    m = build()
    stl = os.path.join(out_dir, 'npf550_holder.stl')
    m.export(stl)
    print('STL:', stl)
    print('watertight:', m.is_watertight, ' volume(mm^3): %.0f' % m.volume)
    print('bounding box(mm):', np.round(m.extents, 2))
    batt = box(P['stop_t'], P['stop_t'] + P['batt_l'],
               -P['batt_w'] / 2, P['batt_w'] / 2,
               P['base_t'], P['base_t'] + P['batt_t'])
    clash = trimesh.boolean.intersection([m, batt], engine='manifold').volume
    print('电池就位干涉(mm^3):', round(clash, 4))
    views = [render([(m, (0.55, 0.72, 0.86))], e, a)
             for e, a in [(28, -55), (28, 125)]]
    out = views[0].copy()
    from PIL import Image
    out = Image.new('RGB', (2 * views[0].width, views[0].height), (255, 255, 255))
    out.paste(views[0], (0, 0))
    out.paste(views[1], (views[0].width, 0))
    out.save(os.path.join(out_dir, 'preview.png'))
    print('preview:', os.path.join(out_dir, 'preview.png'))
