# Puffin-World generation server, cloud image (Brev / AWS).
# Build from server/generation/:  docker build -f container/Dockerfile -t vrwd-puffin .
# Run (repo + weights mounted, not baked in):
#   docker run --gpus all -p 8765:8765 -v $PWD/../..:/workspace \
#     -v /data/puffin_base:/weights/base -v /data/puffin_ckpt:/weights/ckpt vrwd-puffin
FROM nvidia/cuda:12.8.1-cudnn-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates git ffmpeg libgl1 libglib2.0-0 libegl1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-euler.txt container/install.sh /opt/env/
RUN cd /opt/env && ./install.sh && rm -rf /opt/env

ENV PATH=/opt/venv/bin:$PATH \
    PUFFIN_BASE_DIR=/weights/base \
    PUFFIN_CKPT_DIR=/weights/ckpt \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
WORKDIR /workspace/server
