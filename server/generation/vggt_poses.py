"""Camera poses + depth for a set of seed photos with VGGT (GPU).

COLMAP placed only 4 of 15 handheld living-room photos reliably (wide
baselines, white walls); VGGT (Wang et al., CVPR 2025; proposal ref. [6])
predicts every photo's camera and a dense depth map in one forward pass, all
in the first photo's frame. Weights: facebook/VGGT-1B (CC BY-NC 4.0).

Writes to <out>/:
  cameras.json   {images: {name: {c2w (OpenCV), K, width, height}}} in the
                 same layout as sfm.py, plus floor / scale info
  vggt.npz       per photo: image (uint8), depth, depth confidence
  real_unity.ply the photos' own depth fused, in the Unity viewer's frame
                 (floor y = 0, meters, first photo's camera above x = z = 0)
  top_view.png   cameras + points from above, for a sanity check

    python -m generation.vggt_poses $SCRATCH/sfm/livingroom/images \\
        --out outputs/scenes/livingroom-real --weights $SCRATCH/vggt_weights
"""
import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

SERVER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIR))
LONG_SIDE = 518          # VGGT's training resolution; both sides multiples of 14 px


def main():
    p = argparse.ArgumentParser()
    p.add_argument('images', nargs='?', help='directory of upright photos (EXIF applied)')
    p.add_argument('--fuse_only', action='store_true',
                   help='re-fuse <out>/vggt.npz without the GPU')
    p.add_argument('--out', required=True)
    p.add_argument('--weights', default=os.path.expandvars('$SCRATCH/vggt_weights'))
    p.add_argument('--conf_pct', type=float, default=50.0,
                   help='keep depth pixels above this per-photo confidence percentile')
    p.add_argument('--camera_height', type=float, default=1.4,
                   help='median photo height above the floor in meters')
    args = p.parse_args()
    out = Path(os.path.abspath(args.out))
    out.mkdir(parents=True, exist_ok=True)

    if not args.fuse_only:
        predict(args, out)
    fuse(args, out)


def predict(args, out):
    import torch
    from PIL import Image
    from vggt.models.vggt import VGGT
    from vggt.utils.pose_enc import pose_encoding_to_extri_intri

    names = sorted(f for f in os.listdir(args.images)
                   if f.lower().endswith(('.jpg', '.jpeg', '.png')))
    first = Image.open(os.path.join(args.images, names[0]))
    short = int(round(LONG_SIDE * min(first.size) / max(first.size) / 14)) * 14
    W, H = (LONG_SIDE, short) if first.width > first.height else (short, LONG_SIDE)
    imgs = []
    for n in names:
        im = Image.open(os.path.join(args.images, n)).convert('RGB')
        if (im.width > im.height) != (W > H):
            raise SystemExit(f'{n}: mixed portrait and landscape images')
        imgs.append(np.asarray(im.resize((W, H), Image.LANCZOS)))
    x = torch.from_numpy(np.stack(imgs)).permute(0, 3, 1, 2).float().div(255).cuda()

    model = VGGT.from_pretrained(args.weights).cuda().eval()
    with torch.no_grad(), torch.autocast('cuda', dtype=torch.bfloat16):
        pred = model(x)
    extr, intr = pose_encoding_to_extri_intri(pred['pose_enc'], (H, W))
    extr, intr = extr[0].float().cpu().numpy(), intr[0].float().cpu().numpy()
    depth = pred['depth'][0, ..., 0].float().cpu().numpy()          # [N, H, W]
    conf = pred['depth_conf'][0].float().cpu().numpy()
    c2w = []
    for e in extr:                       # camera-from-world, OpenCV
        T = np.eye(4)
        T[:3, :4] = e
        c2w.append(np.linalg.inv(T))
    np.savez_compressed(out / 'vggt.npz', names=np.array(names), images=np.stack(imgs),
                        depth=depth.astype(np.float16), conf=conf.astype(np.float16),
                        c2w=np.stack(c2w), K=intr)


def flattest_up(pts, up0, max_deg=15.0, bin_size=0.01, sample=300000):
    """Up direction within max_deg of up0 whose height histogram has the
    sharpest peaks (floor, ceiling, table tops): coarse grid, then refine."""
    pts = pts[np.random.default_rng(0).choice(len(pts), min(sample, len(pts)), replace=False)]

    def sharpness(u):
        h = pts @ u
        hist, _ = np.histogram(h, bins=np.arange(h.min(), h.max() + bin_size, bin_size))
        return np.sort(hist)[-2:].sum()

    def cone(axis, deg, n):
        x = np.cross(axis, [1.0, 0.0, 0.0] if abs(axis[0]) < 0.9 else [0.0, 0.0, 1.0])
        x /= np.linalg.norm(x)
        y = np.cross(axis, x)
        out = [axis]
        for t in np.radians(np.linspace(deg / n, deg, n)):
            for a in np.linspace(0, 2 * np.pi, max(6, int(4 * n * np.sin(t) / np.sin(np.radians(deg)))),
                                 endpoint=False):
                out.append(np.cos(t) * axis + np.sin(t) * (np.cos(a) * x + np.sin(a) * y))
        return out

    best = max(cone(up0, max_deg, 30), key=sharpness)
    best = max(cone(best, 1.0, 10), key=sharpness)
    return best / np.linalg.norm(best)


