"""GPU check that streaming.stream() matches upstream's chunked generation.

Generates a 2-chunk pan with depth from the same seed four ways:
  upstream, upstream2   run_chunked_generation twice: GPU nondeterminism
                        between identical runs is the noise floor
  stream                streaming.stream() in one call
  resumed               streaming.stream() as two calls, resuming the state
Per-view PSNR and depth difference against `upstream` are compared with the
noise floor; a contact sheet (rows: upstream / upstream2 / stream / resumed)
goes to outputs/check_stream.png. Also times the first chunk and runs a
padded 3-view path.

    python -m generation.check_stream --image /seeds/test-room0.JPG
"""
import argparse
import os
import time
from pathlib import Path

import numpy as np

SERVER_DIR = Path(__file__).resolve().parents[1]


def psnr(a, b):
    mse = np.mean((a.astype(np.float64) - b.astype(np.float64)) ** 2)
    return 99.0 if mse == 0 else 10 * np.log10(255.0 ** 2 / mse)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--image', required=True)
    p.add_argument('--model', default='pro')
    p.add_argument('--num_steps', type=int, default=10)
    args = p.parse_args()
    image = os.path.abspath(args.image)

    import torch
    from PIL import Image
    from generation import puffin_runtime as pr
    from generation import scenes, streaming

    model = pr.load_model(args.model, geometry=True)
    seed_img, pil = pr.load_seed_image(image)
    _, cam = pr.understand(model, pil)
    K = pr.intrinsics_from_vfov(cam[2])
    poses = scenes.pan_poses(15, 5.0, scenes.gravity_up(cam[1]))   # seed + 14 = 2 chunks
    to_u8 = lambda f: ((f.clamp(-1, 1) + 1) * 127.5).round().byte().permute(1, 2, 0).numpy()

    def upstream():
        r = pr.generate(model, seed_img, poses, K, cam, num_steps=args.num_steps, seed=0)
        return ([to_u8(f) for f in r['gen_images_tensor'][0].float().cpu()],
                [np.asarray(d.float().cpu()) for d in r['depth_samples'][0]])

    def run(splits):
        state = streaming.seed_state(seed_img)
        g = torch.Generator(device=model.device).manual_seed(0)
        frames, depths, first, t0 = [], [], None, time.perf_counter()
        for part in splits:
            for c in streaming.stream(model, state, part, K, cam,
                                      num_steps=args.num_steps, generator=g):
                first = first or time.perf_counter() - t0
                if not depths:
                    depths.append(c.anchor_depth)
                frames += c.frames
                depths += c.depths
        print(f"  first chunk after {first:.1f} s, total {time.perf_counter() - t0:.1f} s")
        return frames, depths

    runs = {'upstream': upstream(), 'upstream2': upstream(),
            'stream': run([poses[1:]]), 'resumed': run([poses[1:8], poses[8:]])}
    ref_f, ref_d = runs['upstream']

    def compare(name):
        frames, depths = runs[name]
        if (len(frames), len(depths)) != (len(ref_f), len(ref_d)):
            print(f"{name:9s} view count {len(frames)}/{len(depths)} vs {len(ref_f)}/{len(ref_d)}")
            return None
        ps = [psnr(a, b) for a, b in zip(frames, ref_f)]
        dd = [float(np.median(np.abs(a - b)[b > 0] / b[b > 0])) for a, b in zip(depths, ref_d)]
        print(f"{name:9s} PSNR vs upstream: mean {np.mean(ps):.1f} dB, worst {min(ps):.1f} dB "
              f"(chunk 1 {np.mean(ps[:7]):.1f}, chunk 2 {np.mean(ps[7:]):.1f}) | "
              f"depth diff median {np.median(dd):.2%}, worst {max(dd):.2%}", flush=True)
        return min(ps), max(dd)

    floor = compare('upstream2')
    ok = floor is not None
    for name in ('stream', 'resumed'):
        r = compare(name)
        # Pass if no worse than the run-to-run noise, with a 3 dB / 1 pt margin.
        ok &= r is not None and r[0] >= floor[0] - 3.0 and r[1] <= floor[1] + 0.01

    sheet = np.concatenate([np.concatenate(runs[k][0][::2], axis=1)
                            for k in ('upstream', 'upstream2', 'stream', 'resumed')], axis=0)
    Image.fromarray(sheet).resize((sheet.shape[1] // 4, sheet.shape[0] // 4)) \
        .save(SERVER_DIR / 'outputs' / 'check_stream.png')

    state = streaming.seed_state(seed_img)
    short = list(streaming.stream(model, state, poses[1:4], K, cam,
                                  num_steps=args.num_steps))
    n = sum(len(c.frames) for c in short)
    print(f"padded    3 poses -> {n} frames, state at view {state.views_done - 1}")
    ok &= n == 3 and state.views_done == 4
    print('ok' if ok else 'FAILED')


if __name__ == '__main__':
    main()
