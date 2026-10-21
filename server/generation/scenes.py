"""WP2 seed scenes: one photo or text prompt -> Puffin-World -> scene_unity.ply.

Short camera runs out of the seed view, all generated with depth:
  left / right  turn in place about the gravity up-axis Puffin estimates
  walk          move forward along the horizontal view direction
Each run is its own short autoregressive chain from the seed: one long
360-degree chain (11 chunks) drifted into invented places and faded to black
after ~3 chunks, while short chains at CFG 2 hold (sweep_drift.py, 2026-10-21:
indoor stays consistent for 4 chunks = 140 deg, the golden-hour plaza for ~2
before drifting toward night). Each run is fused with upstream's
export_reconstruction_glb (per-view depth gauges, flying-pixel filter, voxel
denoise), every run is put on the first run's depth scale via the seed view
(they all generate its depth), and the merged cloud is written in the Unity viewer's frame, like depth/depth_standin.py:
floor at y = 0, meters (scaled so the seed camera is --camera_height above
the floor), seed camera at x = z = 0 looking down +z.

Outputs in <out>/<name>/: scene_unity.ply, scene.json (seed camera, scale,
trajectories), <run>.mp4 / <run>.glb, raw.npz (frames, depths, poses per
run: re-fuse without regenerating via --fuse_only).

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
    p.add_argument('--cfg_scale', type=float, default=2.0,
                   help='4.0 (upstream free-view demo) fades long chains faster')
    p.add_argument('--deg_per_view', type=float, default=5.0,
                   help='8 deg/view changed the scene within 2 chunks')
    p.add_argument('--turn_chunks', type=int, default=3,
                   help='chunks per left / right branch (7 views = 35 deg each at 5 deg)')
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
    r = pr.generate(model, seed_img, poses, K, cam, cfg_scale=args.cfg_scale,
                    num_steps=args.num_steps, seed=args.seed)
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

    n_turn = 1 if args.quick else args.turn_chunks
    n_walk = 1 if args.quick else args.walk_chunks
    turn_views = pr.views_for_chunks(n_turn)
    raw = dict(K=K, cam=np.asarray(cam), up=up)
    plan = [('left', lambda: pan_poses(turn_views, -args.deg_per_view, up)),
            ('right', lambda: pan_poses(turn_views, args.deg_per_view, up)),
            # walk step needs a depth scale: the first run's seed-view depth
            ('walk', lambda: walk_poses(pr.views_for_chunks(n_walk), step, up))]
    step = None
    for name, make_poses in plan:
        if name == 'walk':
            d0 = raw['left_depths'][0].astype(np.float32)
            step = args.walk_step * float(np.median(d0[d0 > 0]))
        poses = make_poses()
        frames, depths = run_path(pr, model, seed_img, poses, K, cam, args)
        raw.update({f'{name}_frames': frames, f'{name}_depths': depths.astype(np.float16),
                    f'{name}_poses': np.stack(poses[:len(frames)])})
        raw['runs'] = np.array([n for n, _ in plan if f'{n}_frames' in raw])
        np.savez_compressed(out / 'raw.npz', **raw)    # keep finished runs if a later one fails
        save_frames_as_mp4(list(frames), str(out / f'{name}.mp4'), fps=8)
        print(f"{name}: {len(frames)} views" + (f", step {step:.4f} (depth units)"
              if name == 'walk' else f", {(len(frames) - 1) * args.deg_per_view:.0f} deg"),
              flush=True)

    (out / 'meta.json').write_text(json.dumps(dict(
        caption=caption, cam_rad=dict(zip(('roll', 'pitch', 'vfov', 'k1'), cam)),
        source=args.image or args.prompt, model=args.model,
        num_steps=args.num_steps, cfg_scale=args.cfg_scale,
        deg_per_view=args.deg_per_view, turn_chunks=n_turn, walk_chunks=n_walk,
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
    runs = [str(r) for r in raw['runs']] if 'runs' in raw else ['pan', 'walk']
    # Every run generates the seed view's depth: put each on the first run's
    # scale (the walk's poses were laid out in those depth units).
    ref = raw[f'{runs[0]}_depths'][0].astype(np.float32)
    clouds = []
    for name in runs:
        d = raw[f'{name}_depths'].astype(np.float32)
        ok = (ref > 0) & (d[0] > 0)
        d *= float(np.median(ref[ok] / d[0][ok])) if ok.sum() > 100 else 1.0
        clouds.append(fuse_run(raw[f'{name}_frames'], d, raw[f'{name}_poses'], K,
                               out / f'{name}.glb'))
    pts = opencv_to_unity(np.concatenate([c[0] for c in clouds]))
    rgb = np.concatenate([c[1] for c in clouds])

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
    if scale <= 0:   # floor fitted above the camera: scaling would mirror the scene
        raise SystemExit(f'floor fit put the seed camera below the floor (height {cam_height:.3f})')
    pts *= scale
    write_ply(out / 'scene_unity.ply', pts, rgb)

    tilt = math.degrees(math.acos(np.clip(normal @ up_unity / np.linalg.norm(up_unity), -1, 1)))
    traj = {tag: [to_unity_pose(p, R, d, scale).tolist() for p in raw[f'{tag}_poses']]
            for tag in runs}
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
