"""Extract sharp, color-consistent frames from phone videos for COLMAP / splatting.

- Decodes with ffmpeg (applies the phone's rotation flag) at --fps.
- iPhone HDR video (HLG, BT.2020) is converted to SDR sRGB with one fixed
  exposure for every frame, so the same wall has the same color in all frames.
  SDR videos are passed through.
- In each window of --keep_every frames, keeps the sharpest one
  (variance of the Laplacian), which drops motion-blurred frames.

Usage:
    python -m splat_train.video_to_frames ../data/room/vid0.MOV ../data/room/vid1.MOV ../data/room/vid2.MOV \
        --out outputs/room_splat/images
"""
import argparse
import json
import os
import subprocess

import numpy as np
from PIL import Image

# BT.2020 -> BT.709 primaries (linear light).
BT2020_TO_709 = np.array([[1.6605, -0.5876, -0.0728],
                          [-0.1246, 1.1329, -0.0083],
                          [-0.0182, -0.1006, 1.1187]])


def probe(path):
    out = subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
         'stream=width,height,color_transfer:stream_side_data=rotation',
         '-of', 'json', path], capture_output=True, text=True, check=True)
    s = json.loads(out.stdout)['streams'][0]
    rot = next((d['rotation'] for d in s.get('side_data_list', []) if 'rotation' in d), 0)
    w, h = s['width'], s['height']
    if abs(rot) == 90:
        w, h = h, w
    return w, h, s.get('color_transfer', '')


def hlg_to_srgb(e, gain):
    """HLG-encoded BT.2020 RGB in [0,1] -> 8-bit sRGB (BT.709)."""
    a, b, c = 0.17883277, 0.28466892, 0.55991073
    lin = np.where(e <= 0.5, e * e / 3.0, (np.exp((e - c) / a) + b) / 12.0)
    lin = np.clip(lin @ BT2020_TO_709.T, 0, None) * gain
    lin = lin / (1.0 + lin / 4.0) * 1.25  # soft shoulder: 1.0 stays ~1.0, highlights roll off
    srgb = np.where(lin <= 0.0031308, 12.92 * lin, 1.055 * np.power(lin, 1 / 2.4) - 0.055)
    return (np.clip(srgb, 0, 1) * 255 + 0.5).astype(np.uint8)


def sharpness(gray):
    g = gray.astype(np.float32)
    lap = (-4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:])
    return float(lap.var())


def frames(path, fps, long_side):
    w, h, transfer = probe(path)
    scale = long_side / max(w, h)
    ow, oh = int(round(w * scale / 2)) * 2, int(round(h * scale / 2)) * 2
    hdr = transfer in ('arib-std-b67', 'smpte2084')
    vf = f"fps={fps},scale={ow}:{oh}:flags=area"
    if hdr:
        vf += ":in_color_matrix=bt2020:in_range=tv"
    pix = 'rgb48le' if hdr else 'rgb24'
    proc = subprocess.Popen(['ffmpeg', '-v', 'error', '-i', path, '-vf', vf,
                             '-f', 'rawvideo', '-pix_fmt', pix, '-'],
                            stdout=subprocess.PIPE)
    nbytes = ow * oh * 3 * (2 if hdr else 1)
    while True:
        buf = proc.stdout.read(nbytes)
        if len(buf) < nbytes:
            break
        if hdr:
            yield np.frombuffer(buf, '<u2').reshape(oh, ow, 3) / 65535.0, True
        else:
            yield np.frombuffer(buf, np.uint8).reshape(oh, ow, 3), False
    proc.wait()


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('videos', nargs='+')
    p.add_argument('--out', required=True, help='output images directory')
    p.add_argument('--fps', type=float, default=6.0, help='decode rate before selection')
    p.add_argument('--keep_every', type=int, default=2,
                   help='keep the sharpest frame of each window of this many')
    p.add_argument('--long_side', type=int, default=1600, help='output long side in px')
    p.add_argument('--hdr_gain', type=float, default=2.0,
                   help='exposure for HLG video: linear scene value * gain = display value')
    args = p.parse_args()

    os.makedirs(args.out, exist_ok=True)
    total = 0
    for vi, path in enumerate(args.videos):
        window, kept = [], 0
        for idx, (frame, hdr) in enumerate(frames(path, args.fps, args.long_side)):
            rgb = hlg_to_srgb(frame, args.hdr_gain) if hdr else frame
            window.append((sharpness(rgb.mean(axis=2)), idx, rgb))
            if len(window) == args.keep_every:
                _, best_idx, best = max(window, key=lambda t: t[0])
                Image.fromarray(best).save(
                    os.path.join(args.out, f"v{vi}_{best_idx:04d}.jpg"), quality=95)
                window, kept = [], kept + 1
        print(f"{path}: kept {kept} frames")
        total += kept
    print(f"{total} frames -> {args.out}")


if __name__ == '__main__':
    main()
