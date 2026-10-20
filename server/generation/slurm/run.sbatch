#!/bin/bash
# Run any generation module in the container on Euler, weights staged on
# node-local disk (from server/):
#   sbatch -J check-stream --time=0:30:00 generation/slurm/run.sbatch \
#       generation.check_stream --image /seeds/test-room0.JPG
#SBATCH -A ls_polle
#SBATCH --gpus=nvidia_rtx_pro_6000:1
#SBATCH --cpus-per-task=8
#SBATCH --mem-per-cpu=16G
#SBATCH --tmp=100G
#SBATCH --time=1:00:00
#SBATCH --output=outputs/slurm/%x-%j.out
set -euo pipefail
REPO=$(cd .. && pwd)
MODULE=$1; shift

# One sequential copy (~80 s) instead of Python reading scratch (~26 min).
WEIGHTS=$TMPDIR/weights
mkdir -p "$WEIGHTS/ckpt"
cp -r "$SCRATCH/puffin_base" "$WEIGHTS/base"
cp "$SCRATCH"/puffin_ckpt/Puffin-World-*.pth "$WEIGHTS/ckpt/"

nvidia-smi --query-gpu=name,memory.total --format=csv
apptainer exec --nv \
    --bind "$REPO:/workspace" \
    --bind "$WEIGHTS/base:/weights/base" \
    --bind "$WEIGHTS/ckpt:/weights/ckpt" \
    --bind "$SCRATCH/seeds:/seeds" \
    --env PUFFIN_BASE_DIR=/weights/base,PUFFIN_CKPT_DIR=/weights/ckpt \
    --pwd /workspace/server \
    "$SCRATCH/vrwd-puffin.sif" \
    python -m "$MODULE" "$@"
