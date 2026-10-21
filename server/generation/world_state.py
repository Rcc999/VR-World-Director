"""Export Puffin-World's world states for the VR menu.

Puffin-World represents a world through three states (README): appearance
(RGB), geometry (depth) and physics (gravity field + latitude, i.e. the
perspective field). Physics is not predicted for generated views: the seed's
estimated roll / pitch is propagated through the relative camera poses and
fed to the model as conditioning. So per view this records
  scene        roll / pitch of the camera in the final leveled scene
  conditioned  roll / pitch Puffin was told to generate (generated views)
  measured     roll / pitch / vfov Puffin's perception branch reads back
               from the frame (--measure; GPU)
and their differences (the proposal's camera-control accuracy metric).

Works on every scene kind in outputs/scenes/:
  single    scenes.py      raw.npz runs from one seed (photo or prompt)
  multiseed multiseed.py   per-photo seed runs + a VGGT-reconstructed scene
  real      vggt_poses.py  photos / video frames only (measure = Puffin's
                           perception vs. VGGT's leveled cameras)

Writes <scene>/world_state/: world_state.json and per run <run>-rgb.mp4,
<run>-depth.mp4, <run>-pf_up.mp4, <run>-pf_lat.mp4 (see WORLD_STATE.md).

    python -m generation.world_state outputs/scenes/outdoor-v2            # CPU
    python -m generation.world_state outputs/scenes/* --measure          # GPU
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
S = np.diag([1.0, -1.0, 1.0])          # OpenCV <-> Unity (common/pointcloud.py)


# ---------------------------------------------------------------------------
# physics
# ---------------------------------------------------------------------------
def roll_pitch(up_cam):
    """Puffin's (roll, pitch) in radians from the world-up vector in OpenCV
    camera coordinates (Puffin's Gravity class stores up: rp=0 -> (0,-1,0))."""
    import torch
    from scripts.camera.geometry.gravity import Gravity
    g = Gravity(torch.tensor(np.asarray(up_cam, dtype=np.float32)))
    return float(g.roll), float(g.pitch)


def up_from_rp(roll, pitch):
    import torch
    from scripts.camera.geometry.gravity import Gravity
    return Gravity.from_rp(torch.tensor(float(roll)), torch.tensor(float(pitch))).vec3d.numpy()


def unity_c2w(c2w, R, d, s):
    M = np.eye(4)
    M[:3, :3] = R @ S @ c2w[:3, :3] @ S
    M[:3, 3] = (R @ S @ c2w[:3, 3] + [0.0, d, 0.0]) * s
    return M


def wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


# ---------------------------------------------------------------------------
# scene kinds -> runs
# ---------------------------------------------------------------------------
def load_runs(scene):
    """[(name, dict(frames uint8 [N,H,W,3], depths [N,H,W] | None, c2w [N,4,4]
    OpenCV world, K 3x3, generated bool, seed_rp (roll, pitch) | None,
    vfov, k1))], leveling (R, d, s), caption, kind."""
    if (scene / 'raw.npz').exists():
        raw = np.load(scene / 'raw.npz')
        meta = json.loads((scene / 'scene.json').read_text())
        if 'unity' not in meta:
            raise SystemExit(f'{scene}: re-fuse with scenes.py --fuse_only first (no leveling in scene.json)')
        U = meta['unity']
        cam = raw['cam']
        names = [str(r) for r in raw['runs']] if 'runs' in raw else ['pan', 'walk']
        runs = [(n, dict(frames=raw[f'{n}_frames'], depths=raw[f'{n}_depths'].astype(np.float32),
                         c2w=raw[f'{n}_poses'], K=raw['K'], generated=True,
                         seed_rp=(float(cam[0]), float(cam[1])), vfov=float(cam[2]),
                         k1=float(cam[3]))) for n in names]
        return runs, (np.array(U['R_level']), U['floor_offset'], U['scale_to_meters']), \
            meta.get('caption'), 'single'

    v = np.load(scene / 'vggt.npz')
    cam = json.loads((scene / 'cameras.json').read_text())
    U = cam['unity']
    level = (np.array(U['R_level']), U['floor_offset'], U['scale_to_meters'])
    names = [str(n) for n in v['names']]
    H = v['images'].shape[1]
    vfovs = [2 * math.atan(H / 2 / K[1, 1]) for K in v['K']]
    runs = [('real', dict(frames=v['images'], depths=v['depth'].astype(np.float32),
                          c2w=v['c2w'], K=v['K'], generated=False, seed_rp=None,
                          vfov=float(np.median(vfovs)), k1=0.0, names=names))]
    kind = 'real'
    for f in sorted((scene / 'seeds').glob('*.npz')) if (scene / 'seeds').exists() else []:
        g = np.load(f)
        i = [Path(n).stem for n in names].index(f.stem)
        c = g['cam']
        for side in ('left', 'right'):
            rel = g[f'{side}_poses']
            runs.append((f'{f.stem}-{side}', dict(
                frames=g[f'{side}_frames'], depths=g[f'{side}_depths'].astype(np.float32),
                c2w=np.stack([v['c2w'][i] @ P for P in rel]), c2w_rel=rel, K=g['K'],
                generated=True, seed_rp=(float(c[0]), float(c[1])), vfov=float(c[2]),
                k1=float(c[3]))))
        kind = 'multiseed'
    return runs, level, None, kind


# ---------------------------------------------------------------------------
# media
# ---------------------------------------------------------------------------
def depth_frames(depths):
    """Turbo-colored inverse depth with one range per run (comparable across
    frames): red = near, blue = far. Puffin saturates sky / invalid pixels to
    huge finite depths; like upstream, anything beyond 20x the median is sky
    (drawn black) and kept out of the color range."""
    import matplotlib
    cmap = matplotlib.colormaps['turbo']
    pos = depths[depths > 0]
    med = float(np.median(pos)) if pos.size else 1.0
    valid = pos[pos <= 20 * med]
    inv = 1.0 / valid if valid.size else np.array([0.0, 1.0])
    lo, hi = np.percentile(inv, [2, 98])
    out = []
    for d in depths:
        ok = (d > 0) & (d <= 20 * med)
        x = np.zeros_like(d)
        x[ok] = np.clip((1.0 / d[ok] - lo) / max(hi - lo, 1e-9), 0, 1)
        rgb = (cmap(x)[..., :3] * 255).astype(np.uint8)
        rgb[~ok] = 0
        out.append(rgb)
    return out


def pf_frames(frames, rps, K, vfov, k1):
    """Puffin's own perspective-field overlays (up arrows, latitude bands)."""
    import torch
    from scripts.evaluation.modules.pf_vis import build_offline_pf, render_pf_overlay_frame
    H, W = frames.shape[1:3]
    up_out, lat_out = [], []
    Ks = K if np.ndim(K) == 3 else [K] * len(frames)     # VGGT: one K per real frame
    for f, (r, p), Kt in zip(frames, rps, Ks):
        up, lat = build_offline_pf(f"{r} {p} {vfov} {k1}", H, W, np.array2string(np.asarray(Kt)))
        t = torch.from_numpy(f).permute(2, 0, 1).float() / 127.5 - 1.0
        up_out.append(render_pf_overlay_frame(t, up, 'up', out_size=(W, H)))
        lat_out.append(render_pf_overlay_frame(t, lat, 'lat', out_size=(W, H)))
    return up_out, lat_out


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
CLOUD_SOURCES = {          # role -> files in the scene folder, concatenated
    'single': dict(real=['photo.ply'], generated=['generated.ply']),
    'multiseed': dict(real=['real_unity.ply'], generated=['generated.ply']),
    'real': dict(real=['real_unity.ply']),
}


def export_clouds(scene, out, kind, voxel=0.02):
    """Headset-sized clouds with fixed role names in world_state/clouds/
    (full = real + generated), so world_state.json lists exactly what ships."""
    from common.pointcloud import read_ply, write_ply
    from generation.multiseed import voxel_merge
    (out / 'clouds').mkdir(exist_ok=True)
    parts, listed = {}, {}
    for role, files in CLOUD_SOURCES[kind].items():
        clouds = [read_ply(scene / f) for f in files]
        parts[role] = (np.concatenate([c[0] for c in clouds]).astype(np.float64),
                       np.concatenate([c[1] for c in clouds]))
    parts['full'] = (np.concatenate([p[0] for p in parts.values()]),
                     np.concatenate([p[1] for p in parts.values()]))
    for role, (pts, rgb) in parts.items():
        P, C = voxel_merge(pts, rgb, voxel)
        write_ply(out / 'clouds' / f'{role}.ply', P, C)
        listed[role] = dict(file=f'clouds/{role}.ply', points=int(len(P)), voxel_m=voxel)
    return listed


def export(scene, model=None, measure_every=7, media=True):
    from generation import puffin_runtime  # noqa: F401  (upstream on sys.path)
    from scripts.evaluation.modules import save_frames_as_mp4

    runs, (R, d, s), caption, kind = load_runs(scene)
    out = scene / 'world_state'
    out.mkdir(exist_ok=True)
    # Measuring costs GPU time: carry earlier measurements over (they are
    # camera-frame quantities, independent of the scene's leveling).
    old = {}
    if (out / 'world_state.json').exists():
        prev = json.loads((out / 'world_state.json').read_text())
        old = {(rn, v['index']): v['measured'] for rn, r in prev['runs'].items()
               for v in r['views'] if 'measured' in v}
        caption = caption or prev.get('caption')
    up_w = S @ R.T @ np.array([0.0, 1.0, 0.0])       # world up in the OpenCV fusion frame
    measure = model is not None
    if measure:
        from generation import puffin_runtime as pr
        from PIL import Image

    state = dict(
        kind=kind,
        conventions=('Unity frame: +x right, +y up, +z forward, meters, floor y=0. '
                     'Angles in degrees. roll/pitch follow Puffin-World (pitch < 0 = looking '
                     'down). c2w_unity columns = camera right / up / forward / position.'),
        gravity_unity=[0.0, -1.0, 0.0],
        caption=caption,
        runs={})
    err = {'gen': [], 'real': []}
    for name, run in runs:
        frames, c2w, K = run['frames'], run['c2w'], run['K']
        views, rps_cond = [], []
        for t in range(len(frames)):
            sr, sp = roll_pitch(c2w[t][:3, :3].T @ up_w)
            view = dict(index=t, c2w_unity=unity_c2w(c2w[t], R, d, s).round(5).tolist(),
                        scene=dict(roll=round(math.degrees(sr), 3), pitch=round(math.degrees(sp), 3)))
            if run['generated']:
                rel = run.get('c2w_rel', c2w)[t][:3, :3]
                cr, cp = roll_pitch(rel.T @ up_from_rp(*run['seed_rp']))
                view['conditioned'] = dict(roll=round(math.degrees(cr), 3), pitch=round(math.degrees(cp), 3))
                rps_cond.append((cr, cp))
            else:
                rps_cond.append((sr, sp))
            ref_rp = view.get('conditioned', view['scene'])
            if (name, t) in old and not measure:
                view['measured'] = m = old[(name, t)]
                err['gen' if run['generated'] else 'real'].append(
                    (abs(m['roll'] - ref_rp['roll']), abs(m['pitch'] - ref_rp['pitch'])))
            if measure and t % measure_every == 0 and (t > 0 or not run['generated']):
                text = puffin_runtime.image_to_text(model, Image.fromarray(frames[t]))
                cap, (mr, mp, mv, _) = puffin_runtime.split_caption(text)
                ref = view.get('conditioned', view['scene'])
                view['measured'] = dict(roll=round(math.degrees(mr), 3), pitch=round(math.degrees(mp), 3),
                                        vfov=round(math.degrees(mv), 3))
                e = (abs(math.degrees(wrap(mr)) - ref['roll']), abs(math.degrees(mp) - ref['pitch']))
                err['gen' if run['generated'] else 'real'].append(e)
                if state['caption'] is None:
                    state['caption'] = cap
            views.append(view)

        files = {}
        if media:
            save_frames_as_mp4(list(frames), str(out / f'{name}-rgb.mp4'), fps=8)
            files['rgb'] = f'{name}-rgb.mp4'
            if run['depths'] is not None:
                save_frames_as_mp4(depth_frames(run['depths']), str(out / f'{name}-depth.mp4'), fps=8)
                files['depth'] = f'{name}-depth.mp4'
            up, lat = pf_frames(frames, rps_cond, K, run['vfov'], run['k1'])
            save_frames_as_mp4(up, str(out / f'{name}-pf_up.mp4'), fps=8)
            save_frames_as_mp4(lat, str(out / f'{name}-pf_lat.mp4'), fps=8)
            files.update(pf_up=f'{name}-pf_up.mp4', pf_lat=f'{name}-pf_lat.mp4')
        state['runs'][name] = dict(
            generated=run['generated'], frames=len(frames), fps=8, files=files,
            vfov=round(math.degrees(run['vfov']), 3),
            seed=None if run['seed_rp'] is None else dict(
                roll=round(math.degrees(run['seed_rp'][0]), 3),
                pitch=round(math.degrees(run['seed_rp'][1]), 3)),
            views=views)
        print(f"  {name}: {len(frames)} views" + (f", files {sorted(files)}" if files else ''), flush=True)

    def summary(es, against):
        if not es:
            return None
        a = np.array(es)
        return dict(against=against, views=len(es),
                    roll_err_deg_median=round(float(np.median(a[:, 0])), 2),
                    pitch_err_deg_median=round(float(np.median(a[:, 1])), 2),
                    roll_err_deg_p90=round(float(np.percentile(a[:, 0], 90)), 2),
                    pitch_err_deg_p90=round(float(np.percentile(a[:, 1], 90)), 2))
    state['physics_check'] = dict(
        generated=summary(err['gen'], 'conditioned (what Puffin was told)'),
        real=summary(err['real'], 'scene (VGGT-leveled real cameras)'))
    state['clouds'] = export_clouds(scene, out, kind)
    (out / 'world_state.json').write_text(json.dumps(state, indent=1))
    pc = state['physics_check']
    print(f"{scene.name}: {kind}, {len(runs)} runs | physics check: "
          f"generated {pc['generated']} | real {pc['real']}", flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('scenes', nargs='+')
    p.add_argument('--measure', action='store_true',
                   help="read roll/pitch/vfov back with Puffin's perception branch (GPU)")
    p.add_argument('--measure_every', type=int, default=7,
                   help='measure every n-th view (7 = once per chunk)')
    p.add_argument('--no_media', action='store_true')
    args = p.parse_args()
    scenes = [Path(os.path.abspath(s)) for s in args.scenes]
    model = None
    if args.measure:
        from generation import puffin_runtime as pr
        model = pr.load_model('pro', geometry=False)
    for scene in scenes:
        export(scene, model, args.measure_every, media=not args.no_media)


if __name__ == '__main__':
    main()
