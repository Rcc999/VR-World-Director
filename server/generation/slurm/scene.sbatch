#!/bin/bash
# One seed scene in the container on Euler (from server/):
#   sbatch -J scene-indoor generation/slurm/scene.sbatch indoor --image /seeds/test-room0.JPG
#   sbatch -J scene-text   generation/slurm/scene.sbatch text --prompt "..."
# Seeds in $SCRATCH/seeds are mounted at /seeds. Results: outputs/scenes/<name>/.
#SBATCH -A ls_polle
#SBATCH --gpus=nvidia_rtx_pro_6000:1
#SBATCH --cpus-per-task=8
#SBATCH --mem-per-cpu=16G
#SBATCH --tmp=100G
#SBATCH --time=3:00:00
#SBATCH --output=outputs/slurm/%x-%j.out
set -euo pipefail
REPO=$(cd .. && pwd)

# Python reads the checkpoints from scratch at ~40 MB/s (26 min). Stage them
# on the node's local disk with one sequential copy first.
WEIGHTS=$TMPDIR/weights
mkdir -p "$WEIGHTS"
t0=$(date +%s)
cp -r "$SCRATCH/puffin_base" "$WEIGHTS/base"
mkdir -p "$WEIGHTS/ckpt" && cp "$SCRATCH"/puffin_ckpt/Puffin-World-*.pth "$WEIGHTS/ckpt/"
echo "staged weights in $(( $(date +%s) - t0 )) s"

nvidia-smi --query-gpu=name,memory.total --format=csv
apptainer exec --nv \
    --bind "$REPO:/workspace" \
    --bind "$WEIGHTS/base:/weights/base" \
    --bind "$WEIGHTS/ckpt:/weights/ckpt" \
    --bind "$SCRATCH/seeds:/seeds" \
    --env PUFFIN_BASE_DIR=/weights/base,PUFFIN_CKPT_DIR=/weights/ckpt \
    --pwd /workspace/server \
    "$SCRATCH/vrwd-puffin.sif" \
    python -m generation.scenes "$@"
