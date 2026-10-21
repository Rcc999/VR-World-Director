"""Fill a VGGT-reconstructed multi-photo scene with Puffin-World.

vggt_poses.py gives every photo a camera pose and real depth (one frame,
leveled to Unity by its cameras.json). Here each photo also becomes a Puffin
seed with short left / right turns about the real vertical, so the gaps
between photos and the corners nobody photographed get generated content
anchored on nearby real views (short chains: sweep_drift.py).

GPU stage (per photo, saved as <out>/seeds/<photo>.npz, resumable):
  seed = the photo's 640x640 center crop (Puffin's input format); camera
  conditioning = Puffin's own roll / pitch / k1 with VGGT's vertical FoV of
  that crop; turn axis = the leveled world up seen from that camera.
CPU stage (--fuse_only, or after generating):
  each seed's Puffin depth is scaled to VGGT's depth of the same pixels,
  generated views (not the seed itself: the photo is real) are fused with
  upstream's reconstruction, placed with the photo's VGGT pose and leveled
  like the real cloud. Writes generated.ply and full.ply (real + generated).

    python -m generation.multiseed outputs/scenes/livingroom-real \\
        --images $SCRATCH/sfm/livingroom/images --photos IMG_7015.jpg IMG_7016.jpg
    python -m generation.multiseed outputs/scenes/livingroom-real --fuse_only
"""
import argparse
import json
import math
import os
import sys
from pathlib import Path

import numpy as np

SERVER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIR))
RES = 640


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('scene', help='vggt_poses.py output dir (vggt.npz, cameras.json)')
    p.add_argument('--images', help='the upright photos VGGT saw (full resolution)')
    p.add_argument('--photos', nargs='*', default=None,
                   help='subset of photo names to generate (default: all)')
    p.add_argument('--fuse_only', action='store_true')
    p.add_argument('--turn_chunks', type=int, default=1,
                   help='chunks per side (7 views = 35 deg at 5 deg/view)')
    p.add_argument('--deg_per_view', type=float, default=5.0)
    p.add_argument('--cfg_scale', type=float, default=2.0)
    p.add_argument('--num_steps', type=int, default=50)
    p.add_argument('--seed', type=int, default=42)
    return p.parse_args()


def crop_rows(h, w):
    """Rows of a portrait image kept by Puffin's center square crop."""
    top = (h - w) // 2
    return top, top + w


def world_up_cv(cam):
    """Leveled world up (+y in Unity) in VGGT's OpenCV world frame."""
    from common.pointcloud import unity_to_opencv
    R = np.array(cam['unity']['R_level'])
    return unity_to_opencv((R.T @ np.array([0.0, 1.0, 0.0]))[None])[0]


def generate(args, scene, v, cam):
    import torch
    from generation import puffin_runtime as pr
    from generation import scenes
    from scripts.evaluation.modules import save_frames_as_mp4

    names = [str(n) for n in v['names']]
    todo = args.photos or names
    seeds_dir = scene / 'seeds'
    seeds_dir.mkdir(exist_ok=True)
    model = pr.load_model('pro', geometry=True)
    up_w = world_up_cv(cam)
    H, W = v['depth'].shape[1:]

    for name in todo:
        if (seeds_dir / f'{Path(name).stem}.npz').exists():
            print(f"{name}: already generated", flush=True)
            continue
        i = names.index(name)
        seed_img, pil = pr.load_seed_image(os.path.join(args.images, name), res=RES)
        _, (roll, pitch, _, k1) = pr.understand(model, pil)
        # VGGT's vertical FoV of the square crop: crop height in VGGT pixels.
        r0, r1 = crop_rows(H, W)
        vfov = 2 * math.atan((r1 - r0) / 2 / v['K'][i][1, 1])
        cam_params = (roll, pitch, vfov, k1)
        K = pr.intrinsics_from_vfov(vfov, res=RES)
        up = v['c2w'][i][:3, :3].T @ up_w          # world up in this camera's frame
        up /= np.linalg.norm(up)

        out = dict(K=K, cam=np.asarray(cam_params), up=up)
        n_views = pr.views_for_chunks(args.turn_chunks)
        for side, sign in (('left', -1), ('right', 1)):
            poses = scenes.pan_poses(n_views, sign * args.deg_per_view, up)
            r = pr.generate(model, seed_img, poses, K, cam_params, cfg_scale=args.cfg_scale,
                            num_steps=args.num_steps, seed=args.seed)
            frames = [seed_img] + [f.float().cpu() for f in r['gen_images_tensor'][0]]
            n = min(len(frames), len(r['depth_samples'][0]), len(poses))
            out[f'{side}_frames'] = np.stack([((f.clamp(-1, 1) + 1) * 127.5).round().byte()
                                              .permute(1, 2, 0).numpy() for f in frames[:n]])
            out[f'{side}_depths'] = np.stack([np.asarray(d.float().cpu(), dtype=np.float32)
                                              for d in r['depth_samples'][0][:n]]).astype(np.float16)
            out[f'{side}_poses'] = np.stack(poses[:n])
            save_frames_as_mp4(list(out[f'{side}_frames']),
                               str(seeds_dir / f'{Path(name).stem}-{side}.mp4'), fps=8)
        np.savez_compressed(seeds_dir / f'{Path(name).stem}.npz', **out)
        print(f"{name}: roll {math.degrees(roll):.1f} pitch {math.degrees(pitch):.1f} "
              f"vfov {math.degrees(vfov):.1f} deg (VGGT) | left+right {2 * (n_views - 1)} views",
              flush=True)
    del model
    torch.cuda.empty_cache()


