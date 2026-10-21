#!/bin/bash
# Train a depth-guided 3DGS on a Puffin scene, on Euler (from server/):
#   sbatch -J 3dgs-plaza puffin_fusion/train_3dgs.sbatch outputs/scenes/plaza3d --out outputs/splats/Plaza3D.ply
# gsplat is installed in $SCRATCH/gsplat_lib (uv pip install --target, see server/README.md);
# its CUDA code compiles on the first run (~5 min) into $SCRATCH/torch_ext.
#SBATCH -A ls_polle
#SBATCH --gpus=1
#SBATCH --cpus-per-task=8
#SBATCH --mem-per-cpu=8G
#SBATCH --time=2:00:00
#SBATCH --output=outputs/slurm/%x-%j.out
set -euo pipefail
REPO=$(cd .. && pwd)
nvidia-smi --query-gpu=name,memory.total --format=csv
apptainer exec --nv \
    --bind "$REPO:/workspace" --bind "$SCRATCH" \
    --env PYTHONPATH=$SCRATCH/gsplat_lib,TORCH_EXTENSIONS_DIR=$SCRATCH/torch_ext,MAX_JOBS=8 \
    --pwd /workspace/server \
    "$SCRATCH/vrwd-puffin.sif" \
    python -m puffin_fusion.train_3dgs "$@"
