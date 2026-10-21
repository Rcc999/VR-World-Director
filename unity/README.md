# unity

`vr-director/` is the Unity 6 (6000.3.25f1) VR project: URP, OpenXR, MRTK3, Android XR,
built for the **Samsung Galaxy XR** (standalone Android build). Open that folder in Unity Hub.

- MRTK3 packages are vendored as tarballs in `vr-director/Packages/MixedReality/`.
- Gaussian splats are rendered with a fork of aras-p's Unity Gaussian Splatting that adds Quest 3
  stereo support (`arghyasur1991/UnityGaussianSplatting` at da5b057, embedded and patched, see below).
- Binary assets (`.ply`, splat `.bytes`, images, video) go through Git LFS. Run `git lfs install` once.
- The first open rebuilds `Library/`, which takes a few minutes. Put APKs in `vr-director/Builds/` (git-ignored).

## Our code: `Assets/VRDirector/`

| File | Role |
|---|---|
| `Editor/PlyImporter.cs` | Imports a `.ply` point cloud as a mesh (one square per point, optional per-point size). |
| `Shaders/PointCloud.shader` | Draws those squares facing the viewer, in stereo. |
| `Editor/PointCloudSceneBuilder.cs` | Menu **VR Director → Build Point Cloud Viewer Scene**. |
| `Editor/PointCloudSceneBuilder.cs` → *Build Puffin World Scenes* | One scene per `.ply` in `PointClouds/Puffin/`; build = all worlds. |
| `Editor/SplatSceneBuilder.cs` | Menu **VR Director → Build Gaussian Splat Viewer Scene**; also sets Vulkan-only and URP settings the splat renderer needs. |
| `Runtime/VRLocomotion.cs` | Moving around (added to the XR rig by both menus). |

Both menus copy `HelloCube.unity` (the working XR rig), put the scene at the origin, switch to
full VR (no passthrough, black background) and make the new scene the only one in the build.

## Scenes in `Assets/`

| Asset | From | Scene |
|---|---|---|
| `PointClouds/Depth/` | `server/depth` | `Scenes/PointCloudViewer.unity` |
| `PointClouds/SplatPoints/` | `server/splat_points` | `Scenes/PointCloudViewer.unity` |
| `GaussianAssets/` | `server/splat_gaussians` | `Scenes/SplatViewer.unity` |
| `PointClouds/Puffin/` (`Indoor`, `Plaza`, `Ruin` `.ply` + `.json`) | Puffin-World on Euler (`data/vrwd_scenes/front/`) | `Scenes/Puffin/Puffin-<Name>.unity` |
| `PointClouds/Puffin/` (`IndoorWide`, `PlazaWide`, `RuinWide`) | New dense runs, ±105° + walk, 9M points each (`data/vrwd_scenes/v2/`) | `Scenes/Puffin/Puffin-<Name>Wide.unity` |
| `GaussianAssets/Puffin/` | `Indoor`, `Ruin`: points → Gaussians; `Plaza`: trained 3DGS test (streaky) | replaces the point version of `Puffin-<Name>` |

**Point cloud:** copy the `.ply` into `Assets/PointClouds/...`, select it, run *Build Point Cloud Viewer Scene*.

**Gaussian splat:**
1. *Tools → Gaussian Splats → Create GaussianSplatAsset*: input the `.ply` from `splat_for_unity`,
   output `Assets/GaussianAssets`, quality Low.
2. Copy the matching `.transform.json` into `Assets/GaussianAssets/` (it places the splat).
3. Select the new asset, run *Build Gaussian Splat Viewer Scene*, then *Build and Run*.

**Puffin worlds:** the `.ply` files are already in Unity coordinates (meters, floor at y = 0, seed
camera at (0, 1.5, 0) looking down +z), so no conversion is needed.
1. Put them in `Assets/PointClouds/Puffin/` (`<Name>.ply`; the 3 from `data/vrwd_scenes/front/` are there).
2. Run *VR Director → Build Puffin World Scenes*: one scene per cloud in `Scenes/Puffin/`.
3. Rebuild the room too (*Build Gaussian Splat Viewer Scene*, above) so it gets the Worlds button.

