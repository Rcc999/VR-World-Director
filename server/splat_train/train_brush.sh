#!/usr/bin/env bash
# Train a Gaussian splat with Brush (Metal on a Mac, ~25 min for 15k steps).
#
#   splat_train/train_brush.sh outputs/room_splat    (from server/)
#
# Expects <scene>/images and <scene>/sparse/0 from run_colmap.sh. Writes
# <scene>/splat_{5000,10000,15000}.ply in COLMAP coordinates. --with-viewer
# opens a window that shows training live (the log stays empty otherwise).
#
# Brush v0.3.0 is not in git; download the macOS build from
# https://github.com/ArthurBrussee/brush/releases into server/tools/brush/.
set -euo pipefail

SCENE=${1:?usage: train_brush.sh <scene_dir>}
STEPS=${STEPS:-15000}
BRUSH=${BRUSH:-tools/brush/brush-app-aarch64-apple-darwin/brush_app}

"$BRUSH" "$SCENE" --with-viewer \
  --total-steps "$STEPS" --export-every 5000 \
  --export-path "$SCENE" --export-name "splat_{iter}.ply" \
  --eval-every 100000
