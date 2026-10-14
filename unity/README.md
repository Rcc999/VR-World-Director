# unity

`vr-director/` is the Unity 6 (6000.3.25f1) VR project: URP, OpenXR, MRTK3 and Android XR,
built for Meta Quest. Open that folder in Unity Hub.

- MRTK3 packages are vendored as tarballs in `vr-director/Packages/MixedReality/` and referenced
  from `Packages/manifest.json`, so no extra download is needed.
- Binary assets (images, models, `.ply` point clouds, audio) go through Git LFS
  (`vr-director/.gitattributes`). Run `git lfs install` once per machine.
- The first open rebuilds `Library/`, which takes a few minutes.
