# World states for the VR menu

Puffin-World describes a world with three states: **appearance** (RGB),
**geometry** (depth) and **physics** (gravity field and latitude, the
"perspective field"). This is what the server exports so Unity can toggle
them. All files sit in the scene folder (`outputs/scenes/<scene>/`).

## Where each state comes from

| State | Source |
|---|---|
| Appearance | Puffin's generated frames (real photos / video frames for real views) |
| Geometry | Puffin's generated depth, scaled to meters (to VGGT's depth for multi-photo scenes) |
| Physics, conditioned | Puffin's own estimate of the seed's roll / pitch, propagated along the camera path with Puffin's code: what each generated view was told to respect |
| Physics, measured | Puffin's perception branch run on the frame itself (`--measure`) |
| Physics, scene | the camera in the final leveled scene (floor fit, or VGGT); the reference |
| Caption | Puffin's perception branch |

Puffin does not predict physics for generated views; it conditions on it.
`measured` vs `conditioned` is how well it respected it (the proposal's
camera-control accuracy, evaluation (ii)).

## Point clouds (toggle real / generated)

`world_state/clouds/`, listed in `world_state.json` under `clouds` (role ->
file, point count, voxel size). Only these ship; the scene folder's raw,
full-density clouds are not part of the package.

| Role | Content |
|---|---|
| `full.ply` | real + generated |
| `real.ply` | the photo(s) / video frames only (for one-seed scenes: the seed view) |
| `generated.ply` | Puffin's generated content only (absent for video-only scenes) |

All are merged into 2 cm cells (headset-sized) and share one frame: Unity
axes, meters, floor at y = 0, first camera at (0, camera height, 0) looking
down +z. One-seed scenes are leveled with Puffin's gravity (the up the
images were generated with) and the floor is the ground around the camera;
`floor_vs_gravity_deg` in `scene.json` is a whole-scene RANSAC floor kept
only as a diagnostic (sloped terrain makes it unreliable).

Height / depth coloring needs no extra data: a shader mode on `position.y`
(height above floor) or distance to the viewer.

## `world_state/world_state.json`

```jsonc
{
  "kind": "single" | "multiseed" | "real",
  "gravity_unity": [0, -1, 0],            // scene is leveled: gravity is straight down
  "caption": "...",                        // Puffin's description of the scene
  "clouds": {"full": {"file": "clouds/full.ply", "points": 812345, "voxel_m": 0.02}, "real": {...}, "generated": {...}},
  "runs": {
    "<run>": {                             // e.g. "left", "right", "walk", "IMG_7017-left", "real"
      "generated": true,
      "frames": 22, "fps": 8, "vfov": 51.6,
      "seed": {"roll": 0.6, "pitch": -9.7},             // Puffin's estimate for the seed photo
      "files": {"rgb": "<run>-rgb.mp4", "depth": "<run>-depth.mp4",
                "pf_up": "<run>-pf_up.mp4", "pf_lat": "<run>-pf_lat.mp4"},
      "views": [{
        "index": 0,
        "c2w_unity": [[...4x4...]],                     // camera right/up/forward/position columns
        "scene":       {"roll": 0.1, "pitch": -9.8},    // degrees
        "conditioned": {"roll": 0.6, "pitch": -9.7},    // generated views only
        "measured":    {"roll": 1.2, "pitch": -8.9, "vfov": 53.0}   // every 7th view, with --measure
      }]
    }
  },
  "physics_check": {                       // null until --measure
    "generated": {"against": "conditioned ...", "views": 12,
                  "roll_err_deg_median": 1.1, "pitch_err_deg_median": 2.0, ...},
    "real": {...}                          // Puffin's perception vs. the real (VGGT) cameras
  }
}
```

Angles are degrees; Puffin's convention: pitch < 0 = looking down, roll > 0
= clockwise. Frame `index` i of a run is frame i of all its videos.

## Videos per run

| File | Content |
|---|---|
| `<run>-rgb.mp4` | the generated (or real) frames |
| `<run>-depth.mp4` | depth, turbo colors, one range per run (red = near, blue = far) |
| `<run>-pf_up.mp4` | Puffin's up-vector field drawn over the frame |
| `<run>-pf_lat.mp4` | Puffin's latitude field (angle above / below the horizon) over the frame |

## Suggested menu toggles

| Toggle | Data |
|---|---|
| Show / hide generated content | load `generated.ply` as its own object |
| Color by height / depth | shader mode, no data |
| Gravity arrow + horizon plane at eye height | `gravity_unity` |
| Viewfinder level (roll / pitch of the virtual camera) | computed live from the camera's transform |
| Replay with depth / perspective-field overlay | swap the replay screen's video between `rgb`, `depth`, `pf_up`, `pf_lat` |
| Physics check badge | `physics_check` and per-view `measured` vs `conditioned` |
| Scene caption panel | `caption` |

## Live generation (WebSocket server, streaming.py)

Every streamed chunk carries `frames`, `depths` (path scale), `poses`
(OpenCV c2w), and `physics`: per new view `{roll, pitch, vfov, k1}` in
radians, the exact perspective-field parameters Puffin was conditioned on.

## Regenerating

```bash
python -m generation.world_state outputs/scenes/<scene>                 # CPU: json + videos
sbatch -J ws --time=1:00:00 generation/slurm/run.sbatch \
    generation.world_state outputs/scenes/<scene> --measure               # GPU: + measured physics
```
