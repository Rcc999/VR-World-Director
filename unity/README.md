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

**Point cloud:** copy the `.ply` into `Assets/PointClouds/...`, select it, run *Build Point Cloud Viewer Scene*.

**Gaussian splat:**
1. *Tools → Gaussian Splats → Create GaussianSplatAsset*: input the `.ply` from `splat_for_unity`,
   output `Assets/GaussianAssets`, quality Low.
2. Copy the matching `.transform.json` into `Assets/GaussianAssets/` (it places the splat).
3. Select the new asset, run *Build Gaussian Splat Viewer Scene*, then *Build and Run*.

## Controls in the headset (hands, no controllers)

| Action | Gesture |
|---|---|
| Move | Pinch in empty space and pull |
| Turn | Pinch with both hands and rotate them |
| Teleport | Point at the floor, hold a still pinch until the ring appears, release |
| Menu | Turn your left palm toward you; poke buttons with your right index |
| New camera | Menu → *New camera*: it sits in your right hand with a live preview; aim, then pinch to place |
| Edit a camera | Pinch it, move or rotate your hand (it never rolls, so the horizon stays level) |
| Undo / Clear all / Reset position | Menu buttons |
| Save | Menu → *Save*: cameras go to `camera_path.json` on the headset and load back at start |
| Speed | Menu → *Speed*: Slow / Medium / Fast = 0.25 / 0.5 / 1 m/s along the path |
| Generate | Menu → *Generate*: renders the shot along the path (1280×720, 30 fps PNGs + `trajectory.json`). Meanwhile you wait in an empty black space with only the progress screen, and nothing can be touched. Then the room comes back and the shot replays on a screen; press again to close |

The video shows only the room: the room is on the **Scene** layer, and the shot and preview cameras render only that layer (no hands, menu, screen, camera models or path).

Cameras are numbered in placement order and joined by the path line.
Code: `Runtime/VRLocomotion.cs`, `HandInput.cs`, `CameraPathTool.cs`, `PathCamera.cs`, `ShotRenderer.cs`, `PathMenu.cs`.
To get a shot onto the Mac as MP4: `server/shots/pull_shot.sh` (see `server/README.md`).

The splat package is embedded in `vr-director/Packages/org.nesnausk.gaussian-splatting/` with two
patches (marked `VR Director patch`): extra cameras get correct splat sizes on the headset, and splats
respect a camera's culling mask (so the headset can hide them while the shot camera renders them).
