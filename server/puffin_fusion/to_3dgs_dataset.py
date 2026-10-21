"""Puffin-World scene -> a COLMAP-format dataset to train a 3DGS with Brush.

Uses Puffin's own cameras (no COLMAP solve): the generated views of raw.npz,
optionally upscaled 4x with Real-ESRGAN (Puffin renders 640x640, about half
the sharpness a headset shows), the camera paths dense_fuse.py wrote in the
Unity frame (meters, floor y = 0), and its dense cloud to start the Gaussians.

COLMAP is right-handed and Unity left-handed, so everything is written in
W = Unity with y flipped (y down). Back in Unity that is a Transform with
scale (1, -1, 1), written next to the trained splat by --unity_transform.

    python -m puffin_fusion.to_3dgs_dataset ../data/vrwd_scenes/raw/text \\
        ../data/vrwd_scenes/dense/Plaza --keep_views pan=15 --upscale \\
        --out outputs/puffin_3dgs/Plaza
    splat_train/train_brush.sh outputs/puffin_3dgs/Plaza
"""
import argparse
import json
import struct
from pathlib import Path

import numpy as np
from PIL import Image

SERVER_DIR = Path(__file__).resolve().parents[1]
ESRGAN = SERVER_DIR / 'tools/upscale/RealESRGAN_x4plus.pth'
FLIP_Y = np.diag([1.0, -1.0, 1.0])


def rotmat_to_qvec(R):
    """3x3 rotation -> COLMAP quaternion (w, x, y, z)."""
    K = np.array([
        [R[0, 0] - R[1, 1] - R[2, 2], 0, 0, 0],
        [R[1, 0] + R[0, 1], R[1, 1] - R[0, 0] - R[2, 2], 0, 0],
        [R[2, 0] + R[0, 2], R[2, 1] + R[1, 2], R[2, 2] - R[0, 0] - R[1, 1], 0],
        [R[1, 2] - R[2, 1], R[2, 0] - R[0, 2], R[0, 1] - R[1, 0], R[0, 0] + R[1, 1] + R[2, 2]],
    ]) / 3.0
    w, V = np.linalg.eigh(K)
    q = V[[3, 0, 1, 2], np.argmax(w)]
    return q if q[0] >= 0 else -q


def read_ply_xyzrgb(path):
    with open(path, 'rb') as f:
        header = []
        while (line := f.readline().decode('ascii').strip()) != 'end_header':
            header.append(line)
        n = int(next(l for l in header if l.startswith('element vertex')).split()[-1])
        props = [l.split()[1:] for l in header if l.startswith('property')]
        types = {'float': '<f4', 'double': '<f8', 'uchar': 'u1'}
        a = np.frombuffer(f.read(), dtype=[(nm, types[t]) for t, nm in props], count=n)
    return (np.stack([a['x'], a['y'], a['z']], 1).astype(np.float64),
            np.stack([a['red'], a['green'], a['blue']], 1).astype(np.uint8))


def upscaler():
    import torch
    import spandrel
    model = spandrel.ModelLoader().load_from_file(str(ESRGAN)).eval()
    dev = 'mps' if torch.backends.mps.is_available() else 'cuda' if torch.cuda.is_available() else 'cpu'
    model.to(dev)

    def run(img):  # HxWx3 uint8 -> 4H x 4W x 3 uint8
        with torch.no_grad():
            x = torch.from_numpy(img).permute(2, 0, 1)[None].float().div(255).to(dev)
            y = model(x).clamp(0, 1)[0].permute(1, 2, 0).mul(255).round().byte().cpu().numpy()
        return y
    return run


def write_colmap(sparse, K, size, names, c2w_w, pts, rgb):
    """Binary COLMAP model: one PINHOLE camera, one image per view, the init points."""
    sparse.mkdir(parents=True, exist_ok=True)
    w, h = size
    with open(sparse / 'cameras.bin', 'wb') as f:
        f.write(struct.pack('<Q', 1))
        f.write(struct.pack('<iiQQ', 1, 1, w, h))  # id, PINHOLE, width, height
        f.write(struct.pack('<4d', K[0, 0], K[1, 1], K[0, 2], K[1, 2]))
    with open(sparse / 'images.bin', 'wb') as f:
        f.write(struct.pack('<Q', len(names)))
        for i, (name, M) in enumerate(zip(names, c2w_w), start=1):
            R = M[:3, :3].T  # world -> camera
            t = -R @ M[:3, 3]
            f.write(struct.pack('<i4d3di', i, *rotmat_to_qvec(R), *t, 1))
            f.write(name.encode() + b'\0')
            f.write(struct.pack('<Q', 0))  # no 2D observations
    with open(sparse / 'points3D.bin', 'wb') as f:
        f.write(struct.pack('<Q', len(pts)))
        for i, (p, c) in enumerate(zip(pts, rgb), start=1):
            f.write(struct.pack('<Q3d3BdQ', i, *p, *c, 0.0, 0))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('raw_dir', help='folder with raw.npz')
    p.add_argument('dense', help='dense_fuse.py output without extension (<name>.ply + <name>.json)')
    p.add_argument('--out', required=True)
    p.add_argument('--keep_views', nargs='*', default=[], metavar='RUN=N',
                   help='same as for dense_fuse.py (the json holds only those poses)')
    p.add_argument('--upscale', action='store_true', help='4x Real-ESRGAN on every view')
    p.add_argument('--init_points', type=int, default=1_000_000)
    args = p.parse_args()

    raw = np.load(Path(args.raw_dir) / 'raw.npz')
    meta = json.loads(Path(args.dense + '.json').read_text())
    keep = {k: int(v) for k, v in (kv.split('=') for kv in args.keep_views)}
    K = np.asarray(meta['intrinsics_640'], dtype=np.float64)
    out = Path(args.out)
    (out / 'images').mkdir(parents=True, exist_ok=True)
    up = upscaler() if args.upscale else None

    names, c2w_w = [], []
    for run, poses in meta['trajectories_unity_c2w'].items():
        frames = raw[f'{run}_frames'][:keep.get(run)]
        for i, (img, M) in enumerate(zip(frames, poses)):
            if i == 0 and names:
                continue  # every run starts from the same seed view
            M = np.asarray(M)
            # Unity c2w columns are right / up / forward; OpenCV wants right / down / forward,
            # and the world goes to W (y flipped) to be right-handed.
            Mw = np.eye(4)
            Mw[:3, :3] = FLIP_Y @ M[:3, :3] @ FLIP_Y
            Mw[:3, 3] = FLIP_Y @ M[:3, 3]
            name = f'{run}_{i:03d}.png'
            Image.fromarray(up(img) if up else img).save(out / 'images' / name)
            names.append(name)
            c2w_w.append(Mw)
            print(name, flush=True)

    s = 4.0 if up else 1.0
    Ks = K.copy()
    Ks[:2] *= s
    size = (int(round(640 * s)), int(round(640 * s)))

    pts, rgb = read_ply_xyzrgb(args.dense + '.ply')
    if len(pts) > args.init_points:
        idx = np.random.default_rng(0).choice(len(pts), args.init_points, replace=False)
        pts, rgb = pts[idx], rgb[idx]
    write_colmap(out / 'sparse' / '0', Ks, size, names, c2w_w, pts @ FLIP_Y, rgb)
    (out / 'unity.transform.json').write_text(json.dumps(
        {'position': [0, 0, 0], 'rotation': [0, 0, 0, 1], 'scale': [1, -1, 1]}, indent=2))
    print(f"{len(names)} views ({size[0]}x{size[1]}), {len(pts)} init points -> {out}")


if __name__ == '__main__':
    main()
