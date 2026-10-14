"""Depth -> colored point cloud, OpenCV -> Unity coordinates, and PLY output.

Conventions:
  OpenCV camera (Puffin-World, most CV code): right-handed, +x right, +y down, +z forward.
  Unity: left-handed, +x right, +y up, +z forward.
Going from one to the other is a single reflection, y -> -y, which also flips
handedness. The same map applies to world-frame points as long as the world
frame follows the OpenCV axes (as Puffin's c2w poses do).
"""
import numpy as np

OPENCV_TO_UNITY = np.diag([1.0, -1.0, 1.0])


def opencv_to_unity(points):
    """(N, 3) OpenCV-frame points -> Unity-frame points."""
    return points @ OPENCV_TO_UNITY.T


def unity_to_opencv(points):
    """Inverse of opencv_to_unity (the reflection is its own inverse)."""
    return points @ OPENCV_TO_UNITY.T


def unproject(depth, K):
    """(H, W) depth along the optical axis + 3x3 intrinsics -> (H, W, 3)
    points in the OpenCV camera frame."""
    h, w = depth.shape
    u, v = np.meshgrid(np.arange(w) + 0.5, np.arange(h) + 0.5)
    x = (u - K[0, 2]) / K[0, 0] * depth
    y = (v - K[1, 2]) / K[1, 1] * depth
    return np.stack([x, y, depth], axis=-1)


def edge_mask(depth, rel_thresh=0.04):
    """True where depth is smooth. Pixels on depth discontinuities are
    'flying pixels' smeared between foreground and background; drop them."""
    d = np.pad(depth, 1, mode='edge')
    diffs = [np.abs(d[1:-1, 1:-1] - d[1 + dy:d.shape[0] - 1 + dy,
                                       1 + dx:d.shape[1] - 1 + dx])
             for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1))]
    return np.max(diffs, axis=0) / np.maximum(depth, 1e-6) < rel_thresh


def fit_floor(points, up_hint=(0.0, 1.0, 0.0), max_tilt_deg=35.0,
              inlier_dist=0.03, iters=2000, seed=0):
    """RANSAC the floor plane in Unity-frame points. Only planes whose normal
    is within max_tilt_deg of up_hint count, and among those the lowest one
    with enough support wins (so a tabletop does not beat the floor).
    Returns (unit normal pointing up, offset d) with normal . p + d = 0."""
    rng = np.random.default_rng(seed)
    up = np.asarray(up_hint, dtype=np.float64)
    pts = points[rng.choice(len(points), min(len(points), 50_000), replace=False)]
    cos_max = np.cos(np.radians(max_tilt_deg))
    best, best_score = None, -np.inf
    for _ in range(iters):
        a, b, c = pts[rng.choice(len(pts), 3, replace=False)]
        n = np.cross(b - a, c - a)
        norm = np.linalg.norm(n)
        if norm < 1e-9:
            continue
        n /= norm
        if n @ up < 0:
            n = -n
        if n @ up < cos_max:
            continue
        d = -n @ a
        inliers = np.abs(pts @ n + d) < inlier_dist
        if inliers.mean() < 0.05:
            continue
        # Prefer low planes: score = support minus height of the plane.
        score = inliers.mean() - 0.1 * (-d)
        if score > best_score:
            best, best_score = (n, d, inliers), score
    if best is None:
        raise RuntimeError("no floor plane found")
    n, _, inliers = best
    # Refine with least squares on the inliers.
    sub = pts[inliers]
    centroid = sub.mean(axis=0)
    n = np.linalg.svd(sub - centroid)[2][-1]
    if n @ up < 0:
        n = -n
    return n, -n @ centroid


def level_to_floor(points, normal, d):
    """Rotate so the floor normal becomes +y and translate the floor to y=0.
    The rotation is about the camera origin, so the camera stays at x=z=0
    and ends up at y = its height above the floor."""
    up = np.array([0.0, 1.0, 0.0])
    v = np.cross(normal, up)
    s, c = np.linalg.norm(v), normal @ up
    if s < 1e-9:
        R = np.eye(3)
    else:
        vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
        R = np.eye(3) + vx + vx @ vx * ((1 - c) / s ** 2)
    leveled = points @ R.T
    leveled[:, 1] += d  # camera height above the floor
    return leveled, R, d


def write_ply(path, points, colors, sizes=None):
    """Binary little-endian PLY: float x,y,z + uchar red,green,blue, plus an
    optional float `size` (point diameter in meters) that the Unity viewer
    uses instead of its distance-based size."""
    points = np.asarray(points, dtype='<f4')
    colors = np.asarray(colors, dtype=np.uint8)
    fields = [('x', '<f4'), ('y', '<f4'), ('z', '<f4'),
              ('red', 'u1'), ('green', 'u1'), ('blue', 'u1')]
    if sizes is not None:
        fields.append(('size', '<f4'))
    vertex = np.empty(len(points), dtype=fields)
    vertex['x'], vertex['y'], vertex['z'] = points.T
    vertex['red'], vertex['green'], vertex['blue'] = colors.T
    if sizes is not None:
        vertex['size'] = sizes
    header = ("ply\nformat binary_little_endian 1.0\n"
              f"element vertex {len(vertex)}\n"
              "property float x\nproperty float y\nproperty float z\n"
              "property uchar red\nproperty uchar green\nproperty uchar blue\n"
              + ("property float size\n" if sizes is not None else "")
              + "end_header\n")
    with open(path, 'wb') as f:
        f.write(header.encode('ascii'))
        f.write(vertex.tobytes())


def read_ply(path):
    """Reader for the format write_ply produces (used by tests)."""
    with open(path, 'rb') as f:
        n = None
        while (line := f.readline().decode('ascii').strip()) != 'end_header':
            if line.startswith('element vertex'):
                n = int(line.split()[-1])
        vertex = np.frombuffer(f.read(), count=n, dtype=[
            ('x', '<f4'), ('y', '<f4'), ('z', '<f4'),
            ('red', 'u1'), ('green', 'u1'), ('blue', 'u1')])
    points = np.stack([vertex['x'], vertex['y'], vertex['z']], axis=-1)
    colors = np.stack([vertex['red'], vertex['green'], vertex['blue']], axis=-1)
    return points, colors
