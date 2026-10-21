"""Puffin-World scene -> textured depth meshes for Unity (one per view).

Each kept view's depth map becomes a triangle grid in 3D, textured with that
view's image: continuous surfaces at the image's full sharpness instead of
points. Triangles across a depth jump are dropped (no rubber sheets between
foreground and background), and the sky is pushed onto a far shell so it stays
a backdrop instead of vanishing.

Depths are put on the same scale as the dense point cloud (run alignment +
upstream's per-view and global gauge solves), and everything goes through the
same leveling / scale as the .json next to that cloud, so the meshes sit where
the points do (Unity frame: meters, floor y = 0, seed camera at (0, 1.5, 0)).

Turns overlap a lot, so only every --every-th view is used and only its middle
--keep_frac of columns (the outermost views keep their outer side).

    python -m puffin_fusion.depth_mesh ../data/vrwd_scenes/v2/text \\
        ../data/vrwd_scenes/v2/text/scene_dense.json \\
        --out ../unity/vr-director/Assets/Meshes/Puffin/PlazaMesh
Then Unity: VR Director > Build Puffin Mesh Worlds.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

from puffin_fusion.dense_fuse import load_reconstruction
from common.pointcloud import OPENCV_TO_UNITY


def aligned_depths(rec, depths, poses, K):
    """Upstream export_reconstruction_glb's per-view + global gauge solves."""
    views = [dict(depth=np.where(np.isfinite(d) & (d > 0), d, 0.0).astype(np.float64),
                  K=rec._rescale_K(K, d.shape[1], d.shape[0]), c2w=P) for d, P in zip(depths, poses)]
    m = rec.solve_per_view_depth_scales(views)
    for v, mv in zip(views, m):
        v['depth'] = v['depth'] * mv
    s = rec.solve_depth_pose_scale(views)
    return [v['depth'] * s for v in views]


def view_mesh(depth, K, c2w, to_unity, cols, stride, edge_tol, sky_m, scale, backdrop=True):
    """Grid mesh of one view in Unity coordinates: vertices, uvs, triangles."""
    H, W = depth.shape
    valid = np.isfinite(depth) & (depth > 0)
    dv = depth[valid]
    far = min(20.0 * float(np.median(dv)), float(np.percentile(dv, 98)), sky_m / scale)
    d = np.where(valid, np.minimum(depth, far), far)        # sky / holes -> far shell
    sky = ~valid | (depth >= far)

    ys = np.arange(0, H, stride)
    xs = np.arange(cols[0], cols[1], stride)
    gx, gy = np.meshgrid(xs, ys)
    z = d[gy, gx]
    cam = np.stack([(gx + 0.5 - K[0, 2]) / K[0, 0] * z, (gy + 0.5 - K[1, 2]) / K[1, 1] * z, z], -1)
    world = cam.reshape(-1, 3) @ c2w[:3, :3].T + c2w[:3, 3]
    verts = to_unity(world)
    uv = np.stack([(gx + 0.5) / W, 1.0 - (gy + 0.5) / H], -1).reshape(-1, 2)

    h, w = gy.shape
    idx = np.arange(h * w).reshape(h, w)
    a, b, c, e = idx[:-1, :-1], idx[:-1, 1:], idx[1:, :-1], idx[1:, 1:]
    zf, skf = z.reshape(-1), sky[gy, gx].reshape(-1)
    tris, cut = [], []
    for t in (np.stack([a, c, b], -1), np.stack([b, c, e], -1)):
        t = t.reshape(-1, 3)
        zt = zf[t]
        same_sky = skf[t].all(1) | ~skf[t].any(1)              # never bridge sky and ground
        smooth = zt.max(1) / np.maximum(zt.min(1), 1e-9) < 1 + edge_tol
        tris.append(t[same_sky & smooth])
        cut.append(t[~(same_sky & smooth)])
    tris, cut = np.concatenate(tris), np.concatenate(cut)
    if not backdrop or len(cut) == 0:
        return verts, uv, tris

    # Backdrop: each cut triangle again, pushed back to its farthest corner's depth and
    # colored with that corner's pixel. It sits behind the foreground, so it only shows
    # where the viewer looks behind an edge: background color there instead of black.
    far_corner = cut[np.arange(len(cut)), np.argmax(zf[cut], 1)]
    rays = (cam.reshape(-1, 3) / zf[:, None])[cut]             # [n, 3, 3] unit-depth rays
    back_cam = rays * zf[far_corner][:, None, None]
    back = to_unity(back_cam.reshape(-1, 3) @ c2w[:3, :3].T + c2w[:3, 3])
    back_uv = np.repeat(uv[far_corner], 3, axis=0)
    n = len(verts)
    return (np.concatenate([verts, back]), np.concatenate([uv, back_uv]),
            np.concatenate([tris, n + np.arange(3 * len(cut)).reshape(-1, 3)]))


