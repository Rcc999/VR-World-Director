"""Train a 3D Gaussian splat on a Puffin-World scene, guided by Puffin's depth (GPU, gsplat).

Every generated view (all runs: turns, sideways slides, orbits, walk) is a training image
at its own Puffin camera. The Gaussians start at the dense point cloud (+ a sky shell) and
are fitted to the images (L1) and to Puffin's depth (relative L1, sky excluded), which
keeps them on the surfaces: without depth, views that mostly turn in place gave needles.
A penalty on very elongated Gaussians helps the same way.

Frame: W = Unity with y flipped (right-handed, meters, floor y = 0). The splat goes into
Unity with a Transform of scale (1, -1, 1), written next to it (.transform.json).

    python -m puffin_fusion.train_3dgs outputs/scenes/plaza3d --out outputs/splats/Plaza3D.ply
(on Euler: puffin_fusion/train_3dgs.sbatch)
"""
import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from puffin_fusion.dense_fuse import load_reconstruction
from puffin_fusion.depth_mesh import aligned_depths
from puffin_fusion.to_3dgs_dataset import read_ply_xyzrgb

FLIP_Y = np.diag([1.0, -1.0, 1.0])
C0 = 0.28209479177387814  # SH band 0


def load_views(scene, meta, upscale=None):
    """Images, intrinsics, W-frame world-to-camera matrices and metric depths of every view."""
    raw = np.load(scene / 'raw.npz')
    K = raw['K'].astype(np.float64)
    runs = [str(r) for r in raw['runs']]
    scale = float(meta['scale_to_meters'])
    rec = load_reconstruction()
    ref = raw[f'{runs[0]}_depths'][0].astype(np.float32)
    imgs, viewmats, depths, names = [], [], [], []
    for run in runs:
        frames, poses = raw[f'{run}_frames'], raw[f'{run}_poses'].astype(np.float64)
        d = raw[f'{run}_depths'].astype(np.float32)
        ok = (ref > 0) & (d[0] > 0)
        d *= float(np.median(ref[ok] / d[0][ok]))
        dal = aligned_depths(rec, list(d), list(poses), K)
        for i, M in enumerate(meta['trajectories_unity_c2w'][run]):
            if i == 0 and names:
                continue  # every run starts from the same seed view
            M = np.asarray(M)
            c2w = np.eye(4)
            c2w[:3, :3] = FLIP_Y @ M[:3, :3] @ FLIP_Y   # Unity camera -> OpenCV camera, in W
            c2w[:3, 3] = FLIP_Y @ M[:3, 3]
            imgs.append(frames[i])
            viewmats.append(np.linalg.inv(c2w))
            depths.append(dal[i] * scale)
            names.append(f'{run}_{i:02d}')
    print(f'{len(names)} views: ' + ', '.join(f"{r} {sum(n.startswith(r + '_') for n in names)}" for r in runs))
    return np.stack(imgs), K, np.stack(viewmats), np.stack(depths), names


def init_gaussians(ply, n_points, sky_m, n_sky, center, device):
    pts, rgb = read_ply_xyzrgb(ply)
    if len(pts) > n_points:
        idx = np.random.default_rng(0).choice(len(pts), n_points, replace=False)
        pts, rgb = pts[idx], rgb[idx]
    pts = pts @ FLIP_Y
    # Sky shell: points on a far sphere so the sky has Gaussians of its own (else
    # floaters appear in front of the cameras to explain it).
    g = np.random.default_rng(1).normal(size=(n_sky, 3))
    g /= np.linalg.norm(g, axis=1, keepdims=True)
    sky = center + sky_m * g
    pts = np.concatenate([pts, sky])
    rgb = np.concatenate([rgb, np.full((n_sky, 3), 160, np.uint8)])

    from scipy.spatial import cKDTree
    dist, _ = cKDTree(pts).query(pts, k=4)
    s = np.clip(dist[:, 1:].mean(1), 1e-4, None)
    n = len(pts)
    t = lambda a: torch.tensor(a, dtype=torch.float32, device=device)
    params = torch.nn.ParameterDict({
        'means': torch.nn.Parameter(t(pts)),
        'scales': torch.nn.Parameter(t(np.log(s))[:, None].repeat(1, 3)),
        'quats': torch.nn.Parameter(t(np.tile([1.0, 0, 0, 0], (n, 1)))),
        'opacities': torch.nn.Parameter(torch.logit(torch.full((n,), 0.5, device=device))),
        'sh0': torch.nn.Parameter(((t(rgb) / 255.0 - 0.5) / C0)[:, None, :]),
        'shN': torch.nn.Parameter(torch.zeros(n, 15, 3, device=device)),
    })
    return params


