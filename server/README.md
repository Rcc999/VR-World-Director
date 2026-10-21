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
| `puffin_fusion/` | Puffin-World runs → denser point clouds (`dense_fuse.py`), and a 3DGS training set from them (`to_3dgs_dataset.py`, experiment). |
| `world_state/` | Copies a Puffin world state export into Unity (`Assets/WorldStates/`), videos re-encoded to H.264. |

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
shots/pull_shot.sh            # latest shot -> outputs/shots/<scene>/<name>/<name>.mp4 (+ frames, shot.json)
shots/pull_shot.sh shot3      # latest shot with that name (as in the headset's Shots panel)
SCENE=Puffin-Indoor shots/pull_shot.sh shot3   # shot3 of that world (names repeat across worlds)
shots/pull_shot.sh --list     # shots on the headset, with their world
```

Tests: `.venv/bin/python -m common.test_pointcloud`

### Puffin points → Gaussians (no training)

Each point becomes a round Gaussian as wide as the gap to its neighbors, so the Puffin worlds
look smooth instead of made of squares (~500k Gaussians each):

```bash
for s in indoor:Indoor text:Plaza outdoor:Ruin; do
  .venv/bin/python -m splat_gaussians.points_to_gaussians ../data/vrwd_scenes/front/puffin-${s%%:*}-front.ply \
    --out outputs/puffin_splats/${s##*:}.ply
done
```
Options: `--size` (bigger = smoother, blurrier; default 0.6), `--max_splats`, `--min_y -0.3`
(cut noise under the floor). Then into Unity: see *Puffin worlds as Gaussians* in `unity/README.md`.

## Puffin-World worlds (denser)

Puffin-World runs on Euler (code: `server/generation/` on the `generation-server` branch). Its
upstream fusion averages each world into a 512³ voxel grid, keeps at most 1M points per run
and skips views, which makes the worlds look pixelated. We turn that off (`voxel_res 0`, 3M
points per run, every view): the views are only 640×640, so every pixel counts.

**New run on Euler** (left + right turns of 105° and a walk, fused dense, 9M points). On the
`generation-server` clone, apply `puffin_fusion/scenes_dense.patch` (`patch -p1`), then from `server/`:

```bash
sbatch -J scene-plaza generation/slurm/scene.sbatch text --prompt "..." \
    --voxel_res 0 --max_points 3000000 --max_stride 1 --ply_name scene_unity_dense.ply
```
→ `outputs/scenes/<name>/scene_unity_dense.ply` (+ `raw.npz`, videos). Copy it to
`Assets/PointClouds/Puffin/<Name>Wide.ply` and run *Build Puffin World Scenes* (`unity/README.md`).

**Runs with parallax** (for walking around and for 3DGS): the patch also adds camera runs that move,
not only turn. `--runs left right strafe_l strafe_r orbit_l orbit_r walk`: `strafe_*` slides
sideways (0.03 × scene depth per view), `orbit_*` circles the point the seed view looks at
(2°/view). Each run starts from the seed view. About 120 views → ~3 h on an A100 (one job per
world, they run in parallel).

**Re-fuse an existing run on the Mac** (CPU, minutes, needs `raw.npz` + `meta.json`):

```bash
.venv/bin/python -m puffin_fusion.dense_fuse ../data/vrwd_scenes/raw/indoor --keep_views pan=22 \
    --out ../data/vrwd_scenes/dense/Indoor.ply
```
`--keep_views RUN=N` keeps only the first N views of a run (e.g. before a long pan drifts).

**First 3DGS experiment (superseded by the depth-guided training below):** `to_3dgs_dataset.py` writes a
COLMAP dataset from Puffin's own cameras (optionally 4× Real-ESRGAN, weights in
`tools/upscale/RealESRGAN_x4plus.pth`), then `splat_train/train_brush.sh`. Result: streaks.
The views mostly turn in place, so there is no parallax and the Gaussians become thin needles.
Dense points or `points_to_gaussians.py` (above) look better.

**Textured depth meshes (best look so far):** every pixel of a Puffin view is pushed out to its
depth and neighbors are joined into triangles, textured with the view's image. Per world:
- ~13 views (every 20° of the turns, middle 80 % of each, so neighbors overlap and hide seams);
- cut where the depth jumps > 15 %, with a backdrop patch behind each cut (background color
  instead of black when you look behind an edge); sky on a shell at 150 m;
- a 360° dome at 170 m painted from all views, gaps filled with blurred sky / ground colors;
- same scale and frame as the dense cloud (they overlap within ~2 cm). ~1.8M triangles, seconds
  on the Mac (`--upscale`: 4× Real-ESRGAN textures).

```bash
.venv/bin/python -m puffin_fusion.depth_mesh ../data/vrwd_scenes/v2/text ../data/vrwd_scenes/v2/text/scene_dense.json \
    --out ../unity/vr-director/Assets/Meshes/Puffin/PlazaMesh
```
Then Unity: *VR Director → Build Puffin Mesh Worlds*.

**Depth-guided 3DGS (Euler, in progress):** `puffin_fusion/train_3dgs.py` trains a splat with
gsplat on every view of a parallax run, starting from the dense points (+ a sky shell), with
an image loss, a loss against Puffin's depth (keeps the Gaussians on surfaces) and a penalty on
needle-shaped Gaussians. Output in the W frame (Unity with y flipped) + `.transform.json`
(scale (1, -1, 1)), then into Unity like the room (*Create GaussianSplatAsset*).

```bash
# once: gsplat into scratch (its CUDA code compiles on the first run)
apptainer exec --bind $SCRATCH --env UV_CACHE_DIR=$SCRATCH/.uvcache $SCRATCH/vrwd-puffin.sif \
    $SCRATCH/bin/uv pip install --python /opt/venv/bin/python --target $SCRATCH/gsplat_lib --no-deps \
    gsplat==1.5.3 jaxtyping wadler-lindig
# per world (from server/, after its scene job)
sbatch -J 3dgs-plaza puffin_fusion/train_3dgs.sbatch outputs/scenes/plaza3d --out outputs/splats/Plaza3D.ply
```
