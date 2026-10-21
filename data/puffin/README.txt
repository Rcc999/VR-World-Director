Puffin-World seed scenes (VR World Director), generated 2026-10-21 on Euler.

front/  RECOMMENDED. Only the views before the long pan drifted, plus the
        forward walk: indoor 105 deg, text (plaza) 70 deg, outdoor (ruin) 105 deg.
full/   Everything generated: 385-deg pan + walk. The second half of each pan
        drifts into invented places and goes dark; kept for reference.
        *-pan.mp4 / *-walk.mp4 show the generated views.

Into Unity: copy a .ply into Assets/PointClouds/Puffin/, select it, run
VR Director > Build Point Cloud Viewer Scene. Same frame as the depth/splat
clouds: floor at y = 0, meters, seed camera at (0, 1.5, 0) looking down +z.
If the headset struggles, set Max Points on the importer (e.g. 500000).

*.json: camera paths in Unity coordinates (trajectories_unity_c2w: 4x4,
columns = camera right / up / forward / position), seed camera estimate,
scale. Scale assumes the seed photo was taken 1.5 m above the floor.