**Puffin worlds as Gaussians (smoother, no squares):** turn each cloud into round Gaussians with
`server/splat_gaussians/points_to_gaussians.py` (see `server/README.md`), then run
*VR Director → Build Puffin Splat Worlds*: every `server/outputs/puffin_splats/<Name>.ply` becomes a
splat asset (Low quality, like the room) in `Assets/GaussianAssets/Puffin/` and replaces the point
version of `Scenes/Puffin/Puffin-<Name>.unity` (same scene name, so its cameras and shots stay).
*Build Puffin World Scenes* puts the points back.

Both menus set the build to **all worlds**: the 3DGS room first (opens at start), then the Puffin
scenes. Switch between them in the headset with *Worlds*. If a world stutters, select its `.ply`
and set *Max Points* (e.g. 500000) on the importer. The *Wide* worlds use all 9M points (≈1 GB of
mesh, fine in the editor); set *Max Points* (e.g. 2000000) on them before a headset build.

## Controls in the headset (hands, no controllers)

| Action | Gesture |
|---|---|
| Move | Pinch in empty space and pull |
| Turn | Pinch with both hands and rotate them |
| Menu | Turn your left palm toward you; poke buttons with your right index (two columns: cameras left, shots right) |
| New camera | Menu → *New camera*: it sits in your right hand with a live preview; aim, then pinch to place |
| Edit a camera | Pinch it, move or rotate your hand (it never rolls, so the horizon stays level) |
| Undo / Clear all / Reset position | Menu buttons |
| Save | Menu → *Save*: cameras go to `camera_path_<scene>.json` on the headset (one per world) and load back at start |
| Speed | Menu → *Speed*: Slow / Medium / Fast = 0.25 / 0.5 / 1 m/s along the path |
| Generate | Menu → *Generate*: renders a new shot along the path (1280×720, 30 fps PNGs + `shot.json`). Meanwhile you wait in an empty black space with only the progress screen, and nothing can be touched. Then you are back at the start position with your cameras; watch it from *Shots* |
| Shots | Menu → panel with this scene's shots, one at a time (*< Prev / Next >*):<br>• *Watch*: the video (its saved frames) on a screen<br>• *Ride*: your head follows the shot's path (position and turns; up/down stays yours), seeing only the room; you end at the start<br>• *Edit*: back to the start with that shot's cameras; *Generate* then makes a **new** shot, the old one is kept<br>• *Rename*: touch keyboard · *Delete*: press twice<br>While a shot plays, the menu button reads *Stop video* / *Stop ride* |
| Help | Menu → panel listing all gestures and buttons; it also opens when the app starts |
| Worlds | Menu → scene picker (up to 8): Room 3DGS and the Puffin worlds (Indoor, Plaza, Ruin, and their *Wide* versions). Each world keeps its own cameras and shots |

