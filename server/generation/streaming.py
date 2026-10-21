"""Chunk-by-chunk Puffin-World generation for the server.

Same chunked autoregression as upstream's run_chunked_generation
(scripts/evaluation/generation_multi_view.py), for one path, built from its
helpers: 8-view windows overlapping by one view, each window's ray maps
rebuilt relative to its first view, the previous window's last latent fed in
as the next anchor (no VAE round trip), the perspective-field anchor relayed
across windows, and each window's depth put on the first window's scale via
the overlap view plus upstream's reprojection refinement.

What upstream cannot do and the server needs:
  * yield every chunk as soon as it is generated,
  * stop between chunks (the caller just stops iterating),
  * resume: PathState carries everything the next chunk needs, so a later
    request can extend a path from where it ended instead of from the seed.

Upstream-only extras (combo trajectories, depth-visualization quantile maps,
batches > 1) are left out. check_stream.py compares this loop with upstream's.
"""
import time
from dataclasses import dataclass, field

import numpy as np
import torch

from generation import puffin_runtime as pr  # noqa: F401  (upstream on sys.path)
from scripts.evaluation.generation_multi_view import (
    _depth_np, _parse_4x4, _parse_K_np, overlap_depth_scale)
from scripts.evaluation.modules import (
    normalize_gen_outputs_multi, rebuild_chunk_ray_maps,
    solve_chunk_boundary_scale)

NUM_VIEWS = 8   # views per window the model was trained on (1 anchor + 7 targets)


def _str(m):
    return np.array2string(np.asarray(m, dtype=np.float64))


@dataclass
class PathState:
    """Where a path ended: everything its next chunk needs."""
    seed_pixel: torch.Tensor          # [3, H, W] in [-1, 1]; fills the target slots, as upstream
    pose: str                         # c2w of the last view (string, upstream's format)
    pixel: torch.Tensor               # last view, [3, H, W] in [-1, 1]
    latent: torch.Tensor = None       # last view's latent (None while at the seed)
    pp_anchor: object = None          # perspective-field params of the last view
    depth: torch.Tensor = None        # last view's depth, on the path's scale
    depth_refs: list = field(default_factory=list)   # last kept views, for refinement
    views_done: int = 1               # views so far, including the seed


@dataclass
class Chunk:
    index: int                        # chunk number within this stream() call
    view_ids: list                    # global view indices of the new frames
    frames: list                      # uint8 [H, W, 3] per new view
    depths: list                      # float32 [H, W] per new view (None without geometry)
    poses: list                       # 4x4 OpenCV c2w per new view
    anchor_depth: np.ndarray          # depth of the window's first view (the seed for chunk 0)
    seconds: float
    physics: list = None              # per new view: dict(roll, pitch, vfov, k1) in radians,
                                      # the perspective-field params Puffin conditioned it on


def seed_state(seed_img, seed_pose=None):
    return PathState(seed_pixel=seed_img, pixel=seed_img,
                     pose=_str(np.eye(4) if seed_pose is None else seed_pose))


