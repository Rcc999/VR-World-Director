"""World state export (server/generation/world_state.py, one folder per scene)
-> Unity's Assets/WorldStates/<scene>/, ready for VR Director > Build World State Scene.

Per scene it copies:
- the clouds listed in world_state.json -> clouds: real.ply and generated.ply
  (none for video-only scenes) to the scene folder; full.ply is those two merged,
  so it is skipped,
- world_state/world_state.json,
- world_state/<run>-{rgb,depth,pf_up,pf_lat}.mp4, re-encoded to H.264: the export
  writes MPEG-4 Part 2, which Unity's video player does not decode on every platform.

Usage (from server/):
    python -m world_state.to_unity ~/Downloads/vrwd_world_states \
        --unity ../unity/vr-director/Assets/WorldStates [--scenes ruin indoor]
"""
import argparse
import json
import os
import shutil
import subprocess

ROLES = ['real', 'generated']  # full = real + generated, not needed in Unity


def to_h264(src, dst):
    """MPEG-4 Part 2 -> H.264 (yuv420p, even size), same frames and fps."""
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', src, '-c:v', 'libx264', '-preset', 'medium',
                    '-crf', '20', '-pix_fmt', 'yuv420p', '-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2',
                    '-an', dst], check=True)


def import_scene(src, dst):
    os.makedirs(os.path.join(dst, 'world_state'), exist_ok=True)
    ws_json = os.path.join(src, 'world_state', 'world_state.json')
    ws = json.load(open(ws_json))
    clouds = []
    for role in ROLES:
        if role in ws['clouds']:
            shutil.copy2(os.path.join(src, 'world_state', ws['clouds'][role]['file']), os.path.join(dst, f'{role}.ply'))
            clouds.append(f'{role}.ply')

    shutil.copy2(ws_json, os.path.join(dst, 'world_state', 'world_state.json'))
    videos = sorted({f for run in ws['runs'].values() for f in run['files'].values()})
    for v in videos:
        out = os.path.join(dst, 'world_state', v)
        if not os.path.exists(out) or os.path.getmtime(out) < os.path.getmtime(os.path.join(src, 'world_state', v)):
            to_h264(os.path.join(src, 'world_state', v), out)
    print(f'{os.path.basename(src)}: clouds {clouds}, {len(videos)} videos')


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('export', help='unzipped export: one folder per scene, each with world_state/world_state.json')
    p.add_argument('--unity', required=True, help='Unity Assets/WorldStates folder')
    p.add_argument('--scenes', nargs='*', help='only these scenes (default: all)')
    a = p.parse_args()
    scenes = a.scenes or sorted(d for d in os.listdir(a.export)
                                if os.path.exists(os.path.join(a.export, d, 'world_state', 'world_state.json')))
    for s in scenes:
        import_scene(os.path.join(a.export, s), os.path.join(a.unity, s))


if __name__ == '__main__':
    main()
