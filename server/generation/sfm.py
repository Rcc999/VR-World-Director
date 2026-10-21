"""Camera poses for a set of seed photos with COLMAP (pycolmap, CPU).

Multi-photo scenes need every photo's pose in one frame before Puffin-World
generates around each of them. Images must already be upright (EXIF applied):
COLMAP ignores the orientation tag, Puffin must see the same pixels.

Writes <scene_dir>/sparse/ (COLMAP model) and <scene_dir>/cameras.json:
  images:  {name: {c2w: 4x4 OpenCV camera-to-world, K: 3x3, width, height}}
  points:  sparse 3D points [x, y, z] in the same frame (COLMAP's arbitrary
           scale and orientation), with per-image observations so each
           photo's generated depth can be scaled to it.

    ~/venvs/colmap/bin/python -m generation.sfm $SCRATCH/sfm/livingroom --f35 24
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np


def main():
    p = argparse.ArgumentParser()
    p.add_argument('scene_dir', help='directory with images/ (upright JPEGs)')
    p.add_argument('--f35', type=float, default=None,
                   help='35mm-equivalent focal length from EXIF, as the focal prior')
    args = p.parse_args()

    import pycolmap
    from PIL import Image

    scene = Path(args.scene_dir)
    images = scene / 'images'
    db = scene / 'database.db'
    sparse = scene / 'sparse'
    db.unlink(missing_ok=True)
    sparse.mkdir(exist_ok=True)

    w, h = Image.open(next(images.iterdir())).size
    reader = pycolmap.ImageReaderOptions()
    reader.camera_model = 'SIMPLE_RADIAL'
    if args.f35:
        # 35mm-equivalent focal is defined against the 43.27 mm full-frame diagonal.
        f = args.f35 / 43.27 * math.hypot(w, h)
        reader.camera_params = f"{f:.1f},{w / 2:.1f},{h / 2:.1f},0"

    pycolmap.extract_features(db, images, camera_mode=pycolmap.CameraMode.SINGLE,
                              reader_options=reader)
    pycolmap.match_exhaustive(db)
    recs = pycolmap.incremental_mapping(db, images, sparse)
    if not recs:
        raise SystemExit('COLMAP registered no images')
    rec = max(recs.values(), key=lambda r: r.num_reg_images())
    n_all = len(list(images.iterdir()))
    print(f"registered {rec.num_reg_images()}/{n_all} images, "
          f"{rec.num_points3D()} points, {len(recs)} model(s)")

    out_images = {}
    for img in rec.images.values():
        if not img.has_pose:
            continue
        cam = rec.cameras[img.camera_id]
        w2c = np.eye(4)
        w2c[:3, :4] = img.cam_from_world().matrix()
        K = cam.calibration_matrix()
        out_images[img.name] = dict(c2w=np.linalg.inv(w2c).tolist(), K=K.tolist(),
                                    width=cam.width, height=cam.height,
                                    radial=cam.params[3:].tolist())
    pids = sorted(rec.points3D)
    index = {pid: i for i, pid in enumerate(pids)}
    xyz = [rec.points3D[pid].xyz.tolist() for pid in pids]
    obs = {}
    for img in rec.images.values():
        if img.has_pose:
            obs[img.name] = [index[p2.point3D_id] for p2 in img.points2D if p2.has_point3D()]
    missing = sorted(set(x.name for x in images.iterdir()) - set(out_images))
    (scene / 'cameras.json').write_text(json.dumps(dict(
        images=out_images, missing=missing,
        points=dict(xyz=xyz, observed_by=obs)), indent=None))
    centers = np.array([np.array(v['c2w'])[:3, 3] for v in out_images.values()])
    spread = np.ptp(centers, axis=0)
    print(f"camera centers spread (COLMAP units): {np.round(spread, 2)}; "
          f"focal {np.array(next(iter(out_images.values()))['K'])[0, 0]:.0f} px; "
          f"missing: {missing or 'none'}")


if __name__ == '__main__':
    main()
