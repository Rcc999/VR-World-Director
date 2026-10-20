# server

Builds 3D scenes and exports them in the Unity viewer's frame: floor at y = 0, meters, and
x = z = 0 where the capture was taken (the XR rig spawns there). Everything here runs on a Mac.

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-mac.txt
brew install ffmpeg colmap
```

Run every command **from `server/`** (scripts are modules). Outputs go to `server/outputs/` (git-ignored).

| Folder | What it does |
|---|---|
| `common/` | Shared code: PLY writing, axis conversion, floor leveling (`pointcloud.py`), splat + COLMAP reading and the map to the Unity frame (`splats.py`). |
| `depth/` | One photo → metric depth (Depth Anything V2) → point cloud. Only covers what the photo sees. |
| `splat_train/` | Videos → frames → camera poses (COLMAP) → Gaussian splat (Brush). Shared by the next two. |
| `splat_points/` | Splat → colored point cloud. Light, but looks pixelated: each splat becomes an opaque square. |
| `splat_gaussians/` | Splat → pruned splat (300k) + Unity transform, rendered as real Gaussians. Realistic. |
| `shots/` | Pulls a shot rendered on the headset and makes an MP4. |

## Depth (one photo)

```bash
.venv/bin/python -m depth.prepare_photo ../data/room/test-room0.JPG --out outputs/test-room0
.venv/bin/python -m depth.depth_standin outputs/test-room0      # -> outputs/test-room0/scene_unity.ply
```

## Gaussian splat (videos)

The room videos (`vid0-2.MOV`) are not in git; get them from Rayane into `../data/room/`.
Film the room slowly, turning in place and walking a little, so every direction is seen
(a direction nobody filmed stays empty in VR).

```bash
.venv/bin/python -m splat_train.video_to_frames ../data/room/vid0.MOV ../data/room/vid1.MOV ../data/room/vid2.MOV \
    --out outputs/room_splat/images                              # ~200 sharp frames
splat_train/run_colmap.sh outputs/room_splat                     # camera poses, ~10 min on CPU
splat_train/train_brush.sh outputs/room_splat                    # splat, ~25 min (Brush, see script)

# Option A, points (pixelated):
.venv/bin/python -m splat_points.splat_to_points outputs/room_splat/splat_15000.ply \
    --colmap outputs/room_splat/sparse/0 --out outputs/room_splat/scene_unity.ply

# Option B, real Gaussians (recommended):
.venv/bin/python -m splat_gaussians.splat_for_unity outputs/room_splat/splat_15000.ply \
    --colmap outputs/room_splat/sparse/0 --out outputs/room_splat/unity/room-splat.ply
```

Then follow `unity/README.md` to bring the result into the headset.

## Shots from the headset

After *Generate* in VR, plug the headset in and run (from `server/`):

```bash
shots/pull_shot.sh        # latest shot -> outputs/shots/<date>/<date>.mp4 (+ frames, trajectory.json)
```

Tests: `.venv/bin/python -m common.test_pointcloud`
