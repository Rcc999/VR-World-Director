#!/bin/bash
# WP0 benchmark in the container on Euler: sbatch generation/slurm/bench.sbatch pro  (from server/)
# Default GPU is the RTX Pro 6000 (same as the planned cloud box). For an A100:
#   sbatch --gpus=nvidia_a100_80gb_pcie:1 generation/slurm/bench.sbatch pro
#SBATCH -A ls_polle
#SBATCH --job-name=puffin-bench
#SBATCH --gpus=nvidia_rtx_pro_6000:1
#SBATCH --cpus-per-task=8
#SBATCH --mem-per-cpu=16G
#SBATCH --time=1:00:00
#SBATCH --tmp=100G
#SBATCH --output=outputs/slurm/%x-%j.out

MODEL=${1:-pro}
REPO=$(cd .. && pwd)
# Stage weights on node-local disk: one sequential copy takes ~80 s, while
# Python reading them straight from scratch takes ~26 min.
WEIGHTS=$TMPDIR/weights
mkdir -p "$WEIGHTS/ckpt"
cp -r "$SCRATCH/puffin_base" "$WEIGHTS/base"
cp "$SCRATCH"/puffin_ckpt/Puffin-World-*.pth "$WEIGHTS/ckpt/"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
apptainer exec --nv \
    --bind "$REPO:/workspace" \
    --bind "$WEIGHTS/base:/weights/base" \
    --bind "$WEIGHTS/ckpt:/weights/ckpt" \
    --bind "$SCRATCH/seeds:/seeds" \
    --env PUFFIN_BASE_DIR=/weights/base,PUFFIN_CKPT_DIR=/weights/ckpt \
    --pwd /workspace/server \
    "$SCRATCH/vrwd-puffin.sif" \
    python -m generation.bench --model "$MODEL" --image /seeds/test-room0.JPG
