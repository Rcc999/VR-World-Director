"""WP2 seed scenes: one photo or text prompt -> Puffin-World -> scene_unity.ply.

Two camera runs from the seed view, both generated with depth:
  pan   turn in place 360 deg about the gravity up-axis Puffin estimates
        (deg_per_view close to upstream's 4 deg default for synthetic paths)
  walk  move forward along the horizontal view direction
Each run is fused with upstream's export_reconstruction_glb (per-view depth
gauges, flying-pixel filter, voxel denoise), the walk is put on the pan's
depth scale via the seed view (both runs generate its depth), and the merged
cloud is written in the Unity viewer's frame, like depth/depth_standin.py:
floor at y = 0, meters (scaled so the seed camera is --camera_height above
the floor), seed camera at x = z = 0 looking down +z.

Outputs in <out>/<name>/: scene_unity.ply, scene.json (seed camera, scale,
trajectories), pan.mp4 / walk.mp4, pan.glb / walk.glb, raw.npz (frames,
depths, poses: re-fuse without regenerating via --fuse_only).

    python -m generation.scenes indoor --image photo.jpg
    python -m generation.scenes text --prompt "A sunlit Japanese garden ..."
"""
import argparse
import json
import math
import os
from pathlib import Path

import sys

import numpy as np

SERVER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIR))  # common/ (puffin_runtime chdirs away)
# Text seeds have no photo to estimate the camera from: eye level, slightly
# down, ~52 deg vertical FoV, no distortion (radians, Puffin's order).
TEXT_CAM = (0.0, -0.08, 0.9, 0.0)


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('name')
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument('--image')
    src.add_argument('--prompt')
    src.add_argument('--fuse_only', action='store_true',
                     help='re-fuse <out>/<name>/raw.npz without the GPU')
    p.add_argument('--model', choices=('pro', 'base'), default='pro')
    p.add_argument('--out', default=str(SERVER_DIR / 'outputs' / 'scenes'))
    p.add_argument('--num_steps', type=int, default=50)
    p.add_argument('--deg_per_view', type=float, default=5.0)
    p.add_argument('--pan_deg', type=float, default=360.0)
    p.add_argument('--walk_chunks', type=int, default=2)
    p.add_argument('--walk_step', type=float, default=0.04,
                   help='forward step per view as a fraction of the seed '
                        "view's median depth")
    p.add_argument('--camera_height', type=float, default=1.5,
                   help='meters between the seed camera and the floor')
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--quick', action='store_true',
                   help='smoke test: 10 steps, one chunk per run')
    return p.parse_args()


# ---------------------------------------------------------------------------
# camera paths (OpenCV c2w, world = seed camera frame)
# ---------------------------------------------------------------------------
def gravity_up(pitch):
    """World up in the seed camera's OpenCV frame (+y down, +z forward) from
    Puffin's pitch (negative = looking down). Roll is left to the floor fit."""
    return np.array([0.0, -math.cos(pitch), math.sin(pitch)])


def rotation(axis, angle):
    axis = axis / np.linalg.norm(axis)
    k = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]],
                  [-axis[1], axis[0], 0]])
    return np.eye(3) + math.sin(angle) * k + (1 - math.cos(angle)) * k @ k


def pan_poses(n, deg_per_view, up):
    poses = []
    for i in range(n):
        P = np.eye(4)
        P[:3, :3] = rotation(up, math.radians(deg_per_view * i))
        poses.append(P)
    return poses


def walk_poses(n, step, up):
    fwd = np.array([0.0, 0.0, 1.0])
    fwd = fwd - (fwd @ up) * up
    fwd /= np.linalg.norm(fwd)
    poses = []
    for i in range(n):
        P = np.eye(4)
        P[:3, 3] = fwd * step * i
        poses.append(P)
    return poses


def chunks_for(views_needed, num_views=8):
    return max(1, math.ceil((views_needed - 1) / (num_views - 1)))


