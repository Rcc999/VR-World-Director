"""Re-fuse a Puffin-World seed scene denser, on the Mac (CPU, no GPU/weights).

Input: the raw.npz + meta.json that generation/scenes.py (generation-server
branch) writes per scene: generated frames, depths and camera poses per run.
Same steps as its fuse_scene (upstream export_reconstruction_glb per run, runs
on one depth scale, floor fit, meters, Unity frame), but without upstream's
thinning: no 512^3 voxel averaging, a larger point budget, every view used.
--keep_views pan=22 fuses only the first views of a run (before it drifts).

    python -m puffin_fusion.dense_fuse ../data/vrwd_scenes/raw/indoor --keep_views pan=22 \
        --out ../data/vrwd_scenes/dense/Indoor.ply
"""
import argparse
import importlib.util
import json
import math
import sys
import types
from pathlib import Path

import numpy as np

SERVER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIR))
from common.pointcloud import (OPENCV_TO_UNITY, fit_floor, level_to_floor,  # noqa: E402
                               opencv_to_unity, write_ply)

MODULES = SERVER_DIR.parent / 'third_party/Puffin/Puffin-World/scripts/evaluation/modules'


def load_reconstruction():
    """Upstream reconstruction.py without its package __init__ (which pulls in
    the dataset code and its heavy dependencies)."""
    pkg = types.ModuleType('puffin_modules')
    pkg.__path__ = [str(MODULES)]
    sys.modules['puffin_modules'] = pkg
    for name in ('parsing', 'media', 'reconstruction'):
        spec = importlib.util.spec_from_file_location(f'puffin_modules.{name}', MODULES / f'{name}.py')
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
    return sys.modules['puffin_modules.reconstruction']


def fuse_run(rec, frames, depths, poses, K, glb_path, args):
    import torch
    import trimesh
    tens = [torch.from_numpy(f).permute(2, 0, 1).float() / 127.5 - 1.0 for f in frames]
    rec.export_reconstruction_glb(
        tens, [d.astype(np.float64) for d in depths], [np.array2string(p) for p in poses],
        [np.array2string(K)] * len(poses), str(glb_path),
        max_points=args.max_points, voxel_res=args.voxel_res, max_stride=args.max_stride)
    cloud = next(g for g in trimesh.load(glb_path).geometry.values()
                 if isinstance(g, trimesh.PointCloud))
    pts = np.asarray(cloud.vertices) @ np.diag([1.0, -1.0, -1.0])  # glTF -> OpenCV
    return pts, np.asarray(cloud.colors)[:, :3]


def to_unity_pose(c2w, R_level, d, scale):
    S = OPENCV_TO_UNITY
    M = np.eye(4)
    M[:3, :3] = R_level @ S @ c2w[:3, :3] @ S
    M[:3, 3] = (R_level @ S @ c2w[:3, 3] + [0.0, d, 0.0]) * scale
    return M


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('scene_dir', help='folder with raw.npz (+ meta.json)')
    p.add_argument('--out', required=True, help='output .ply (a .json with the camera paths goes next to it)')
    p.add_argument('--voxel_res', type=int, default=0, help='0 = no voxel averaging (upstream: 512)')
    p.add_argument('--max_points', type=int, default=3_000_000, help='per run (upstream: 1M)')
    p.add_argument('--max_stride', type=int, default=1, help='1 = every view (upstream: 4)')
    p.add_argument('--keep_views', nargs='*', default=[], metavar='RUN=N')
    p.add_argument('--camera_height', type=float, default=1.5)
    args = p.parse_args()

    scene = Path(args.scene_dir)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    rec = load_reconstruction()
    raw = np.load(scene / 'raw.npz')
    K = raw['K']
    runs = [str(r) for r in raw['runs']] if 'runs' in raw else ['pan', 'walk']
    keep = {k: int(v) for k, v in (kv.split('=') for kv in args.keep_views)}
    print('runs: ' + ', '.join(f"{r} ({len(raw[r + '_frames'])} views)" for r in runs))

    ref = raw[f'{runs[0]}_depths'][0].astype(np.float32)
    clouds = []
    for name in runs:
        n = keep.get(name)
        d = raw[f'{name}_depths'][:n].astype(np.float32)
        ok = (ref > 0) & (d[0] > 0)
        d *= float(np.median(ref[ok] / d[0][ok])) if ok.sum() > 100 else 1.0
        pts, rgb = fuse_run(rec, raw[f'{name}_frames'][:n], d, raw[f'{name}_poses'][:n], K,
                            out.with_name(f'{out.stem}_{name}.glb'), args)
        print(f"{name}: {len(d)} views -> {len(pts)} points", flush=True)
        clouds.append((pts, rgb))
    pts = opencv_to_unity(np.concatenate([c[0] for c in clouds]))
    rgb = np.concatenate([c[1] for c in clouds])

    up_unity = opencv_to_unity(raw['up'][None])[0]
    try:
        normal, d = fit_floor(pts, up_hint=up_unity)
        floor = 'ransac'
    except RuntimeError:
        normal = up_unity / np.linalg.norm(up_unity)
        d = -float(np.percentile(pts @ normal, 2))
        floor = 'gravity'
    pts, R, cam_height = level_to_floor(pts, normal, d)
    scale = args.camera_height / cam_height
    pts *= scale
    write_ply(out, pts, rgb)

    meta = json.loads((scene / 'meta.json').read_text()) if (scene / 'meta.json').exists() else {}
    meta.update(points=int(len(pts)), floor_fit=floor, scale_to_meters=float(scale),
                camera_height_m=args.camera_height, intrinsics_640=K.tolist(),
                fusion=dict(voxel_res=args.voxel_res, max_points=args.max_points,
                            max_stride=args.max_stride, keep_views=keep),
                trajectories_unity_c2w={t: [to_unity_pose(p, R, d, scale).tolist()
                                            for p in raw[f'{t}_poses'][:keep.get(t)]] for t in runs})
    out.with_suffix('.json').write_text(json.dumps(meta, indent=1))
    lo, hi = np.percentile(pts, [1, 99], axis=0)
    print(f"{len(pts)} points | floor {floor} | x{scale:.2f} | extent {np.round(hi - lo, 1)} m -> {out}")


if __name__ == '__main__':
    main()
