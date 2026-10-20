#!/usr/bin/env bash
# Copy a shot rendered on the headset (Generate button) to the Mac and make an MP4.
#
#   shots/pull_shot.sh            (from server/; headset plugged in by USB)
#   shots/pull_shot.sh 20261020_153000     a specific shot instead of the latest
#   VFLIP=1 shots/pull_shot.sh    if the video comes out upside down
#
# Writes outputs/shots/<shot>/ with frame_*.png, trajectory.json, camera_path.json
# and <shot>.mp4.
set -euo pipefail

PKG=${PKG:-com.UnityTechnologies.com.unity.template.urpblank}
ADB=${ADB:-$(command -v adb || ls /Applications/Unity/Hub/Editor/*/PlaybackEngines/AndroidPlayer/SDK/platform-tools/adb | tail -1)}
REMOTE=/sdcard/Android/data/$PKG/files

SHOT=${1:-$("$ADB" shell ls "$REMOTE/Shots" | tr -d '\r' | sort | tail -1)}
[ -n "$SHOT" ] || { echo "no shots on the headset ($REMOTE/Shots)"; exit 1; }
OUT=outputs/shots/$SHOT
mkdir -p outputs/shots
"$ADB" pull "$REMOTE/Shots/$SHOT" outputs/shots/
"$ADB" pull "$REMOTE/camera_path.json" "$OUT/" 2>/dev/null || true

FPS=$(grep -o '"fps": *[0-9]*' "$OUT/trajectory.json" | grep -o '[0-9]*$')
VF=${VFLIP:+-vf vflip}
ffmpeg -v error -y -framerate "${FPS:-30}" -i "$OUT/frame_%04d.png" $VF \
  -c:v libx264 -pix_fmt yuv420p -crf 18 "$OUT/$SHOT.mp4"
echo "-> $OUT/$SHOT.mp4 ($(ls "$OUT"/frame_*.png | wc -l | tr -d ' ') frames @ ${FPS:-30} fps)"