def save_ply(path, params):
    p = {k: v.detach().cpu().numpy() for k, v in params.items()}
    n = len(p['means'])
    rest = p['shN'].transpose(0, 2, 1).reshape(n, -1)            # channel-major, like 3DGS
    cols = ([('x', p['means'][:, 0]), ('y', p['means'][:, 1]), ('z', p['means'][:, 2])]
            + [(f'nx', np.zeros(n)), ('ny', np.zeros(n)), ('nz', np.zeros(n))]
            + [(f'f_dc_{i}', p['sh0'][:, 0, i]) for i in range(3)]
            + [(f'f_rest_{i}', rest[:, i]) for i in range(rest.shape[1])]
            + [('opacity', p['opacities'])]
            + [(f'scale_{i}', p['scales'][:, i]) for i in range(3)]
            + [(f'rot_{i}', p['quats'][:, i]) for i in range(4)])
    data = np.stack([c[1] for c in cols], 1).astype('<f4')
    header = ('ply\nformat binary_little_endian 1.0\n' f'element vertex {n}\n'
              + ''.join(f'property float {c[0]}\n' for c in cols) + 'end_header\n')
    with open(path, 'wb') as f:
        f.write(header.encode())
        f.write(data.tobytes())
    Path(path).with_suffix('.transform.json').write_text(json.dumps(
        {'position': [0, 0, 0], 'rotation': [0, 0, 0, 1], 'scale': [1, -1, 1]}, indent=2))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('scene_dir', help='Puffin scene: raw.npz + scene_dense.json + scene_unity_dense.ply')
    ap.add_argument('--json', default='scene_dense.json')
    ap.add_argument('--ply', default='scene_unity_dense.ply')
    ap.add_argument('--out', required=True)
    ap.add_argument('--steps', type=int, default=15000)
    ap.add_argument('--init_points', type=int, default=1_000_000)
    ap.add_argument('--depth_weight', type=float, default=0.3)
    ap.add_argument('--aniso_max', type=float, default=10.0, help='penalize Gaussians longer than this ratio')
    ap.add_argument('--sky_m', type=float, default=150.0)
    ap.add_argument('--max_gaussians', type=int, default=3_000_000)
    args = ap.parse_args()

    from gsplat import rasterization
    from gsplat.strategy import DefaultStrategy

    dev = 'cuda'
    scene = Path(args.scene_dir)
    meta = json.loads((scene / args.json).read_text())
    imgs, K, viewmats, depths, names = load_views(scene, meta)
    V, H, W = imgs.shape[:3]
    center = (np.linalg.inv(viewmats[0]))[:3, 3]

    # Depth supervision only where Puffin's depth is solid (not sky / far haze).
    far = np.minimum(20 * np.median(depths.reshape(V, -1), 1), np.percentile(depths.reshape(V, -1), 95, axis=1))
    dmask = (depths > 0) & (depths < far[:, None, None]) & (depths < args.sky_m)

    imgs_t = torch.tensor(imgs, device=dev).float() / 255.0
    depths_t = torch.tensor(depths, device=dev).float()
    dmask_t = torch.tensor(dmask, device=dev)
    viewmats_t = torch.tensor(viewmats, device=dev).float()
    K_t = torch.tensor(K, device=dev).float()

    params = init_gaussians(scene / args.ply, args.init_points, args.sky_m, 100_000, center, dev)
    lrs = dict(means=1.6e-4, scales=5e-3, quats=1e-3, opacities=5e-2, sh0=2.5e-3, shN=2.5e-3 / 20)
    scene_scale = float(np.median(depths[dmask]))
    opt = {k: torch.optim.Adam([{'params': params[k], 'lr': lrs[k] * (scene_scale if k == 'means' else 1),
                                 'name': k}], eps=1e-15) for k in params}
    strategy = DefaultStrategy(refine_stop_iter=int(args.steps * 0.6), verbose=False)
    strategy.check_sanity(params, opt)
    state = strategy.initialize_state(scene_scale=scene_scale)
    print(f'{len(params["means"])} initial Gaussians, scene scale {scene_scale:.1f} m', flush=True)

    t0 = time.time()
    order = np.random.default_rng(0).permutation(np.arange(args.steps) % V)
    for step in range(args.steps):
        v = int(order[step])
        sh_degree = min(3, step // 1000)
        colors = torch.cat([params['sh0'], params['shN']], 1)
        out, alphas, info = rasterization(
            params['means'], F.normalize(params['quats'], dim=-1), torch.exp(params['scales']),
            torch.sigmoid(params['opacities']), colors, viewmats_t[v:v + 1], K_t[None], W, H,
            sh_degree=sh_degree, render_mode='RGB+ED', far_plane=1000.0)
        rgb, dep = out[0, ..., :3], out[0, ..., 3]
        strategy.step_pre_backward(params, opt, state, step, info)

        l_rgb = (rgb - imgs_t[v]).abs().mean()
        m = dmask_t[v]
        l_dep = ((dep[m] - depths_t[v][m]).abs() / depths_t[v][m]).mean()
        s = torch.exp(params['scales'])
        l_aniso = F.relu(s.max(1).values / s.min(1).values.clamp_min(1e-8) - args.aniso_max).mean()
        loss = l_rgb + args.depth_weight * l_dep + 0.01 * l_aniso
        loss.backward()
        for o in opt.values():
            o.step()
            o.zero_grad(set_to_none=True)
        strategy.step_post_backward(params, opt, state, step, info, packed=False)
        if len(params['means']) > args.max_gaussians:
            strategy.refine_stop_iter = step  # stop growing
        if step % 500 == 0 or step == args.steps - 1:
            print(f'step {step:5d}  rgb {l_rgb.item():.4f}  depth {l_dep.item():.4f}  '
                  f'gaussians {len(params["means"])}  {time.time() - t0:.0f} s', flush=True)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    save_ply(out, params)
    # A few renders next to the training views, to check by eye.
    from PIL import Image
    with torch.no_grad():
        for v in np.linspace(0, V - 1, 6).astype(int):
            colors = torch.cat([params['sh0'], params['shN']], 1)
            r, _, _ = rasterization(params['means'], F.normalize(params['quats'], dim=-1),
                                    torch.exp(params['scales']), torch.sigmoid(params['opacities']),
                                    colors, viewmats_t[v:v + 1], K_t[None], W, H, sh_degree=3)
            pair = np.concatenate([imgs[v], (r[0].clamp(0, 1).cpu().numpy() * 255).astype(np.uint8)], 1)
            Image.fromarray(pair).save(out.with_name(f'{out.stem}_check_{names[v]}.jpg'))
    print(f'{len(params["means"])} Gaussians -> {out}')


if __name__ == '__main__':
    main()
