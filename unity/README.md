# unity

`vr-director/` is the Unity 6 (6000.3.25f1) VR project: URP, OpenXR, MRTK3, Android XR,
built for the **Samsung Galaxy XR** (standalone Android build). Open that folder in Unity Hub.

- MRTK3 packages are vendored as tarballs in `vr-director/Packages/MixedReality/`.
- Gaussian splats are rendered with a fork of aras-p's Unity Gaussian Splatting that adds Quest 3
  stereo support (`arghyasur1991/UnityGaussianSplatting`, pinned in `Packages/manifest.json`).
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

- Hold a **left pinch**: move forward where you look. **Right pinch**: move backward.
- Hold **both pinches** ~1.5 s: back to the start. Turn with your body.
- Pinch with the palm facing away: palm toward you opens the system menu.
- Controllers also work if present: left stick moves, right stick turns, B/Y resets.
