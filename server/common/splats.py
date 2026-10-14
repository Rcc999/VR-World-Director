"""Shared helpers for Gaussian splats from a COLMAP capture: reading the
splat .ply and the COLMAP cameras, and the map from COLMAP's world (arbitrary
rotation and scale) to the Unity viewer frame:

- gravity from the cameras' right axes (phones are pitched, rarely rolled),
- floor = the densest height below the cameras, at y = 0,
- scale so the median camera height is --camera_height m,
- spawn (x = z = 0) in the middle of the capture path, +z = first frame's heading.
"""
import os
import subprocess
import tempfile

import numpy as np


def read_gaussian_ply(path):
    """Binary little-endian PLY with one vertex element of scalar properties."""
    types = {'float': '<f4', 'float32': '<f4', 'double': '<f8', 'uchar': 'u1',
             'uint8': 'u1', 'int': '<i4', 'uint': '<u4', 'short': '<i2', 'ushort': '<u2'}
    with open(path, 'rb') as f:
        fields, n, in_vertex = [], None, False
        while (line := f.readline().decode('ascii').strip()) != 'end_header':
            parts = line.split()
            if parts[:1] == ['format'] and parts[1] != 'binary_little_endian':
                raise ValueError(f"unsupported PLY format {parts[1]}")
            if parts[:1] == ['element']:
                in_vertex = parts[1] == 'vertex'
                if in_vertex:
                    n = int(parts[2])
                elif n is None:
                    raise ValueError('vertex must be the first element')
            elif parts[:1] == ['property'] and in_vertex:
                fields.append((parts[2], types[parts[1]]))
        return np.frombuffer(f.read(np.dtype(fields).itemsize * n), dtype=fields, count=n)


def read_colmap_cameras(model_dir):
    """Camera centers and world-space up/forward axes from a COLMAP model."""
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(['colmap', 'model_converter', '--input_path', model_dir,
                        '--output_path', tmp, '--output_type', 'TXT'],
                       check=True, capture_output=True)
        lines = [l for l in open(os.path.join(tmp, 'images.txt'))
                 if l.strip() and not l.startswith('#')]
    centers, rights, ups, fwds = [], [], [], []
    for line in lines[::2]:  # every other line is the 2D point list
        qw, qx, qy, qz, tx, ty, tz = map(float, line.split()[1:8])
        R = quat_to_rot(np.array([qw, qx, qy, qz]))  # world -> camera
        centers.append(-R.T @ np.array([tx, ty, tz]))
        rights.append(R[0])  # camera +x in world
        ups.append(-R[1])    # camera -y (OpenCV up) in world
        fwds.append(R[2])    # camera +z (viewing direction) in world
    return np.array(centers), np.array(rights), np.array(ups), np.array(fwds)


def gravity_up(rights, ups):
    """World up from a hand-held capture. People tilt the phone up and down a
    lot but rarely roll it, so every camera's right axis is ~horizontal: up is
    the direction most orthogonal to all of them (smallest singular vector).
    The mean camera up only picks the sign."""
    up = np.linalg.svd(rights, full_matrices=False)[2][-1]
    return up if up @ ups.mean(axis=0) > 0 else -up


def floor_height(heights, below, bin_size):
    """Height of the floor: the densest height bin under the cameras."""
    h = heights[heights < below]
    hist, edges = np.histogram(h, bins=np.arange(h.min(), below + bin_size, bin_size))
    i = hist.argmax()
    return 0.5 * (edges[i] + edges[i + 1])


def quat_to_rot(q):
    """(..., 4) quaternions (w, x, y, z) -> (..., 3, 3) rotation matrices."""
    q = q / np.linalg.norm(q, axis=-1, keepdims=True)
    w, x, y, z = np.moveaxis(q, -1, 0)
    return np.stack([
        np.stack([1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)], -1),
        np.stack([2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)], -1),
        np.stack([2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)], -1),
    ], -2)


def capture_frame(means, colmap_dir, camera_height):
    """Similarity map from the splat's COLMAP world to the Unity viewer frame,
    p_unity = A @ p + b (A = scale * reflection-rotation, since COLMAP is
    right-handed and Unity left-handed). Also returns the cameras in Unity."""
    centers, rights, ups, fwds = read_colmap_cameras(colmap_dir)
    up = gravity_up(rights, ups)
    fwd = fwds[0] - (fwds[0] @ up) * up  # first frame's heading, made horizontal
    fwd /= np.linalg.norm(fwd)
    down = -up
    right = np.cross(down, fwd)          # OpenCV axes: x = y cross z
    basis = np.stack([right, down, fwd])  # rows: world -> OpenCV-style frame

    # Origin on the floor below the cameras' center; scale from camera height.
    center = centers.mean(axis=0)
    cam_h = (centers - center) @ up
    span = np.ptp(cam_h) + np.ptp(centers @ right) + 1e-6
    floor = floor_height((means - center) @ up, below=cam_h.min(), bin_size=0.01 * span)
    origin = center + floor * up
    scale = camera_height / np.median(cam_h - floor)

    A = scale * np.diag([1.0, -1.0, 1.0]) @ basis  # same as opencv_to_unity
    b = -A @ origin
    # Spawn in the middle of the capture path: x = z = 0 there.
    b -= np.median(centers @ A.T + b, axis=0) * np.array([1.0, 0.0, 1.0])
    return A, b, scale, centers @ A.T + b
