#!/usr/bin/env bash
# Camera poses for a splatting dataset with COLMAP (CPU is fine on a Mac).
#
#   splat_train/run_colmap.sh outputs/room_splat    (from server/)
#
# Expects <scene>/images/*.jpg (from video_to_frames.py). Writes
# <scene>/database.db and <scene>/sparse/0/, the layout Brush and other
# splat trainers load directly.
#
# All frames come from one phone lens, so they share one camera (focal length
# and distortion are estimated once). Matching is exhaustive because separate
# video passes only overlap across videos, not in time order.
set -euo pipefail

SCENE=${1:?usage: run_colmap.sh <scene_dir>}
MAPPER=${MAPPER:-global_mapper}   # or: mapper (incremental, slower, sometimes more robust)
DB="$SCENE/database.db"

rm -rf "$DB" "$SCENE/sparse"
mkdir -p "$SCENE/sparse"

colmap feature_extractor \
  --database_path "$DB" \
  --image_path "$SCENE/images" \
  --ImageReader.single_camera 1 \
  --ImageReader.camera_model OPENCV \
  --FeatureExtraction.use_gpu 0 \
  --SiftExtraction.max_num_features 8192

colmap exhaustive_matcher \
  --database_path "$DB" \
  --FeatureMatching.use_gpu 0 \
  --FeatureMatching.guided_matching 1

colmap "$MAPPER" \
  --database_path "$DB" \
  --image_path "$SCENE/images" \
  --output_path "$SCENE/sparse"

colmap model_analyzer --path "$SCENE/sparse/0"
