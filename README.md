# VR World Director

Camera-path authoring inside a world model, in VR. See `docs/` for the project proposal.

## Layout

| Path | Contents |
|---|---|
| `third_party/Puffin/` | Puffin-World upstream (git submodule, pinned). Only `Puffin-World/` is used. |
| `server/` | Python side: photo → Puffin-World → point cloud, and later the generation server. Runs on a CUDA GPU. |
| `unity/` | Unity 6 VR project (Meta Quest, OpenXR). |
| `docs/` | Proposal and notes. |

## Setup

```bash
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