def write_obj(path, verts, uv, tris, texture):
    # Unity's OBJ importer flips x (right- to left-handed): pre-flip so the mesh lands as is.
    v = verts * [-1.0, 1.0, 1.0]
    with open(path, 'w') as f:
        f.write(f'mtllib {path.stem}.mtl\nusemtl view\n')
        np.savetxt(f, v, fmt='v %.4f %.4f %.4f')
        np.savetxt(f, uv, fmt='vt %.5f %.5f')
        t = tris + 1
        np.savetxt(f, np.stack([t[:, 0], t[:, 0], t[:, 1], t[:, 1], t[:, 2], t[:, 2]], 1), fmt='f %d/%d %d/%d %d/%d')
    path.with_suffix('.mtl').write_text(f'newmtl view\nKd 1 1 1\nmap_Kd {texture}\n')


def panorama(views, R_unity, size=(1024, 512)):
    """360 x 180 equirectangular image (row 0 = straight up) from every view's pixels by
    direction, gaps filled by stretching the nearest colors and blurring: a backdrop for
    whatever no view covers (above / below the generated strip, behind you, seams)."""
    from PIL import ImageFilter
    from scipy.ndimage import binary_erosion
    W, H = size
    acc, cnt = np.zeros((H, W, 3)), np.zeros((H, W))
    for img, K, c2w in views:
        h, w = img.shape[:2]
        gy, gx = np.mgrid[0:h:2, 0:w:2]
        ray = np.stack([(gx + 0.5 - K[0, 2]) / K[0, 0], (gy + 0.5 - K[1, 2]) / K[1, 1], np.ones(gx.shape)], -1)
        d = ray.reshape(-1, 3) @ c2w[:3, :3].T @ OPENCV_TO_UNITY.T @ R_unity.T
        d /= np.linalg.norm(d, axis=1, keepdims=True)
        u = ((np.arctan2(d[:, 0], d[:, 2]) + np.pi) / (2 * np.pi) * W).astype(int) % W
        v = np.clip(((np.pi / 2 - np.arcsin(np.clip(d[:, 1], -1, 1))) / np.pi * H).astype(int), 0, H - 1)
        np.add.at(acc, (v, u), img[gy, gx].reshape(-1, 3))
        np.add.at(cnt, (v, u), 1)
    have = cnt > 0
    pano = np.where(have[..., None], acc / np.maximum(cnt, 1)[..., None], 0)
    cols = np.where(have.any(0))[0]
    # Above / below the strip: the edge colors, smoothed sideways, fading to one sky
    # (ground) color toward the pole, so no vertical streaks.
    from scipy.ndimage import uniform_filter1d
    top = np.array([np.where(have[:, x])[0][0] for x in cols])
    bot = np.array([np.where(have[:, x])[0][-1] for x in cols])
    top_c = uniform_filter1d(pano[top, cols], 41, axis=0, mode='nearest')
    bot_c = uniform_filter1d(pano[bot, cols], 41, axis=0, mode='nearest')
    sky_c, ground_c = np.median(pano[top, cols], 0), np.median(pano[bot, cols], 0)
    for x, t0, b0, tc, bc in zip(cols, top, bot, top_c, bot_c):
        f = (np.arange(t0) / max(t0, 1))[:, None]             # 0 at the pole, 1 at the strip
        pano[:t0, x] = f * tc + (1 - f) * sky_c
        n = H - 1 - b0
        g = (np.arange(1, n + 1) / max(n, 1))[:, None]        # 0 at the strip, 1 at the pole
        pano[b0 + 1:, x] = (1 - g) * bc + g * ground_c
    if 0 < len(cols) < W:                                    # behind you: blend around
        xs = np.arange(W)
        ext = np.concatenate([cols - W, cols, cols + W])
        for c in range(3):
            vals = np.concatenate([pano[:, cols, c]] * 3, 1)
            pano[:, :, c] = np.stack([np.interp(xs, ext, r) for r in vals])
    img = Image.fromarray(pano.clip(0, 255).astype(np.uint8))
    blur = np.asarray(img.filter(ImageFilter.GaussianBlur(10)), dtype=np.float64)
    keep = binary_erosion(have, iterations=3)[..., None]
    return np.where(keep, pano, blur).astype(np.uint8)


