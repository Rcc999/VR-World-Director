"""GPU check that streaming.stream() matches upstream's chunked generation.

Generates a 2-chunk pan with depth three ways from the same seed:
  upstream   run_chunked_generation (via puffin_runtime.generate)
  stream     streaming.stream() in one call
  resumed    streaming.stream() as two calls, the second resuming the state
and reports the largest frame / depth differences (GPU nondeterminism leaves
a little noise), time to the first chunk, and a padded 3-view run.

    python -m generation.check_stream --image /seeds/test-room0.JPG
"""
import argparse
import os
import time

import numpy as np


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--image', required=True)
    p.add_argument('--model', default='pro')
    p.add_argument('--num_steps', type=int, default=10)
    args = p.parse_args()
    image = os.path.abspath(args.image)

    import torch
    from generation import puffin_runtime as pr
    from generation import scenes, streaming

    model = pr.load_model(args.model, geometry=True)
    seed_img, pil = pr.load_seed_image(image)
    _, cam = pr.understand(model, pil)
    K = pr.intrinsics_from_vfov(cam[2])
    poses = scenes.pan_poses(15, 5.0, scenes.gravity_up(cam[1]))   # seed + 14 = 2 chunks
    gen = lambda: torch.Generator(device=model.device).manual_seed(0)

    t0 = time.perf_counter()
    up = pr.generate(model, seed_img, poses, K, cam, num_steps=args.num_steps, seed=0)
    t_up = time.perf_counter() - t0
    up_frames = [((f.clamp(-1, 1) + 1) * 127.5).round().byte().permute(1, 2, 0).numpy()
                 for f in up['gen_images_tensor'][0].float().cpu()]
    up_depths = [np.asarray(d.float().cpu()) for d in up['depth_samples'][0]]

    def run(splits):
        state, g = streaming.seed_state(seed_img), gen()
        frames, depths, first = [], [], None
        t0 = time.perf_counter()
        for part in splits:
            for c in streaming.stream(model, state, part, K, cam,
                                      num_steps=args.num_steps, generator=g):
                first = first or time.perf_counter() - t0
                if not depths:
                    depths.append(c.anchor_depth)
                frames += c.frames
                depths += c.depths
        return frames, depths, first, time.perf_counter() - t0

    one = run([poses[1:]])
    two = run([poses[1:8], poses[8:]])

    def diff(name, frames, depths):
        f = max(np.abs(a.astype(int) - b.astype(int)).max() for a, b in zip(frames, up_frames))
        d = max(float(np.median(np.abs(a - b)[b > 0] / b[b > 0])) for a, b in zip(depths, up_depths))
        n = (len(frames), len(depths))
        ok = n == (len(up_frames), len(up_depths)) and f <= 8 and d < 0.02
        print(f"{name:8s} views {n} vs {(len(up_frames), len(up_depths))} | "
              f"max frame diff {f}/255 | worst median depth diff {d:.2%} | "
              f"{'OK' if ok else 'MISMATCH'}", flush=True)
        return ok

    print(f"upstream total {t_up:.1f} s")
    print(f"stream   first chunk {one[2]:.1f} s, total {one[3]:.1f} s")
    ok = diff('stream', one[0], one[1]) & diff('resumed', two[0], two[1])

    state = streaming.seed_state(seed_img)
    short = list(streaming.stream(model, state, poses[1:4], K, cam,
                                  num_steps=args.num_steps, generator=gen()))
    n = sum(len(c.frames) for c in short)
    print(f"padded   3 poses -> {n} frames, state at view {state.views_done - 1}")
    ok &= n == 3 and state.views_done == 4
    print('ok' if ok else 'FAILED')


if __name__ == '__main__':
    main()