# ---------------------------------------------------------------------------
# generation
# ---------------------------------------------------------------------------
def run_path(pr, model, seed_img, poses, K, cam, args):
    r = pr.generate(model, seed_img, poses, K, cam, num_steps=args.num_steps,
                    seed=args.seed)
    frames = [seed_img] + [f.float().cpu() for f in r['gen_images_tensor'][0]]
    depths = [np.squeeze(np.asarray(d.float().cpu() if hasattr(d, 'cpu') else d,
                                    dtype=np.float32))
              for d in r['depth_samples'][0]]
    n = min(len(frames), len(depths), len(poses))
    if not len(frames) == len(depths) == len(poses):
        print(f"[warn] {len(frames)} frames / {len(depths)} depths / "
              f"{len(poses)} poses; keeping the first {n}", flush=True)
    frames, depths = frames[:n], depths[:n]
    frames = np.stack([((f.clamp(-1, 1) + 1) * 127.5).round().byte()
                       .permute(1, 2, 0).numpy() for f in frames])
    return frames, np.stack(depths)


def generate_scene(args, out):
    import torch
    from generation import puffin_runtime as pr
    from scripts.evaluation.modules import save_frames_as_mp4

    model = pr.load_model(args.model, geometry=True)
    if args.image:
        seed_img, pil = pr.load_seed_image(os.path.abspath(args.image))
        caption, cam = pr.understand(model, pil)
    else:
        caption, cam = args.prompt, TEXT_CAM
        seed_img, _ = pr.text_to_image(model, args.prompt, cam,
                                       num_steps=args.num_steps, seed=args.seed)
    print(f"caption: {caption[:200]}\ncam (rad): {cam}", flush=True)
    K = pr.intrinsics_from_vfov(cam[2], res=seed_img.shape[-1])
    up = gravity_up(cam[1])

    n_pan = 1 if args.quick else chunks_for(args.pan_deg / args.deg_per_view + 1)
    pan = pan_poses(pr.views_for_chunks(n_pan), args.deg_per_view, up)
    pan_frames, pan_depths = run_path(pr, model, seed_img, pan, K, cam, args)
    pan = pan[:len(pan_frames)]
    np.savez_compressed(out / 'raw_pan.npz', K=K, cam=np.asarray(cam), up=up,
                        pan_frames=pan_frames, pan_depths=pan_depths.astype(np.float16),
                        pan_poses=np.stack(pan))
    print(f"pan: {len(pan)} views, {(len(pan) - 1) * args.deg_per_view:.0f} deg",
          flush=True)

    d0 = pan_depths[0][pan_depths[0] > 0]
    step = args.walk_step * float(np.median(d0))
    n_walk = 1 if args.quick else args.walk_chunks
    walk = walk_poses(pr.views_for_chunks(n_walk), step, up)
    walk_frames, walk_depths = run_path(pr, model, seed_img, walk, K, cam, args)
    walk = walk[:len(walk_frames)]
    print(f"walk: {len(walk)} views, step {step:.4f} (depth units)", flush=True)

    for tag, fr in (('pan', pan_frames), ('walk', walk_frames)):
        save_frames_as_mp4(list(fr), str(out / f'{tag}.mp4'), fps=8)
    np.savez_compressed(
        out / 'raw.npz', K=K, cam=np.asarray(cam), up=up,
        pan_frames=pan_frames, pan_depths=pan_depths.astype(np.float16),
        pan_poses=np.stack(pan), walk_frames=walk_frames,
        walk_depths=walk_depths.astype(np.float16), walk_poses=np.stack(walk))
    (out / 'meta.json').write_text(json.dumps(dict(
        caption=caption, cam_rad=dict(zip(('roll', 'pitch', 'vfov', 'k1'), cam)),
        source=args.image or args.prompt, model=args.model,
        num_steps=args.num_steps, deg_per_view=args.deg_per_view,
        walk_step=args.walk_step, seed=args.seed), indent=1))
    del model
    torch.cuda.empty_cache()


# ---------------------------------------------------------------------------
# fusion -> Unity
# ---------------------------------------------------------------------------
def fuse_run(frames, depths, poses, K, glb_path):
    """Upstream fusion for one run; returns OpenCV-frame points + colors."""
    import torch
    import trimesh
    from generation import puffin_runtime  # noqa: F401  (puts upstream on sys.path)
    from scripts.evaluation.modules.reconstruction import export_reconstruction_glb

    tens = [torch.from_numpy(f).permute(2, 0, 1).float() / 127.5 - 1.0 for f in frames]
    export_reconstruction_glb(tens, [d.astype(np.float64) for d in depths],
                              [np.array2string(p) for p in poses],
                              [np.array2string(K)] * len(poses), str(glb_path))
    cloud = next(g for g in trimesh.load(glb_path).geometry.values()
                 if isinstance(g, trimesh.PointCloud))
    # export_reconstruction_glb flips OpenCV -> glTF with diag(1, -1, -1).
    pts = np.asarray(cloud.vertices) @ np.diag([1.0, -1.0, -1.0])
    return pts, np.asarray(cloud.colors)[:, :3]


