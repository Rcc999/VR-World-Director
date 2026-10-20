"""Fusion -> Unity export check on a synthetic room, no GPU or weights needed.

Renders exact depth for the same pan + walk paths scenes.py generates, inside
a gravity-aligned box seen by a camera pitched down like a real seed photo,
in arbitrary depth units. The exported scene_unity.ply must come out in
meters with the floor at y = 0 and the room at its true size.

    python -m generation.test_scenes      (from server/, Puffin env)
"""
import argparse
import json
import math
import tempfile
from pathlib import Path

import numpy as np

from generation import scenes

RES = 160
PITCH = -0.185            # radians, looking down (as Puffin estimated for test-room0)
UNITS_PER_M = 0.5         # generated depth is in arbitrary units
CAM_H = 1.5               # meters above the floor
ROOM = dict(x=(-2.0, 2.0), y=(-1.2, CAM_H), z=(-2.5, 3.0))  # meters, OpenCV axes (y down)


def render(c2w, K):
    """z-depth + face colors of the box room seen from c2w (box units)."""
    lo = np.array([ROOM['x'][0], ROOM['y'][0], ROOM['z'][0]]) * UNITS_PER_M
    hi = np.array([ROOM['x'][1], ROOM['y'][1], ROOM['z'][1]]) * UNITS_PER_M
    u, v = np.meshgrid(np.arange(RES) + 0.5, np.arange(RES) + 0.5)
    rays = np.stack([u, v, np.ones_like(u)], -1) @ np.linalg.inv(K).T  # z = 1
    d = rays @ c2w[:3, :3].T
    o = c2w[:3, 3]
    with np.errstate(divide='ignore'):
        t = np.where(d > 0, (hi - o) / d, (lo - o) / d)
    t[~np.isfinite(t)] = np.inf
    face = t.argmin(-1)
    depth = t.min(-1).astype(np.float32)
    palette = np.array([[200, 60, 60], [60, 200, 60], [60, 60, 200]], np.uint8)
    rgb = palette[face] + (np.sign(d[..., 0]) > 0)[..., None].astype(np.uint8) * 40
    return depth, rgb


def main():
    K = np.array([[RES / (2 * math.tan(0.45)), 0, RES / 2],
                  [0, RES / (2 * math.tan(0.45)), RES / 2], [0, 0, 1.0]])
    c, s = math.cos(PITCH), math.sin(PITCH)
    seed = np.eye(4)
    seed[:3, :3] = [[1, 0, 0], [0, c, -s], [0, s, c]]   # pitch about camera x
    up = scenes.gravity_up(PITCH)
    pan = scenes.pan_poses(57, 6.5, up)
    walk = scenes.walk_poses(15, 0.04 * UNITS_PER_M * 2.0, up)

    raw = {}
    for tag, poses in (('pan', pan), ('walk', walk)):
        rendered = [render(seed @ p, K) for p in poses]
        raw[f'{tag}_depths'] = np.stack([r[0] for r in rendered]).astype(np.float16)
        raw[f'{tag}_frames'] = np.stack([r[1] for r in rendered])
        raw[f'{tag}_poses'] = np.stack(poses)
    # The walk run's depth gauge drifts from the pan's; fusion must undo it.
    raw['walk_depths'] = (raw['walk_depths'].astype(np.float32) * 1.3).astype(np.float16)

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        np.savez(out / 'raw.npz', K=K, cam=np.array([0, PITCH, 0.9, 0]), up=up, **raw)
        (out / 'meta.json').write_text('{}')
        scenes.fuse_scene(argparse.Namespace(camera_height=CAM_H), out)
        from common.pointcloud import read_ply
        pts, _ = read_ply(out / 'scene_unity.ply')
        meta = json.loads((out / 'scene.json').read_text())

    lo, hi = np.percentile(pts, [0.5, 99.5], axis=0)
    expect_lo = np.array([ROOM['x'][0], 0.0, ROOM['z'][0]])
    expect_hi = np.array([ROOM['x'][1], CAM_H - ROOM['y'][0], ROOM['z'][1]])
    print(f"extent lo {np.round(lo, 2)} (expect {expect_lo})")
    print(f"extent hi {np.round(hi, 2)} (expect {expect_hi})")
    print(f"floor {meta['floor_fit']}, {meta['floor_vs_gravity_deg']} deg off gravity, "
          f"scale x{meta['scale_to_meters']:.3f} (expect {1 / UNITS_PER_M})")
    floor_band = np.mean(np.abs(pts[:, 1]) < 0.05)
    assert abs(meta['scale_to_meters'] - 1 / UNITS_PER_M) < 0.05, 'scale'
    # The camera looks down, so the ceiling is never seen: walls end below it.
    assert np.allclose(lo, expect_lo, atol=0.1), 'extent (min)'
    assert np.allclose(hi[[0, 2]], expect_hi[[0, 2]], atol=0.1), 'extent (x/z max)'
    assert CAM_H < hi[1] <= expect_hi[1] + 0.05, 'extent (height)'
    assert floor_band > 0.05, f'only {floor_band:.1%} of points on y=0'
    cam0 = np.array(meta['trajectories_unity_c2w']['pan'][0])
    assert np.allclose(cam0[:3, 3], [0, CAM_H, 0], atol=0.02), f'seed camera at {cam0[:3, 3]}'
    fwd = cam0[:3, 2]
    assert fwd[2] > 0.9 and fwd[1] < 0, f'seed camera should look +z, slightly down: {fwd}'
    walk_end = np.array(meta['trajectories_unity_c2w']['walk'][-1])[:3, 3]
    assert abs(walk_end[1] - CAM_H) < 0.02 and walk_end[2] > 0, f'walk ends at {walk_end}'
    print('ok')


if __name__ == '__main__':
    main()
