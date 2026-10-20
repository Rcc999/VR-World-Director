#!/bin/bash
# Python environment for the Puffin-World generation server. Shared by the
# Dockerfile (cloud) and puffin.def (Apptainer on Euler) so both stay identical.
# Expects requirements-euler.txt in the working directory.
#
# Stack: Python 3.10, PyTorch 2.7.0 + CUDA 12.8. Upstream pins cu126; cu128 is
# the same torch release with Blackwell (RTX Pro 6000, sm_120) support and
# still runs on Ampere/Ada (A100, 3090, 4090).
set -euo pipefail

VENV=${VENV:-/opt/venv}
FLASH_ATTN_FROM_SOURCE=${FLASH_ATTN_FROM_SOURCE:-0}
export UV_LINK_MODE=copy UV_PYTHON_INSTALL_DIR=/opt/python

curl -LsSf https://astral.sh/uv/0.13.4/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
uv venv --python 3.10 "$VENV"
export VIRTUAL_ENV="$VENV" PATH="$VENV/bin:$PATH"

uv pip install torch==2.7.0 torchvision==0.22.0 torchaudio==2.7.0 \
    --index-url https://download.pytorch.org/whl/cu128
uv pip install -r requirements-euler.txt

if [ "$FLASH_ATTN_FROM_SOURCE" = 1 ]; then
    # Slow (~1 h). Only needed if the prebuilt wheel lacks kernels for the GPU.
    TORCH_CUDA_ARCH_LIST="8.0;8.6;8.9;12.0" MAX_JOBS=${MAX_JOBS:-8} \
        uv pip install flash-attn==2.8.3 --no-build-isolation
else
    uv pip install "https://github.com/Dao-AILab/flash-attention/releases/download/v2.8.3/flash_attn-2.8.3+cu12torch2.7cxx11abiTRUE-cp310-cp310-linux_x86_64.whl"
fi

uv cache clean
python -c "import torch, transformers, deepspeed, xtuner, flash_attn, trimesh; print('env ok', torch.__version__, torch.version.cuda)"