def dome_mesh(center, radius, rows=48, cols=96):
    el = np.linspace(-np.pi / 2, np.pi / 2, rows + 1)
    az = np.linspace(-np.pi, np.pi, cols + 1)
    A, E = np.meshgrid(az, el)
    verts = center + radius * np.stack([np.cos(E) * np.sin(A), np.sin(E), np.cos(E) * np.cos(A)], -1).reshape(-1, 3)
    uv = np.stack([(A + np.pi) / (2 * np.pi), (E + np.pi / 2) / np.pi], -1).reshape(-1, 2)
    idx = np.arange((rows + 1) * (cols + 1)).reshape(rows + 1, cols + 1)
    a, b, c, e = idx[:-1, :-1], idx[:-1, 1:], idx[1:, :-1], idx[1:, 1:]
    tris = np.concatenate([np.stack([a, c, b], -1).reshape(-1, 3), np.stack([b, c, e], -1).reshape(-1, 3)])
    return verts, uv, tris


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('scene_dir', help='folder with raw.npz')
    p.add_argument('scene_json', help='json written with the dense cloud (trajectories_unity_c2w, scale)')
    p.add_argument('--out', required=True, help='output folder (one .obj + .png per view)')
    p.add_argument('--runs', nargs='*', default=None, help='default: all turn runs (not walk)')
    p.add_argument('--every', type=int, default=4, help='use every N-th view of a run')
    p.add_argument('--keep_frac', type=float, default=0.8,
                   help='middle fraction of columns per view (overlap hides seams off the seed spot)')
    p.add_argument('--no_dome', action='store_true', help='no 360 backdrop dome')
    p.add_argument('--stride', type=int, default=2, help='pixels per grid cell')
    p.add_argument('--edge_tol', type=float, default=0.15,
                   help='relative depth jump that cuts a triangle (far ground is seen at a grazing '
                        'angle, so its depth changes fast: 0.05 cut it into stripes)')
    p.add_argument('--no_backdrop', action='store_true',
                   help='leave holes behind depth edges black (default: fill with the background color)')
    p.add_argument('--sky_m', type=float, default=150.0,
                   help='sky and anything farther goes on a shell this far (m); inside the cameras\' far clip')
    p.add_argument('--upscale', action='store_true', help='4x Real-ESRGAN textures')
    args = p.parse_args()

    raw = np.load(Path(args.scene_dir) / 'raw.npz')
    meta = json.loads(Path(args.scene_json).read_text())
    K = raw['K'].astype(np.float64)
    runs = [str(r) for r in raw['runs']]
    use = args.runs or [r for r in runs if r != 'walk']

    # Seed-frame OpenCV -> Unity, recovered from the seed pose (identity) in the json:
    # unity = (R S p + [0, d, 0]) * scale, so its rotation is R and its position (0, d*scale, 0).
    M0 = np.asarray(meta['trajectories_unity_c2w'][runs[0]][0])
    R, scale = M0[:3, :3], float(meta['scale_to_meters'])
    off = M0[:3, 3]

    def to_unity(pts):
        return (pts @ OPENCV_TO_UNITY.T) @ R.T * scale + off

    rec = load_reconstruction()
    up = None
    if args.upscale:
        from puffin_fusion.to_3dgs_dataset import upscaler
        up = upscaler()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ref = raw[f'{runs[0]}_depths'][0].astype(np.float32)
    total_v = total_t = 0
    pano_views = []
    for run in use:
        frames, poses = raw[f'{run}_frames'], raw[f'{run}_poses'].astype(np.float64)
        d = raw[f'{run}_depths'].astype(np.float32)
        ok = (ref > 0) & (d[0] > 0)
        d *= float(np.median(ref[ok] / d[0][ok]))              # same run scale as the fusion
        depths = aligned_depths(rec, list(d), list(poses), K)
        last = len(frames) - 1
        picks = list(range(0 if run == use[0] else args.every, last + 1, args.every))
        if picks[-1] != last:
            if last - picks[-1] < args.every / 2:
                picks.pop()
            picks.append(last)
        # which image side points outward at the end of this turn: the camera's yaw sign
        yaw = (poses[last][:3, :3] @ [0, 0, 1])[0]
        pano_views += [(frames[i], K, poses[i]) for i in range(len(frames))]
        for i in picks:
            W = depths[i].shape[1]
            half = args.keep_frac * W / 2
            lo, hi = int(W / 2 - half), int(W / 2 + half)
            if i == last:
                lo, hi = (0, hi) if yaw < 0 else (lo, W)
            if i == 0 and len(use) == 1:
                lo, hi = 0, W
            verts, uv, tris = view_mesh(depths[i], K, poses[i], to_unity, (lo, hi), args.stride,
                                         args.edge_tol, args.sky_m, scale, not args.no_backdrop)
            name = f'{run}_{i:02d}'
            img = frames[i]
            Image.fromarray(up(img) if up else img).save(out / f'{name}.png')
            write_obj(out / f'{name}.obj', verts, uv, tris, f'{name}.png')
            total_v += len(verts)
            total_t += len(tris)
            print(f'{name}: cols {lo}-{hi}, {len(verts)} vertices, {len(tris)} triangles', flush=True)
    if not args.no_dome:
        Image.fromarray(panorama(pano_views, R)).save(out / 'dome.png')
        write_obj(out / 'dome.obj', *dome_mesh(off, args.sky_m + 20), 'dome.png')
    print(f'{total_v} vertices, {total_t} triangles -> {out}')


if __name__ == '__main__':
    main()
