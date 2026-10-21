"""Where do long pans break down? RGB-only sweep over CFG and step size.

The overnight 360-degree pans (11 chunks, CFG 4, 5 deg/view) darkened and
drifted chunk by chunk. This reruns the first chunks of a pan from the same
seeds with a few settings and logs the mean brightness per chunk (the seed's
brightness is the target) plus a contact sheet per run.

Seeds come from finished scenes (raw.npz frame 0 + meta.json camera), so the
text scene needs no T2I step.

    python -m generation.sweep_drift --scenes indoor text --chunks 4
"""
import argparse
import json
import os
import time
from pathlib import Path

import numpy as np

SERVER_DIR = Path(__file__).resolve().parents[1]
CONFIGS = [  # (cfg_scale, deg_per_view)
    (4.0, 5.0),   # overnight setting
    (2.0, 5.0),   # upstream world_modeling.py default CFG
    (2.0, 8.0),   # fewer chunks for the same angle
]


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--scenes', nargs='+', default=['indoor', 'text'])
    p.add_argument('--chunks', type=int, default=4)
    p.add_argument('--num_steps', type=int, default=50)
    p.add_argument('--out', default=str(SERVER_DIR / 'outputs' / 'sweep_drift'))
    args = p.parse_args()
    out = Path(os.path.abspath(args.out))
    out.mkdir(parents=True, exist_ok=True)
    scenes_dir = SERVER_DIR / 'outputs' / 'scenes'

    import torch
    from PIL import Image
    from generation import puffin_runtime as pr
    from generation import scenes

    model = pr.load_model('pro', geometry=False)     # RGB only: drift is visible there
    results = []
    for name in args.scenes:
        raw = np.load(scenes_dir / name / 'raw.npz')
        meta = json.loads((scenes_dir / name / 'meta.json').read_text())
        cam = tuple(meta['cam_rad'][k] for k in ('roll', 'pitch', 'vfov', 'k1'))
        seed_u8 = raw['pan_frames'][0]
        seed = torch.from_numpy(seed_u8).permute(2, 0, 1).float() / 127.5 - 1.0
        K = pr.intrinsics_from_vfov(cam[2])
        up = scenes.gravity_up(cam[1])
        for cfg, deg in CONFIGS:
            poses = scenes.pan_poses(pr.views_for_chunks(args.chunks), deg, up)
            t0 = time.perf_counter()
            r = pr.generate(model, seed, poses, K, cam, cfg_scale=cfg,
                            num_steps=args.num_steps, seed=42)
            frames = [seed_u8] + [((f.clamp(-1, 1) + 1) * 127.5).round().byte()
                                  .permute(1, 2, 0).numpy()
                                  for f in r['gen_images_tensor'][0].float().cpu()]
            bright = [float(np.mean(f)) for f in frames]
            per_chunk = [round(float(np.mean(bright[1 + 7 * k:8 + 7 * k])), 1)
                         for k in range(args.chunks)]
            tag = f"{name}_cfg{cfg:g}_deg{deg:g}"
            row = dict(scene=name, cfg=cfg, deg_per_view=deg,
                       total_deg=deg * (len(poses) - 1), seed_brightness=round(bright[0], 1),
                       chunk_brightness=per_chunk, seconds=round(time.perf_counter() - t0, 1))
            results.append(row)
            print(json.dumps(row), flush=True)
            # contact sheet: seed + the last view of every chunk
            picks = [frames[0]] + [frames[7 * (k + 1)] for k in range(args.chunks)]
            sheet = np.concatenate(picks, axis=1)
            Image.fromarray(sheet).resize((sheet.shape[1] // 3, sheet.shape[0] // 3)) \
                .save(out / f"{tag}.png")
    (out / 'results.json').write_text(json.dumps(results, indent=1))


if __name__ == '__main__':
    main()
