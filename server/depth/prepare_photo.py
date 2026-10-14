"""Turn a phone photo into Puffin-World's input: an upright, center-cropped
640x640 RGB image plus a pinhole camera (intrinsics + vertical FoV).

The focal length comes from the EXIF 35mm-equivalent focal length when
available, otherwise from --vfov_deg.

Usage:
    python -m depth.prepare_photo ../data/room/test-room0.JPG --out outputs/test-room0
"""
import argparse
import json
import math
import os

from PIL import Image, ImageOps

# 35mm film diagonal in mm: the reference for "equivalent" focal lengths.
FULL_FRAME_DIAG_MM = math.hypot(36.0, 24.0)


def focal_35mm_equiv(img):
    exif = img.getexif().get_ifd(0x8769)  # Exif sub-IFD
    f35 = exif.get(0xA405)  # FocalLengthIn35mmFilm
    return float(f35) if f35 else None


def prepare(path, res=640, vfov_deg=None):
    raw = Image.open(path)
    f35 = focal_35mm_equiv(raw)
    img = ImageOps.exif_transpose(raw).convert('RGB')
    w, h = img.size

    # Focal length in pixels of the full photo: an equivalent focal length
    # maps the image diagonal onto the 35mm diagonal.
    if vfov_deg is None:
        if f35 is None:
            raise ValueError(f"{path}: no EXIF focal length, pass --vfov_deg")
        f_px_full = f35 * math.hypot(w, h) / FULL_FRAME_DIAG_MM
    else:
        f_px_full = (h / 2) / math.tan(math.radians(vfov_deg) / 2)

    # Center square crop keeps the principal point at the center, then resize.
    s = min(w, h)
    left, top = (w - s) // 2, (h - s) // 2
    img = img.crop((left, top, left + s, top + s)).resize(
        (res, res), Image.Resampling.LANCZOS)

    f_px = f_px_full * res / s
    vfov = 2 * math.atan((res / 2) / f_px)
    camera = dict(
        width=res, height=res,
        fx=f_px, fy=f_px, cx=res / 2, cy=res / 2,
        vfov_rad=vfov, vfov_deg=math.degrees(vfov),
        source=os.path.basename(path), focal_35mm_equiv=f35,
        original_size=[w, h], crop_box=[left, top, left + s, top + s],
    )
    return img, camera


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('image')
    p.add_argument('--out', required=True, help='output directory')
    p.add_argument('--res', type=int, default=640)
    p.add_argument('--vfov_deg', type=float, default=None,
                   help='override vertical FoV of the full photo (no EXIF)')
    args = p.parse_args()

    img, camera = prepare(args.image, args.res, args.vfov_deg)
    os.makedirs(args.out, exist_ok=True)
    img.save(os.path.join(args.out, 'input.png'))
    with open(os.path.join(args.out, 'camera.json'), 'w') as f:
        json.dump(camera, f, indent=2)
    print(f"{args.out}/input.png  {args.res}x{args.res}  "
          f"f={camera['fx']:.1f}px  vfov={camera['vfov_deg']:.1f} deg")


if __name__ == '__main__':
    main()
