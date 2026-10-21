"""Colored point cloud (.ply: x y z red green blue, Unity frame) -> Gaussian
splat .ply for the Unity Gaussian Splatting renderer, without training.

Each point becomes a round, nearly opaque Gaussian in the point's color, as
wide as the gap to its neighbors (mean distance to the k nearest), so
neighboring Gaussians overlap into a continuous surface instead of the point
viewer's hard squares. Use it for Puffin-World clouds (already meters, floor
y = 0, seed camera at (0, 1.5, 0)): the transform written next to the .ply is
the identity.

    python -m splat_gaussians.points_to_gaussians ../data/vrwd_scenes/front/puffin-indoor-front.ply \
        --out outputs/puffin_splats/Indoor.ply
Writes Indoor.ply + Indoor.transform.json; in Unity: Create GaussianSplatAsset
from it, then VR Director > Build Gaussian Splat Viewer Scene.
"""
import argparse
import json
import os

import numpy as np
from scipy.spatial import cKDTree

SH_C0 = 0.28209479177387814  # 3DGS: color = 0.5 + SH_C0 * f_dc


def read_points(path):
    with open(path, 'rb') as f:
        header = []
        while (line := f.readline().decode('ascii').strip()) != 'end_header':
            header.append(line)
        n = int(next(l for l in header if l.startswith('element vertex')).split()[-1])
        props = [l.split()[1:] for l in header if l.startswith('property')]
        types = {'float': '<f4', 'double': '<f8', 'uchar': 'u1'}
        dtype = np.dtype([(name, types[t]) for t, name in props])
        data = np.frombuffer(f.read(n * dtype.itemsize), dtype=dtype)
    xyz = np.stack([data['x'], data['y'], data['z']], 1).astype(np.float64)
    rgb = np.stack([data['red'], data['green'], data['blue']], 1).astype(np.float64) / 255
    return xyz, rgb


def write_gaussians(path, xyz, rgb, sigma, opacity):
    n = len(xyz)
    names = ['x', 'y', 'z', 'f_dc_0', 'f_dc_1', 'f_dc_2', 'opacity',
             'scale_0', 'scale_1', 'scale_2', 'rot_0', 'rot_1', 'rot_2', 'rot_3']
    rec = np.zeros(n, dtype=[(k, '<f4') for k in names])
    rec['x'], rec['y'], rec['z'] = xyz.T
    dc = (rgb - 0.5) / SH_C0
    rec['f_dc_0'], rec['f_dc_1'], rec['f_dc_2'] = dc.T
    rec['opacity'] = np.log(opacity / (1 - opacity))  # stored as a logit
    log_s = np.log(sigma)
    rec['scale_0'] = rec['scale_1'] = rec['scale_2'] = log_s  # stored as log
    rec['rot_0'] = 1.0  # identity quaternion (w, x, y, z): round Gaussians
    header = ('ply\nformat binary_little_endian 1.0\n'
              f'element vertex {n}\n'
              + ''.join(f'property float {k}\n' for k in names) + 'end_header\n')
    with open(path, 'wb') as f:
        f.write(header.encode('ascii'))
        f.write(rec.tobytes())


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('points_ply')
    p.add_argument('--out', required=True, help='output .ply (a .transform.json goes next to it)')
    p.add_argument('--max_splats', type=int, default=500_000,
                   help='headset budget: random subsample above it (sizes adapt to the gaps)')
    p.add_argument('--k', type=int, default=4, help='neighbors for the size')
    p.add_argument('--size', type=float, default=0.6,
                   help='Gaussian sigma = size x mean neighbor distance (higher = smoother, blurrier)')
    p.add_argument('--opacity', type=float, default=0.9)
    p.add_argument('--min_y', type=float, default=None,
                   help='drop points below this height (m), e.g. -0.3 to cut noise under the floor')
    p.add_argument('--voxel', type=float, default=0.0,
                   help='merge points into cubes of this size (m) first, averaging position and color '
                        '(removes duplicates where views overlap; e.g. 0.01)')
    p.add_argument('--seed', type=int, default=0)
    args = p.parse_args()

    xyz, rgb = read_points(args.points_ply)
    print(f"{len(xyz)} points")
    if args.min_y is not None:
        keep = xyz[:, 1] >= args.min_y
        xyz, rgb = xyz[keep], rgb[keep]
        print(f"{len(xyz)} above y = {args.min_y}")
    if args.voxel > 0:
        keys = np.floor(xyz / args.voxel).astype(np.int64)
        _, inv, counts = np.unique(keys, axis=0, return_inverse=True, return_counts=True)
        inv = inv.ravel()
        xyz = np.stack([np.bincount(inv, xyz[:, i]) for i in range(3)], 1) / counts[:, None]
        rgb = np.stack([np.bincount(inv, rgb[:, i]) for i in range(3)], 1) / counts[:, None]
        print(f"{len(xyz)} after merging into {args.voxel * 100:g} cm cubes")
    if len(xyz) > args.max_splats:
        idx = np.sort(np.random.default_rng(args.seed).choice(len(xyz), args.max_splats, replace=False))
        xyz, rgb = xyz[idx], rgb[idx]
        print(f"subsampled to {len(xyz)}")

    dist, _ = cKDTree(xyz).query(xyz, k=args.k + 1, workers=-1)
    gap = dist[:, 1:].mean(1)
    # Far from the seed camera points are sparser; cap stray outliers so one
    # lonely point doesn't become a huge blob.
    from_cam = np.linalg.norm(xyz - [0.0, 1.5, 0.0], axis=1)
    sigma = np.clip(args.size * gap, 1e-3, 0.02 + 0.01 * from_cam)
    print(f"sigma median {np.median(sigma) * 100:.1f} cm, p95 {np.percentile(sigma, 95) * 100:.1f} cm")

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    # Slightly varied opacity: Unity's importer stores opacity relative to each block's
    # min..max, and a block where all opacities are equal comes out fully transparent.
    opacity = np.clip(args.opacity + np.random.default_rng(args.seed).uniform(-0.05, 0.05, len(xyz)), 0.05, 0.99)
    write_gaussians(args.out, xyz, rgb, sigma, opacity)
    json_path = os.path.splitext(args.out)[0] + '.transform.json'
    with open(json_path, 'w') as f:
        json.dump({'position': [0, 0, 0], 'rotation': [0, 0, 0, 1], 'scale': [1, 1, 1]}, f, indent=2)
    print(f"{len(xyz)} Gaussians -> {args.out}\ntransform -> {json_path}")


if __name__ == '__main__':
    main()
