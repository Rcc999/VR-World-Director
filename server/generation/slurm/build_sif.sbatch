#!/bin/bash
# Build the Apptainer image on a CPU node: sbatch generation/slurm/build_sif.sbatch  (from server/)
#SBATCH -A ls_polle
#SBATCH --job-name=puffin-build-sif
#SBATCH --cpus-per-task=8
#SBATCH --mem-per-cpu=4G
#SBATCH --tmp=60G
#SBATCH --time=4:00:00
#SBATCH --output=outputs/slurm/%x-%j.out
set -euo pipefail
module load eth_proxy
export APPTAINER_TMPDIR=${TMPDIR:-$SCRATCH/apptainer_tmp} APPTAINER_CACHEDIR=$SCRATCH/.apptainer_cache
mkdir -p "$APPTAINER_TMPDIR" "$APPTAINER_CACHEDIR"
cd generation
apptainer build --fakeroot --force "$SCRATCH/vrwd-puffin.sif" container/puffin.def
ls -lh "$SCRATCH/vrwd-puffin.sif"
