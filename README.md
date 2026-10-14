# VR World Director

Camera-path authoring inside a world model, in VR. See `docs/` for the project proposal.

The final pipeline is one photo → Puffin-World → 3D scene → Unity → headset. Puffin-World needs
a large NVIDIA GPU that we do not have yet, so for now we test the rest of the pipeline
(3D scene → Unity → VR on the Samsung Galaxy XR) with scenes built from our own photos and videos.

## Status

| Approach | Input | Result in VR | Code |
|---|---|---|---|
| Depth | 1 photo | Works, but you only see the ~57° the photo covers | `server/depth/` |
| Splat as points | ~1 min of video | Full 360° room, but looks pixelated (opaque squares) | `server/splat_points/` |
| **Splat as Gaussians** | ~1 min of video | **Full 360° room, realistic** | `server/splat_gaussians/` |

The two splat approaches share capture → camera poses (COLMAP) → training (Brush):
`server/splat_train/`. In VR you can walk around with hand pinches (no controllers needed).

## Run it end to end (realistic splat, on a Mac)

1. **Install** (once): `git lfs install`, `brew install ffmpeg colmap`, Unity 6000.3.25f1 with
   Android Build Support, and the Python env from `server/README.md`. Download Brush v0.3.0
   for macOS into `server/tools/brush/` (link in `server/splat_train/train_brush.sh`).
2. **Build the scene** (from `server/`, about 40 min, mostly COLMAP and training): the
   *Gaussian splat (videos)* commands in `server/README.md`, ending with Option B.
3. **Into Unity**: open `unity/vr-director/` in Unity Hub, then the *Gaussian splat* steps in
   `unity/README.md` (create the asset, copy the `.transform.json`, run the VR Director menu).
4. **Onto the Galaxy XR**: enable developer mode and USB debugging on the headset, plug it in,
   allow the computer, then in Unity *File → Build Profiles → Android → Build and Run* (save the
   APK in `unity/vr-director/Builds/`). The app opens on the headset; see the hand controls in
   `unity/README.md`.

The room in `data/room/` is already processed into `unity/vr-director/Assets/`, so to just try
it in the headset you can skip steps 1–3 except installing Unity.

## Layout

| Path | Contents |
|---|---|
| `server/` | Python side: build 3D scenes and export them for Unity. See `server/README.md`. |
| `unity/vr-director/` | Unity 6 VR project for the Galaxy XR. See `unity/README.md`. |
| `data/room/` | Test captures: 4 photos of one room (Git LFS). The 3 videos are not in git (too large); ask Rayane, put them in `data/room/`. |
| `third_party/Puffin/` | Puffin-World upstream (git submodule, pinned). Only `Puffin-World/` is used. |
| `docs/` | Proposal and notes. |

## Setup

```bash
git lfs install
git clone --recurse-submodules git@github.com:Rcc999/VR-World-Director.git
# or, in an existing clone:
git submodule update --init
```

Puffin-World needs Linux + NVIDIA GPU (Python 3.10, PyTorch 2.7, CUDA 12.6, flash-attn).
Follow `third_party/Puffin/Puffin-World/README.md` for the environment, then download the
checkpoints into `third_party/Puffin/Puffin-World/checkpoints/`:

```bash
cd third_party/Puffin/Puffin-World
huggingface-cli download KangLiao/Puffin-World --local-dir checkpoints --repo-type model
```
