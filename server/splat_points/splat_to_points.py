"""Gaussian splat .ply (Brush / 3DGS export) -> colored point cloud for the
Unity viewer, leveled and scaled using the COLMAP cameras.

- Color: base SH coefficient (f_dc) -> RGB; splats below --min_opacity are dropped.
- Large splats get several points sampled inside their Gaussian, so flat
  surfaces covered by a few big splats do not show holes.
- Every point carries a `size` (diameter in m) from its splat's footprint, so
  the viewer draws big splats as big squares and surfaces close up.
- Frame: leveled, metric, spawn at x=z=0 in the middle of the capture path
  (see common/splats.py). Put the XR rig at the origin.

Usage:
    python -m splat_points.splat_to_points outputs/room_splat/splat_15000.ply \
        --colmap outputs/room_splat/sparse/0 --out outputs/room_splat/scene_unity.ply
"""
import argparse

import numpy as np

from common.pointcloud import write_ply
from common.splats import capture_frame, quat_to_rot, read_gaussian_ply

SH_C0 = 0.28209479177387814


def splat_footprint(scales):
    """Diameter (m) of a splat seen face-on: 2 sigma of its two largest axes,
    as the geometric mean so needles do not become huge squares."""
    s = np.sort(scales, axis=1)[:, ::-1]
    return 2 * np.sqrt(s[:, 0] * s[:, 1])


def fill_points(means, axes, scales, colors, spacing, budget, rng):
    """Extra points inside splats larger than `spacing`: count ~ area of the
    two largest axes / spacing^2 (capped), drawn from each Gaussian within
    1.5 sigma. `axes` are per-splat 3x3 matrices mapping local -> output frame.
    Each fill point's size is its share of the splat's footprint."""
    s = np.sort(scales, axis=1)[:, ::-1]
    counts = np.clip(s[:, 0] * s[:, 1] / spacing ** 2, 0, 50).astype(int)
    if counts.sum() > budget:
        counts = (counts * (budget / counts.sum())).astype(int)
    idx = np.repeat(np.arange(len(means)), counts)
    local = np.clip(rng.normal(size=(len(idx), 3)), -1.5, 1.5) * scales[idx]
    sizes = (splat_footprint(scales) / np.sqrt(np.maximum(counts, 1)))[idx] * 1.5
    return means[idx] + np.einsum('nij,nj->ni', axes[idx], local), colors[idx], sizes


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('splat_ply')
    p.add_argument('--colmap', required=True, help='COLMAP model dir (sparse/0)')
    p.add_argument('--out', required=True)
    p.add_argument('--camera_height', type=float, default=1.45,
                   help='median capture height above the floor, in meters')
    p.add_argument('--min_opacity', type=float, default=0.05)
    p.add_argument('--max_points', type=int, default=700_000,
                   help='total budget (splat centers + sampled fill points)')
    p.add_argument('--radius', type=float, default=6.0,
                   help='drop points farther than this from the capture center (m)')
    p.add_argument('--min_size', type=float, default=0.006,
                   help='smallest point diameter (m); raise it if the cloud shows gaps')
    p.add_argument('--max_size', type=float, default=0.04,
                   help='largest point diameter (m); big blurry splats are capped to this')
    args = p.parse_args()
    rng = np.random.default_rng(0)

    g = read_gaussian_ply(args.splat_ply)
    means = np.stack([g['x'], g['y'], g['z']], axis=1).astype(np.float64)
    colors = np.clip(0.5 + SH_C0 * np.stack([g['f_dc_0'], g['f_dc_1'], g['f_dc_2']], 1), 0, 1)
    colors = (colors * 255 + 0.5).astype(np.uint8)
    opacity = 1 / (1 + np.exp(-g['opacity']))
    scales = np.exp(np.stack([g['scale_0'], g['scale_1'], g['scale_2']], 1)).astype(np.float64)
    quats = np.stack([g['rot_0'], g['rot_1'], g['rot_2'], g['rot_3']], 1).astype(np.float64)
    keep = opacity >= args.min_opacity
    print(f"{len(g)} splats, {keep.sum()} with opacity >= {args.min_opacity}")
    means, colors, scales, quats = means[keep], colors[keep], scales[keep], quats[keep]

    # --- COLMAP world -> Unity viewer frame ----------------------------------
    A, b, scale, cams = capture_frame(means, args.colmap, args.camera_height)
    pts = means @ A.T + b

    # Fill large splats (target 1 cm spacing), then drop far floaters and
    # enforce the budget. Splat axes go through the same map as the points.
    axes = (A / scale) @ quat_to_rot(quats)
    extra, extra_cols, extra_sizes = fill_points(
        pts, axes, scales * scale, colors, spacing=0.01,
        budget=max(args.max_points - len(pts), 0), rng=rng)
    all_pts = np.concatenate([pts, extra])
    all_cols = np.concatenate([colors, extra_cols])
    all_sizes = np.clip(np.concatenate([splat_footprint(scales * scale), extra_sizes]),
                        args.min_size, args.max_size)

    horiz = np.linalg.norm(all_pts[:, [0, 2]], axis=1)
    inside = (horiz < args.radius) & (all_pts[:, 1] > -0.5) & (all_pts[:, 1] < 8)
    all_pts, all_cols, all_sizes = all_pts[inside], all_cols[inside], all_sizes[inside]
    if len(all_pts) > args.max_points:
        sel = rng.choice(len(all_pts), args.max_points, replace=False)
        all_pts, all_cols, all_sizes = all_pts[sel], all_cols[sel], all_sizes[sel]

    write_ply(args.out, all_pts, all_cols, all_sizes)
    print(f"scale x{scale:.3f} | cameras at {np.percentile(cams[:, 1], [5, 50, 95]).round(2)} m | "
          f"cameras span {np.diff(np.percentile(cams[:, [0, 2]], [5, 95], axis=0), axis=0)[0].round(2)} m (p5-p95) | "
          f"point size p5/50/95 {np.percentile(all_sizes, [5, 50, 95]).round(3)} m | "
          f"{len(pts)} centers + {len(extra)} fill -> {len(all_pts)} points -> {args.out}")


if __name__ == '__main__':
    main()
