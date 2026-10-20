#!/bin/bash
# One-shot setup + WP0 benchmark on a cloud GPU box (Brev / AWS) with Docker
# and the NVIDIA container toolkit. Run from the repo root:
#   HF_TOKEN=hf_... server/generation/container/cloud_setup.sh [pro|base|all]
# Needs ~100 GB free for `pro` (weights ~60 GB + image ~15 GB), ~170 GB for `all`.
# HF_TOKEN must belong to an account that accepted the SD3.5 license.
set -euo pipefail
WHICH=${1:-pro}
DATA=${DATA:-$HOME/puffin-data}
REPO=$(git rev-parse --show-toplevel)
: "${HF_TOKEN:?set HF_TOKEN}"
export HF_TOKEN

git -C "$REPO" submodule update --init
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/0.13.4/install.sh | sh
export PATH=$HOME/.local/bin:$PATH
hf() { uvx --from "huggingface_hub[hf_xet]" hf "$@"; }

# ---- weights (only what the chosen model needs) ----
mkdir -p "$DATA/base" "$DATA/ckpt" "$DATA/seeds"
get_pro()  { hf download ACERobotics/Puffin-World --include Puffin-World-Pro.pth --local-dir "$DATA/ckpt"
             hf download Qwen/Qwen2.5-1.5B-Instruct --local-dir "$DATA/base/Qwen2.5-1.5B-Instruct"
             hf download nvidia/C-RADIOv4-H --local-dir "$DATA/base/C-RADIOv4-H"
             hf download stabilityai/stable-diffusion-3.5-large --include "transformer/*" --include "vae/*" \
                 --include model_index.json --local-dir "$DATA/base/stable-diffusion-3.5-large"; }
get_base() { hf download ACERobotics/Puffin-World --include Puffin-World-Base.pth --local-dir "$DATA/ckpt"
             hf download Qwen/Qwen2.5-7B-Instruct --local-dir "$DATA/base/Qwen2.5-7B-Instruct"
             hf download nvidia/C-RADIOv3-H --local-dir "$DATA/base/C-RADIOv3-H"
             hf download stabilityai/stable-diffusion-3.5-medium --include "transformer/*" --include "vae/*" \
                 --include model_index.json --local-dir "$DATA/base/stable-diffusion-3.5-medium"; }
case $WHICH in pro) get_pro ;; base) get_base ;; all) get_pro; get_base ;; esac &
DL=$!

# Seed photos are Git LFS in the repo; fetch the real files directly.
for i in 0 1 2 3; do
    curl -sfL -o "$DATA/seeds/test-room$i.JPG" \
        "https://media.githubusercontent.com/media/Rcc999/VR-World-Director/main/data/room/test-room$i.JPG"
done

# ---- image (builds while weights download) ----
docker build -f "$REPO/server/generation/container/Dockerfile" -t vrwd-puffin "$REPO/server/generation"
wait $DL

# ---- benchmark ----
run() {
    docker run --rm --gpus all --shm-size=16g \
        -v "$REPO:/workspace" -v "$DATA/base:/weights/base" \
        -v "$DATA/ckpt:/weights/ckpt" -v "$DATA/seeds:/seeds" \
        vrwd-puffin "$@"
}
run nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
run python -c "import torch, flash_attn; print(torch.cuda.get_device_name(), torch.cuda.get_device_capability(), 'flash_attn', flash_attn.__version__)"
mkdir -p "$REPO/server/outputs"
models=$([ "$WHICH" = all ] && echo "pro base" || echo "$WHICH")
for m in $models; do
    run python -m generation.bench --model "$m" --image /seeds/test-room0.JPG 2>&1 | tee "$REPO/server/outputs/bench_$m.log"
done
echo "Results: $REPO/server/outputs/bench/"