def to_unity_pose(c2w, R_level, d, scale):
    """OpenCV c2w -> Unity-frame c2w (camera +y up), leveled and scaled."""
    from common.pointcloud import OPENCV_TO_UNITY as S
    M = np.eye(4)
    M[:3, :3] = R_level @ S @ c2w[:3, :3] @ S
    M[:3, 3] = (R_level @ S @ c2w[:3, 3] + [0.0, d, 0.0]) * scale
    return M


def fuse_scene(args, out):
    from common.pointcloud import (fit_floor, level_to_floor, opencv_to_unity,
                                   write_ply)
    raw = np.load(out / 'raw.npz')
    K = raw['K']
    pan_d = raw['pan_depths'].astype(np.float32)
    walk_d = raw['walk_depths'].astype(np.float32)
    # Both runs generate the seed view's depth: put the walk on the pan's
    # scale (its poses were laid out in pan depth units).
    a, b = pan_d[0], walk_d[0]
    ok = (a > 0) & (b > 0)
    walk_d *= float(np.median(a[ok] / b[ok])) if ok.sum() > 100 else 1.0

    pts_p, rgb_p = fuse_run(raw['pan_frames'], pan_d, raw['pan_poses'], K, out / 'pan.glb')
    pts_w, rgb_w = fuse_run(raw['walk_frames'], walk_d, raw['walk_poses'], K, out / 'walk.glb')
    pts = opencv_to_unity(np.concatenate([pts_p, pts_w]))
    rgb = np.concatenate([rgb_p, rgb_w])

    up_unity = opencv_to_unity(raw['up'][None])[0]
    try:
        normal, d = fit_floor(pts, up_hint=up_unity)
        floor = 'ransac'
    except RuntimeError:
        # No floor plane (e.g. open terrain): trust Puffin's gravity and put
        # the floor at the 2nd percentile height.
        normal = up_unity / np.linalg.norm(up_unity)
        d = -float(np.percentile(pts @ normal, 2))
        floor = 'gravity'
    pts, R, cam_height = level_to_floor(pts, normal, d)
    scale = args.camera_height / cam_height
    pts *= scale
    write_ply(out / 'scene_unity.ply', pts, rgb)

    tilt = math.degrees(math.acos(np.clip(normal @ up_unity / np.linalg.norm(up_unity), -1, 1)))
    traj = {tag: [to_unity_pose(p, R, d, scale).tolist() for p in raw[f'{tag}_poses']]
            for tag in ('pan', 'walk')}
    meta = json.loads((out / 'meta.json').read_text())
    meta.update(
        points=int(len(pts)), floor_fit=floor,
        floor_vs_gravity_deg=round(tilt, 2),
        estimated_camera_height=float(cam_height), scale_to_meters=float(scale),
        camera_height_m=args.camera_height,
        intrinsics_640=K.tolist(),
        trajectories_unity_c2w=traj,
        conventions=('Unity frame: +x right, +y up, +z forward, meters, floor '
                     'y=0, seed camera at (0, camera_height_m, 0). c2w columns '
                     'are the camera right/up/forward axes and position.'))
    (out / 'scene.json').write_text(json.dumps(meta, indent=1))
    lo, hi = np.percentile(pts, [1, 99], axis=0)
    print(f"{len(pts)} points | floor {floor} ({tilt:.1f} deg off gravity) | "
          f"camera height {cam_height:.3f} -> x{scale:.2f} = {args.camera_height} m | "
          f"extent {np.round(hi - lo, 1)} m -> {out / 'scene_unity.ply'}")


def main():
    args = parse_args()
    if args.quick:
        args.num_steps = 10
    out = Path(os.path.abspath(args.out)) / args.name
    out.mkdir(parents=True, exist_ok=True)
    if not args.fuse_only:
        generate_scene(args, out)
    fuse_scene(args, out)


if __name__ == '__main__':
    main()
