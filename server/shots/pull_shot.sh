#!/usr/bin/env bash
# Copy a shot rendered on the headset (Generate button) to the Mac and make an MP4.
#
#   shots/pull_shot.sh            (from server/; headset plugged in by USB) the latest shot
#   shots/pull_shot.sh shot3      the latest shot with that name (as shown in the Shots panel)
#   SCENE=Puffin-Indoor shots/pull_shot.sh shot3   only look in that world (scene)
#   shots/pull_shot.sh --list     list the shots on the headset
#   VFLIP=1 shots/pull_shot.sh    if the video comes out upside down
#
# On the headset shots live in Shots/<scene>/<yyyyMMdd_HHmmss>/ (frame_*.png + shot.json).
# Writes outputs/shots/<scene>/<name>/ with the frames, shot.json and <name>.mp4.
set -euo pipefail

PKG=${PKG:-com.UnityTechnologies.com.unity.template.urpblank}
ADB=${ADB:-$(command -v adb || ls /Applications/Unity/Hub/Editor/*/PlaybackEngines/AndroidPlayer/SDK/platform-tools/adb | tail -1)}
REMOTE=/sdcard/Android/data/$PKG/files/Shots

# "<timestamp> <dir> <name>" per shot, oldest first.
shots() {
  "$ADB" shell "for d in $REMOTE/${SCENE:-*}/*/; do [ -f \$d/shot.json ] && echo \$(basename \$d) \$d \$(grep -o '\"name\": *\"[^\"]*\"' \$d/shot.json | sed 's/.*: *\"//;s/\"\$//'); done" \
    | tr -d '\r' | sort
}

# Names may contain spaces: the name is everything after the second field.
if [ "${1:-}" = "--list" ]; then shots | while read -r ts d name; do echo "$(basename "$(dirname "${d%/}")")  $name ($ts)"; done; exit 0; fi
if [ -n "${1:-}" ]; then LINE=$(shots | while read -r ts d name; do [ "$name" = "$1" ] && echo "$ts $d $name"; done | tail -1)
else LINE=$(shots | tail -1); fi
[ -n "$LINE" ] || { echo "no such shot on the headset (try --list)"; exit 1; }
DIR=$(echo "$LINE" | cut -d' ' -f2); NAME=$(echo "$LINE" | cut -d' ' -f3-)

SCENE_DIR=$(basename "$(dirname "${DIR%/}")")
OUT=outputs/shots/$SCENE_DIR/$NAME
rm -rf "$OUT"; mkdir -p "$OUT"
"$ADB" pull "${DIR%/}/." "$OUT/"

FPS=$(grep -o '"fps": *[0-9]*' "$OUT/shot.json" | grep -o '[0-9]*$')
VF=${VFLIP:+-vf vflip}
ffmpeg -v error -y -framerate "${FPS:-30}" -i "$OUT/frame_%04d.png" $VF \
  -c:v libx264 -pix_fmt yuv420p -crf 18 "$OUT/$NAME.mp4"
echo "-> $OUT/$NAME.mp4 ($(ls "$OUT"/frame_*.png | wc -l | tr -d ' ') frames @ ${FPS:-30} fps)"
