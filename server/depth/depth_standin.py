"""Stand-in for Puffin-World while we have no GPU: single-view metric depth
from Depth Anything V2 (indoor) -> colored point cloud in Unity coordinates.

Reads the output of prepare_photo.py (input.png + camera.json) and writes
depth.npy, depth_vis.png and scene_unity.ply into the same directory.
The PLY is leveled on the detected floor: floor at y=0, camera at
(0, camera height, 0) looking roughly down +z.

Usage:
    python -m depth.depth_standin outputs/test-room0
"""
import argparse
import json
import os

import numpy as np
import torch
from PIL import Image
from transformers import AutoImageProcessor, AutoModelForDepthEstimation

from common.pointcloud import (edge_mask, fit_floor, level_to_floor, opencv_to_unity,
                        unproject, write_ply)

MODEL = 'depth-anything/Depth-Anything-V2-Metric-Indoor-Small-hf'


def estimate_depth(img, device):
    processor = AutoImageProcessor.from_pretrained(MODEL)
    model = AutoModelForDepthEstimation.from_pretrained(MODEL).to(device).eval()
    inputs = processor(images=img, return_tensors='pt').to(device)
    with torch.no_grad():
        pred = model(**inputs).predicted_depth  # (1, h, w), meters
    pred = torch.nn.functional.interpolate(
        pred[:, None], size=img.size[::-1], mode='bicubic', align_corners=False)
    return pred[0, 0].clamp(min=1e-3).cpu().numpy()


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('scene_dir', help='directory with input.png + camera.json')
    p.add_argument('--edge_thresh', type=float, default=0.04,
                   help='relative depth jump that marks a flying pixel')
    p.add_argument('--camera_height', type=float, default=None,
                   help='rescale so the photo camera is this many meters above '
                        'the floor (fixes the depth model\'s scale error)')
    args = p.parse_args()

    device = 'mps' if torch.backends.mps.is_available() else 'cpu'
    img = Image.open(os.path.join(args.scene_dir, 'input.png')).convert('RGB')
    with open(os.path.join(args.scene_dir, 'camera.json')) as f:
        cam = json.load(f)
    K = np.array([[cam['fx'], 0, cam['cx']],
                  [0, cam['fy'], cam['cy']],
                  [0, 0, 1]])

    depth = estimate_depth(img, device)
    np.save(os.path.join(args.scene_dir, 'depth.npy'), depth)
    vis = (255 * (1 - (depth - depth.min()) / (np.ptp(depth) + 1e-6))).astype(np.uint8)
    Image.fromarray(vis).save(os.path.join(args.scene_dir, 'depth_vis.png'))

    keep = edge_mask(depth, args.edge_thresh)
    points = opencv_to_unity(unproject(depth, K)[keep])
    colors = np.asarray(img)[keep]

    # Stand-in for Puffin's roll/pitch estimate: level the cloud on the floor.
    normal, d = fit_floor(points)
    points, R, cam_height = level_to_floor(points, normal, d)
    tilt = np.degrees(np.arccos(np.clip(normal[1], -1, 1)))
    scale = args.camera_height / cam_height if args.camera_height else 1.0
    points *= scale  # uniform scale about the floor point below the camera
    cam['standin'] = dict(depth_model=MODEL, floor_tilt_deg=float(tilt),
                          estimated_camera_height_m=float(cam_height),
                          scale=float(scale),
                          camera_height_m=float(cam_height * scale),
                          camera_rotation_unity=R.tolist())
    with open(os.path.join(args.scene_dir, 'camera.json'), 'w') as f:
        json.dump(cam, f, indent=2)

    out = os.path.join(args.scene_dir, 'scene_unity.ply')
    write_ply(out, points, colors)
    print(f"depth {depth.min():.2f}-{depth.max():.2f} m (median {np.median(depth):.2f}) | "
          f"floor tilt {tilt:.1f} deg, camera height {cam_height:.2f} m "
          f"-> x{scale:.2f} = {cam_height * scale:.2f} m | "
          f"{keep.sum()}/{keep.size} points -> {out}")


if __name__ == '__main__':
    main()
