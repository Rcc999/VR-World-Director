"""Gaussian splat .ply (Brush / 3DGS export) -> a smaller splat .ply for the
Unity Gaussian Splatting renderer, plus the Transform that places it in the
viewer frame (floor at y=0, meters, spawn at x=z=0, same as splat_to_points).

The splats themselves stay in COLMAP coordinates: rotating spherical harmonics
is not needed because the renderer applies the GameObject's transform
(including the mirror from right- to left-handed axes, as a negative scale).

Pruning for a standalone headset (every splat costs sorting and blending every
frame, for both eyes):
- drop faint splats (opacity < --min_opacity),
- drop splats outside --radius m from the capture center or below the floor,
- keep at most --max_splats, ranked by opacity x footprint area.

Usage:
    python -m splat_gaussians.splat_for_unity outputs/room_splat/splat_15000.ply \
        --colmap outputs/room_splat/sparse/0 --out outputs/room_splat/unity/room-splat.ply
Writes room-splat.ply and room-splat.transform.json.
"""
import argparse
import json
import os

import numpy as np

from common.splats import capture_frame, read_gaussian_ply


def rot_to_quat(R):
    """3x3 rotation matrix -> quaternion (x, y, z, w)."""
    w = np.sqrt(max(0.0, 1 + R[0, 0] + R[1, 1] + R[2, 2])) / 2
    x = np.copysign(np.sqrt(max(0.0, 1 + R[0, 0] - R[1, 1] - R[2, 2])) / 2, R[2, 1] - R[1, 2])
    y = np.copysign(np.sqrt(max(0.0, 1 - R[0, 0] + R[1, 1] - R[2, 2])) / 2, R[0, 2] - R[2, 0])
    z = np.copysign(np.sqrt(max(0.0, 1 - R[0, 0] - R[1, 1] + R[2, 2])) / 2, R[1, 0] - R[0, 1])
    return np.array([x, y, z, w])


def unity_transform(A, b):
    """p_unity = A @ p + b, with A = s * (mirror-rotation), as a Unity
    Transform: position b, rotation R, scale (s, s, -s), A = R @ diag(s, s, -s)."""
    s = np.cbrt(abs(np.linalg.det(A)))
    R = A / s @ np.diag([1.0, 1.0, -1.0])
    assert np.allclose(R @ R.T, np.eye(3), atol=1e-6) and np.linalg.det(R) > 0
    return {'position': b.tolist(), 'rotation': rot_to_quat(R).tolist(),
            'scale': [s, s, -s]}


def write_like(path, src_path, records):
    """Write `records` with the same header (properties) as the source PLY."""
    with open(src_path, 'rb') as f:
        header = []
        while (line := f.readline().decode('ascii')).strip() != 'end_header':
            header.append(f"element vertex {len(records)}\n"
                          if line.startswith('element vertex') else line)
    with open(path, 'wb') as f:
        f.write(''.join(header + ['end_header\n']).encode('ascii'))
        f.write(records.tobytes())


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('splat_ply')
    p.add_argument('--colmap', required=True, help='COLMAP model dir (sparse/0)')
    p.add_argument('--out', required=True, help='output .ply (a .transform.json goes next to it)')
    p.add_argument('--camera_height', type=float, default=1.45,
                   help='median capture height above the floor, in meters')
    p.add_argument('--min_opacity', type=float, default=0.05)
    p.add_argument('--radius', type=float, default=6.0,
                   help='drop splats farther than this from the capture center (m)')
    p.add_argument('--max_splats', type=int, default=300_000,
                   help='headset budget; ~300k is the reported limit on a Quest 3')
    args = p.parse_args()

    g = read_gaussian_ply(args.splat_ply)
    opacity = 1 / (1 + np.exp(-g['opacity']))
    g = g[opacity >= args.min_opacity]
    opacity = opacity[opacity >= args.min_opacity]
    means = np.stack([g['x'], g['y'], g['z']], axis=1).astype(np.float64)
    print(f"{len(g)} splats with opacity >= {args.min_opacity}")

    A, b, scale, cams = capture_frame(means, args.colmap, args.camera_height)
    pts = means @ A.T + b
    inside = ((np.linalg.norm(pts[:, [0, 2]], axis=1) < args.radius)
              & (pts[:, 1] > -0.5) & (pts[:, 1] < 8))
    g, opacity = g[inside], opacity[inside]
    print(f"{len(g)} inside {args.radius} m")

    if len(g) > args.max_splats:
        scales = np.sort(np.exp(np.stack([g['scale_0'], g['scale_1'], g['scale_2']], 1)), 1)
        importance = opacity * scales[:, 2] * scales[:, 1]
        g = g[np.sort(np.argsort(-importance)[:args.max_splats])]
        print(f"kept the {len(g)} most visible splats")

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    write_like(args.out, args.splat_ply, g)
    transform = unity_transform(A, b)
    json_path = os.path.splitext(args.out)[0] + '.transform.json'
    with open(json_path, 'w') as f:
        json.dump(transform, f, indent=2)
    print(f"scale x{scale:.3f} | {len(g)} splats -> {args.out}\ntransform -> {json_path}")


if __name__ == '__main__':
    main()