Shots are numbered like takes: **shot1, shot2…** per scene (a deleted number is never reused); the
default name is `shot<N>`. On the headset: `Shots/<scene>/<date>/` with `frame_*.png` + `shot.json`
(name, keyframes, every frame's pose).

The video shows only the room: the room is on the **Scene** layer, and the shot and preview cameras render only that layer (no hands, menu, screen, camera models or path).

Cameras are numbered in placement order and joined by the path line.
Code: `Runtime/VRLocomotion.cs`, `HandInput.cs`, `CameraPathTool.cs`, `PathCamera.cs`, `ShotRenderer.cs`, `ShotLibrary.cs`, `ShotsPanel.cs`, `PathMenu.cs`, `HelpPanel.cs`, `WorldsPanel.cs`.
To get a shot onto the Mac as MP4: `server/shots/pull_shot.sh` (see `server/README.md`).

The splat package is embedded in `vr-director/Packages/org.nesnausk.gaussian-splatting/` with two
patches (marked `VR Director patch`): extra cameras get correct splat sizes on the headset, and splats
respect a camera's culling mask (so the headset can hide them while the shot camera renders them).

## How the shot camera moves between the cameras (path math)

Code: `CameraPathTool.CatmullRom`, `ShotRenderer.SampleFrames` / `ArcLengthToU`, `PathCamera.Level`.

The cameras you place are **keyframes** $K_0 \dots K_{N-1}$, each a position $p_i$ and a rotation
(quaternion) $q_i$. *Generate* turns them into one pose per video frame (30 fps) in four steps.

### 1. Position: a Catmull-Rom curve through every camera

Between camera $i$ and $i+1$ the position is a cubic in $u \in [0,1]$ that also looks at the
neighbours $p_{i-1}$ and $p_{i+2}$ (at the two ends the missing neighbour is the end camera itself):

$$
P(u) = \tfrac12\Big[\,2p_i + (p_{i+1}-p_{i-1})\,u + (2p_{i-1}-5p_i+4p_{i+1}-p_{i+2})\,u^2 + (-p_{i-1}+3p_i-3p_{i+1}+p_{i+2})\,u^3\Big]
$$

Why it is smooth:
- $P(0)=p_i$ and $P(1)=p_{i+1}$: the curve **goes exactly through every camera** (unlike a
  Bézier or B-spline, which only pass near their control points).
- The tangent at camera $i$ is $P'(0) = \tfrac12(p_{i+1}-p_{i-1})$, and the segment before it ends
  with the **same** tangent. So the direction of motion never jumps at a camera: no corners
  (the curve is $C^1$). It is also local: moving one camera only changes the 4 segments around it.

The white path line in the headset is this same curve, drawn with 20 points per segment.

### 2. Constant speed: re-parameterise by arc length

Equal steps in $u$ are **not** equal distances (the curve is faster in the middle of a long
segment and slower near tight bends), so stepping $u$ directly would make the camera speed up
and slow down. Instead, per segment:

1. Sample the curve at 64 values of $u$ and add up the distances → cumulative length
   $c_0=0 \le c_1 \le \dots \le c_{64} = L$ (the segment length).
2. For a wanted distance $d$ along the segment, find $c_{j-1} \le d \le c_j$ and interpolate:
   $u = \big(j-1 + \frac{d-c_{j-1}}{c_j-c_{j-1}}\big)/64$.

Now equal steps in $d$ mean equal distances: the camera moves at **constant speed** inside a segment.

### 3. Timing: how many frames per segment

$$
T = \max\!\Big(\frac{L}{v},\; \frac{\theta}{\omega},\; 0.5\,\text{s}\Big), \qquad n = \operatorname{round}(30\,T)
$$

- $v$ = Speed button: 0.25 / 0.5 / 1 m/s.
- $\theta$ = angle between $q_i$ and $q_{i+1}$; $\omega = 90°/\text{s} \times v$ (22 / 45 / 90 °/s), so a
  camera that mostly **turns** in place still gets enough time and never whips around.
- 0.5 s minimum so two almost identical cameras still give a visible segment.

Frame $k$ of the segment ($k = 0 \dots n-1$) is at distance $d = L\,k/n$ → $u$ from step 2 →
position $P(u)$. Example: 2 m between two cameras at Medium → 4 s → 120 frames, one every 1.7 cm.
The very last frame is exactly the last camera.

### 4. Rotation: SLERP, then remove roll

Rotations are blended with **spherical linear interpolation** at the same $u$:

$$
\operatorname{slerp}(q_i, q_{i+1}; u) = \frac{\sin\big((1-u)\Omega\big)}{\sin\Omega}\,q_i + \frac{\sin(u\Omega)}{\sin\Omega}\,q_{i+1},
\qquad \cos\Omega = q_i \cdot q_{i+1}
$$

It turns along the shortest arc between the two orientations at a steady rate, the rotation
equivalent of a straight line. (Blending the angles or matrices directly would wobble or shrink.)

Then `Level` keeps only where the camera looks (its forward vector $f$) and rebuilds the rotation
with world up: `LookRotation(f, up)`. That sets **roll to 0**, so the horizon is always level, the
way a camera on a tripod or gimbal behaves. (Only if you look straight up or down is it left as is.)

### What is (and is not) smooth

| | At a camera | Inside a segment |
|---|---|---|
| Position | passes through it, no corner ($C^1$) | constant speed |
| Speed | can change if the two segments get different durations | constant |
| Rotation | passes through it exactly; the turning rate can change (SLERP is per segment) | steady turn, no roll |

Possible upgrades: SQUAD (a spline for quaternions) to make the turning rate continuous too, and
easing in/out at the first and last camera.

### Ride and Watch

`shot.json` stores every frame's pose. *Ride* plays them back at 30 fps and, between two frames,
blends with `Lerp` (position) and `Slerp` (rotation) at the headset's own frame rate; only the
left/right part of the rotation is applied to you, up/down stays with your head for comfort.
*Watch* just plays the saved PNGs.
