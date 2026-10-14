"""Round-trip tests for pointcloud.py. Run from server/: python -m common.test_pointcloud"""
import os
import tempfile

import numpy as np

from common.pointcloud import (edge_mask, fit_floor, level_to_floor, opencv_to_unity,
                        read_ply, unity_to_opencv, unproject, write_ply)


def test_axes():
    # OpenCV: +x right, +y down, +z forward. Unity: +x right, +y up, +z forward.
    right, down, fwd = np.eye(3)
    assert np.allclose(opencv_to_unity(right[None]), [[1, 0, 0]])
    assert np.allclose(opencv_to_unity(down[None]), [[0, -1, 0]])
    assert np.allclose(opencv_to_unity(fwd[None]), [[0, 0, 1]])


def test_round_trip():
    p = np.random.default_rng(0).normal(size=(100, 3))
    assert np.allclose(unity_to_opencv(opencv_to_unity(p)), p)


def test_unproject_reprojects():
    K = np.array([[500.0, 0, 320], [0, 500, 320], [0, 0, 1]])
    depth = np.random.default_rng(1).uniform(1, 5, size=(64, 64))
    pts = unproject(depth, K).reshape(-1, 3)
    uv = (pts @ K.T)[:, :2] / pts[:, 2:]
    u, v = np.meshgrid(np.arange(64) + 0.5, np.arange(64) + 0.5)
    assert np.allclose(uv, np.stack([u, v], -1).reshape(-1, 2))


def test_edge_mask():
    depth = np.ones((10, 10))
    depth[:, 5:] = 3.0
    m = edge_mask(depth)
    assert not m[:, 4:6].any() and m[:, :3].all() and m[:, 7:].all()


def test_level_floor():
    # Floor 1.5 m below a camera pitched 10 deg down, plus a wall.
    rng = np.random.default_rng(2)
    floor = np.c_[rng.uniform(-3, 3, 5000), np.full(5000, -1.5), rng.uniform(1, 6, 5000)]
    wall = np.c_[rng.uniform(-3, 3, 2000), rng.uniform(-1.5, 2, 2000), np.full(2000, 6.0)]
    a = np.radians(10)
    Rx = np.array([[1, 0, 0], [0, np.cos(a), -np.sin(a)], [0, np.sin(a), np.cos(a)]])
    pts = np.r_[floor, wall] @ Rx.T
    n, d = fit_floor(pts)
    leveled, _, h = level_to_floor(pts, n, d)
    assert abs(h - 1.5) < 0.01
    assert np.abs(leveled[:5000, 1]).max() < 0.01


def test_ply_round_trip():
    rng = np.random.default_rng(3)
    p = rng.normal(size=(50, 3)).astype(np.float32)
    c = rng.integers(0, 256, size=(50, 3)).astype(np.uint8)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, 'x.ply')
        write_ply(path, p, c)
        p2, c2 = read_ply(path)
    assert np.array_equal(p, p2) and np.array_equal(c, c2)


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok ', name)