def fuse(scene, v, cam):

    from PIL import Image
    from generation import scenes
    from common.pointcloud import opencv_to_unity, read_ply, write_ply

    names = [str(n) for n in v['names']]
    H, W = v['depth'].shape[1:]
    r0, r1 = crop_rows(H, W)
    U = cam['unity']
    R, d0, s_m = np.array(U['R_level']), U['floor_offset'], U['scale_to_meters']

    pts_all, rgb_all, report = [], [], []
    for f in sorted((scene / 'seeds').glob('*.npz')):
        g = np.load(f)
        name = next(n for n in names if Path(n).stem == f.stem)
        i = names.index(name)
        # VGGT depth of the same square crop, at Puffin's resolution.
        ref = v['depth'][i][r0:r1].astype(np.float32)
        ref = np.asarray(Image.fromarray(ref).resize((RES, RES), Image.BILINEAR))
        for side in ('left', 'right'):
            dep = g[f'{side}_depths'].astype(np.float32)
            ok = (ref > 0) & (dep[0] > 0)
            s = float(np.median(ref[ok] / dep[0][ok]))      # Puffin units -> VGGT units
            dep = dep * s
            # Generated views only (from view 1): the photo itself is in the real cloud.
            pts, rgb = scenes.fuse_run(g[f'{side}_frames'][1:], dep[1:], g[f'{side}_poses'][1:],
                                       g['K'], scene / 'seeds' / f'{f.stem}-{side}.glb')
            c2w = v['c2w'][i]
            pts = pts @ c2w[:3, :3].T + c2w[:3, 3]           # seed camera -> VGGT world
            u = opencv_to_unity(pts) @ R.T
            u[:, 1] += d0
            pts_all.append(u * s_m)
            rgb_all.append(rgb)
            report.append((f.stem, side, s, len(pts)))
    if not pts_all:
        raise SystemExit('no generated seeds in ' + str(scene / 'seeds'))
    gen_pts, gen_rgb = np.concatenate(pts_all), np.concatenate(rgb_all)
    write_ply(scene / 'generated.ply', gen_pts, gen_rgb)
    real_pts, real_rgb = read_ply(scene / 'real_unity.ply')
    write_ply(scene / 'full.ply', np.concatenate([real_pts, gen_pts]),
              np.concatenate([real_rgb, gen_rgb]))
    for stem, side, s, n in report:
        print(f"  {stem} {side:5s}: depth scale x{s:.3f} to VGGT, {n} points")
    lo, hi = np.percentile(gen_pts, [1, 99], axis=0)
    print(f"generated {len(gen_pts)} points from {len(report) // 2} photos, extent "
          f"{np.round(hi - lo, 1)} m | full.ply = {len(real_pts)} real + {len(gen_pts)} generated")


def main():
    args = parse_args()
    scene = Path(os.path.abspath(args.scene))
    v = np.load(scene / 'vggt.npz')
    cam = json.loads((scene / 'cameras.json').read_text())
    if not args.fuse_only:
        if not args.images:
            raise SystemExit('--images is required to generate')
        generate(args, scene, v, cam)
    fuse(scene, v, cam)


if __name__ == '__main__':
    main()