def fuse(args, out):
    from common.pointcloud import level_to_floor, opencv_to_unity, unproject, write_ply
    v = np.load(out / 'vggt.npz')
    names = [str(n) for n in v['names']]
    imgs, c2w, intr = v['images'], v['c2w'], v['K']
    H, W = imgs.shape[1:3]
    depth, conf = v['depth'].astype(np.float32), v['conf'].astype(np.float32)

    # Fuse the photos' own depth: confident pixels only.
    pts, cols = [], []
    for i in range(len(names)):
        keep = conf[i] > np.percentile(conf[i], args.conf_pct)
        cam = unproject(depth[i], intr[i])[keep]
        pts.append(cam @ c2w[i, :3, :3].T + c2w[i, :3, 3])
        cols.append(imgs[i][keep])
    pts = opencv_to_unity(np.concatenate(pts))
    cols = np.concatenate(cols)

    # Level, then scale so the median photo is camera_height above the floor.
    # RANSAC on the floor failed here twice: it took the white ceiling (the
    # biggest confident plane), which made the scale negative and mirrored the
    # room, and restricted to points below the cameras it settled 6 deg off.
    # Instead pick the up direction that makes the horizontal surfaces flattest,
    # then put the floor at the strongest flat band below every camera.
    up_cv = -c2w[:, :3, 1].mean(0)
    up0 = opencv_to_unity(up_cv[None])[0]
    up0 /= np.linalg.norm(up0)
    cams = opencv_to_unity(c2w[:, :3, 3])
    normal = flattest_up(pts, up0)
    h = pts @ normal
    below = h < (cams @ normal).min()
    hist, edges = np.histogram(h[below], bins=np.arange(h[below].min(), h[below].max() + 0.01, 0.01))
    d = -float(edges[np.argmax(hist)] + 0.005)      # floor plane: normal . p + d = 0
    pts, R, h0 = level_to_floor(pts, normal, d)
    up = up0
    centers = cams @ R.T
    centers[:, 1] += d
    scale = args.camera_height / float(np.median(centers[:, 1]))
    if scale <= 0:
        raise SystemExit(f'floor fit put the cameras below the floor (scale {scale:.3f})')
    pts *= scale
    centers *= scale
    write_ply(out / 'real_unity.ply', pts, cols)

    tilt = np.degrees(np.arccos(np.clip(normal @ up, -1, 1)))
    heights = centers[:, 1]
    (out / 'cameras.json').write_text(json.dumps(dict(
        source='vggt', width=W, height=H, weights='facebook/VGGT-1B',
        images={n: dict(c2w=c2w[i].tolist(), K=intr[i].tolist(), width=W, height=H)
                for i, n in enumerate(names)},
        unity=dict(R_level=R.tolist(), floor_offset=float(d), scale_to_meters=scale,
                   camera_centers_m={n: centers[i].tolist() for i, n in enumerate(names)},
                   floor_vs_camera_up_deg=float(tilt))), indent=1))

    print(f"{len(names)} photos | floor {tilt:.1f} deg off mean camera up | "
          f"camera heights {heights.min():.2f}-{heights.max():.2f} m (median {np.median(heights):.2f}) | "
          f"{len(pts)} points, extent {np.round(np.ptp(np.percentile(pts, [1, 99], 0), 0), 1)} m")
    for n, c, cf in zip(names, centers, conf):
        print(f"  {n}: at x {c[0]:5.2f} z {c[2]:5.2f}, height {c[1]:.2f} m, median conf {np.median(cf):.1f}")

    import matplotlib
    matplotlib.use('agg')
    import matplotlib.pyplot as plt
    sel = np.random.default_rng(0).choice(len(pts), min(200000, len(pts)), replace=False)
    band = sel[(pts[sel, 1] > 0.2) & (pts[sel, 1] < 2.2)]
    fig, ax = plt.subplots(figsize=(8, 8))
    ax.scatter(pts[band, 0], pts[band, 2], c=cols[band] / 255, s=0.5)
    for n, c, M in zip(names, centers, c2w):
        f = opencv_to_unity(M[:3, 2][None])[0] @ R.T
        ax.annotate('', xy=(c[0] + 0.5 * f[0], c[2] + 0.5 * f[2]), xytext=(c[0], c[2]),
                    arrowprops=dict(color='r', width=1, headwidth=5))
        ax.text(c[0], c[2], n[4:8], fontsize=8, color='r')
    ax.set_aspect('equal')
    ax.set_title('top view: walls 0.2-2.2 m + photo cameras (m)')
    fig.savefig(out / 'top_view.png', dpi=80)


if __name__ == '__main__':
    main()