def stream(model, state, poses, K, cam_params, num_steps=50, cfg_scale=4.0,
           generator=None):
    """Generate views along `poses` (4x4 OpenCV c2w, excluding the view
    `state` ends at), one chunk of up to 7 new views at a time. Yields Chunk
    and updates `state` in place, so after the loop, or a break, it describes
    the last generated view and can be passed to the next stream() call.

    A last window with fewer than 7 new poses is padded by repeating its
    final pose; the padded views are generated but not returned.
    cam_params (roll, pitch, vfov, k1) anchors the perspective field on the
    first chunk of a fresh path; later chunks relay state.pp_anchor.
    """
    res = state.pixel.shape[-1]
    intr = _str(K)
    anchor_str = " ".join(f"{v:.8f}" for v in cam_params)
    geometry = bool(getattr(model, 'geometry_state', False))
    if generator is None:
        generator = torch.Generator(device=model.device).manual_seed(42)

    todo = [_str(p) for p in poses]
    for index, start in enumerate(range(0, len(todo), NUM_VIEWS - 1)):
        t0 = time.perf_counter()
        new = todo[start:start + NUM_VIEWS - 1]
        n_new = len(new)
        window = [state.pose] + new + [new[-1]] * (NUM_VIEWS - 1 - n_new)
        intrs = [intr] * NUM_VIEWS
        fresh = state.latent is None

        cam_values = rebuild_chunk_ray_maps(window, intrs, res, res,
                                            torch.float32, torch.device('cpu'))
        pixels = [state.pixel] + [state.seed_pixel] * (NUM_VIEWS - 1)
        latents = None if fresh else [
            [state.latent] + [torch.zeros_like(state.latent)] * (NUM_VIEWS - 1)]
        gt_cam = [[anchor_str if fresh else ''] + [''] * (NUM_VIEWS - 1)]

        with torch.no_grad():
            out = model.generate_multi_view(
                prompt=[''], cfg_prompt=[''],
                pixel_values_init=[pixels], cam_values=[cam_values],
                cam_pose=[window], cam_intrinsics=[intrs],
                gt_cam_params=gt_cam,
                pp_anchor_params=None if state.pp_anchor is None else [state.pp_anchor],
                image_latents_init=latents,
                cfg_scale=cfg_scale, num_steps=num_steps, progress_bar=False,
                generator=generator, height=res, width=res, K=1,
                return_latents=True)

        gen = normalize_gen_outputs_multi(out['images'], B=1, T_tgt=NUM_VIEWS - 1)
        gen = gen.detach().cpu().float()[0]                       # [7, 3, H, W]
        last = n_new - 1                                           # last real new view

        depths, anchor_depth = [None] * n_new, None
        if geometry and out.get('depths') is not None:
            views = [d.detach().cpu().float() for d in out['depths'][0]]   # 8, incl. anchor
            if state.depth is not None:
                # Put this window on the path's scale: the anchor view's depth
                # is regenerated here, so compare it with the kept copy...
                s = overlap_depth_scale(state.depth, views[0])
                views = [v * s for v in views]
                # ...then upstream's reprojection refinement on the first new views.
                if state.depth_refs:
                    new_views = [dict(depth=_depth_np(views[i]),
                                      K=_parse_K_np(intrs[i], views[i]),
                                      c2w=np.asarray(_parse_4x4(window[i])))
                                 for i in range(min(3, len(views)))]
                    s2 = solve_chunk_boundary_scale(state.depth_refs, new_views, s_init=1.0)
                    if abs(s2 - 1.0) > 1e-3:
                        views = [v * s2 for v in views]
            anchor_depth = _depth_np(views[0])
            depths = [_depth_np(v) for v in views[1:1 + n_new]]
            state.depth_refs = (state.depth_refs + [
                dict(depth=_depth_np(views[i]), K=_parse_K_np(intr, views[i]),
                     c2w=np.asarray(_parse_4x4(window[i])))
                for i in range(1, 1 + n_new)][-3:])[-3:]
            state.depth = views[1 + last]

        # Advance to the last real new view (padding is dropped).
        state.pose = window[1 + last]
        state.pixel = gen[last]
        lat = out.get('latents')
        state.latent = lat[0][last].detach() if lat is not None else None
        pp = out.get('pp_cam_params')
        physics = None
        if pp is not None:
            state.pp_anchor = pp[0][1 + last]
            physics = [dict(zip(('roll', 'pitch', 'vfov', 'k1'), map(float, str(x).split())))
                       for x in pp[0][1:1 + n_new]]
        first_id = state.views_done
        state.views_done += n_new

        yield Chunk(
            index=index,
            view_ids=list(range(first_id, first_id + n_new)),
            frames=[((f.clamp(-1, 1) + 1) * 127.5).round().byte().permute(1, 2, 0).numpy()
                    for f in gen[:n_new]],
            depths=depths,
            poses=[np.asarray(_parse_4x4(p)) for p in window[1:1 + n_new]],
            anchor_depth=anchor_depth,
            seconds=time.perf_counter() - t0,
            physics=physics)
