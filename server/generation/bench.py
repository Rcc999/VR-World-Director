"""WP0 benchmark: GPU memory and time per chunk for one Puffin-World model.

Times load, I2T on a seed photo, and chunked generation along a yaw pan at
1 and 3 chunks, with depth on and off. Time per extra chunk is
(t3 - t1) / 2. Results go to <out>/bench_<model>.json, plus the generated
frames for a visual check.

    python -m generation.bench --model pro --image ../data/room/test-room0.JPG
"""
import argparse
import json
import os
import time
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--model', choices=('pro', 'base'), default='pro')
    p.add_argument('--image', required=True)
    p.add_argument('--out', default=str(SERVER_DIR / 'outputs' / 'bench'))
    p.add_argument('--num_steps', type=int, default=50)
    p.add_argument('--deg_per_view', type=float, default=5.0)
    p.add_argument('--chunks', type=int, nargs='+', default=[1, 3])
    return p.parse_args()


def main():
    args = parse_args()
    # Resolve paths before puffin_runtime chdirs into the submodule.
    image = os.path.abspath(args.image)
    out = Path(os.path.abspath(args.out))
    out.mkdir(parents=True, exist_ok=True)

    import torch
    from generation import puffin_runtime as pr
    from scripts.evaluation.modules import save_frames_as_mp4, save_image_tensor

    def sync_time():
        torch.cuda.synchronize()
        return time.perf_counter()

    gib = lambda b: round(b / 2**30, 2)
    res = dict(model=args.model, gpu=torch.cuda.get_device_name(),
               num_steps=args.num_steps, runs=[])

    t0 = sync_time()
    model = pr.load_model(args.model, geometry=True)
    res['load_s'] = round(sync_time() - t0, 1)
    res['mem_after_load_gib'] = gib(torch.cuda.memory_allocated())
    print(json.dumps(res), flush=True)

    seed_img, pil = pr.load_seed_image(image)
    torch.cuda.reset_peak_memory_stats()
    t0 = sync_time()
    caption, cam = pr.understand(model, pil)
    res['i2t_s'] = round(sync_time() - t0, 1)
    res['i2t_peak_gib'] = gib(torch.cuda.max_memory_allocated())
    res['caption'], res['cam_params_rad'] = caption, cam
    K = pr.intrinsics_from_vfov(cam[2])
    print(f"caption: {caption[:200]}\ncam: {cam}", flush=True)

    for geometry in (False, True):
        model.geometry_state = geometry
        for n in args.chunks:
            poses = pr.yaw_pan(pr.views_for_chunks(n), args.deg_per_view)
            torch.cuda.empty_cache()
            torch.cuda.reset_peak_memory_stats()
            t0 = sync_time()
            r = pr.generate(model, seed_img, poses, K, cam,
                            num_steps=args.num_steps)
            run = dict(geometry=geometry, chunks=n, views=len(poses),
                       seconds=round(sync_time() - t0, 1),
                       peak_gib=gib(torch.cuda.max_memory_allocated()))
            res['runs'].append(run)
            print(json.dumps(run), flush=True)
            frames = [seed_img] + [f.float().cpu() for f in r['gen_images_tensor'][0]]
            tag = f"{args.model}_{'rgbd' if geometry else 'rgb'}_c{n}"
            save_frames_as_mp4([((f.clamp(-1, 1) + 1) * 127.5).byte()
                                .permute(1, 2, 0).numpy() for f in frames],
                               str(out / f"{tag}.mp4"), fps=6)
            save_image_tensor(frames[-1], str(out / f"{tag}_last.png"))

    for geometry in (False, True):
        t = {r['chunks']: r['seconds'] for r in res['runs'] if r['geometry'] == geometry}
        if 1 in t and len(t) > 1:
            n = max(t)
            res[f"per_extra_chunk_s_{'rgbd' if geometry else 'rgb'}"] = \
                round((t[n] - t[1]) / (n - 1), 1)
    res['peak_gib_overall'] = max(r['peak_gib'] for r in res['runs'])
    (out / f"bench_{args.model}.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == '__main__':
    main()
