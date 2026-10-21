Puffin-World seed scenes (VR World Director), generated 2026-10-21 on Euler.
Only this README is in git (the folders are ~1 GB, see .gitignore). The worlds
used in VR are in unity/vr-director/Assets/PointClouds/Puffin/. Ask Rayane.

front/  Darius's first runs, only the views before the long pan drifted, plus
        the forward walk: indoor 105 deg, text (plaza) 70 deg, outdoor (ruin)
        105 deg. Upstream fusion (512^3 voxels, 1M points) -> pixelated.
full/   Everything of those runs: 385-deg pan + walk. The second half of each
        pan drifts into invented places and goes dark; kept for reference.
raw/    Same runs, raw.npz (frames, depths, poses per run) + meta.json.
dense/  raw/ re-fused denser on the Mac (server/puffin_fusion/dense_fuse.py,
        no voxel averaging, every view): 6M points each.
v2/     New runs on our Euler account (generation-server branch + the patch
        server/puffin_fusion/scenes_dense.patch): left + right turns of 105 deg
        each and a walk, fused dense (9M points). = the *Wide worlds in Unity.
        left/right/walk.mp4 are the generated views (mpeg4; v2_preview/ has
        H.264 copies that play on a Mac).

Frame of every .ply: floor at y = 0, meters, seed camera at (0, 1.5, 0)
looking down +z (Unity coordinates). *.json: camera paths in Unity
coordinates (trajectories_unity_c2w: 4x4, columns = camera right / up /
forward / position), seed camera estimate, scale. Scale assumes the seed
photo was taken 1.5 m above the floor.
