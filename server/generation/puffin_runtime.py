"""Load Puffin-World and run its building blocks (I2T, T2I, chunked I2I)
outside the upstream demo scripts.

Upstream configs hard-code the authors' cluster paths for the base models
(Qwen2.5, SD3.5, C-RADIO). We rewrite that prefix to PUFFIN_BASE_DIR at load
time instead of editing the submodule.

Poses are OpenCV camera-to-world 4x4 matrices (+x right, +y down, +z forward),
the convention Puffin-World is trained on. Use common/pointcloud.py to go to
the Unity frame.
"""
import math
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
PUFFIN_ROOT = Path(os.environ.get(
    'PUFFIN_ROOT', REPO_ROOT / 'third_party' / 'Puffin' / 'Puffin-World'))
BASE_DIR = os.environ.get(
    'PUFFIN_BASE_DIR', os.path.expandvars('$SCRATCH/puffin_base'))
CKPT_DIR = os.environ.get(
    'PUFFIN_CKPT_DIR', os.path.expandvars('$SCRATCH/puffin_ckpt'))
UPSTREAM_BASE_PREFIX = '/mnt/afs_100t/NTU_slab/kliao/models'

# Upstream configs read relative paths (configs/scheduler_cus) and import
# `configs.*` / `src.*` / `scripts.*`, so everything runs from PUFFIN_ROOT.
os.chdir(PUFFIN_ROOT)
sys.path.insert(0, str(PUFFIN_ROOT))

import torch  # noqa: E402
from einops import rearrange  # noqa: E402
from mmengine.config import Config  # noqa: E402
from PIL import Image  # noqa: E402
from xtuner.model.utils import guess_load_checkpoint  # noqa: E402
from xtuner.registry import BUILDER  # noqa: E402

from scripts.demo.freeview_world_exp import (  # noqa: E402
    build_data_sample, image_to_text, split_caption, text_to_image)
from scripts.evaluation.generation_multi_view import (  # noqa: E402
    collect_batch_inputs, run_chunked_generation)

MODELS = {
    'pro': dict(
        config='configs/pipelines/final_stage_4_world_all_asym_attn_qwen2_5_1_5b_radiov4H_sd3p5L.py',
        checkpoint='Puffin-World-Pro.pth'),
    'base': dict(
        config='configs/pipelines/final_stage_4_world_all_asym_attn_qwen2_5_7b_radiov3H_sd3p5M.py',
        checkpoint='Puffin-World-Base.pth'),
}


def _remap_paths(node):
    """Recursively swap the upstream base-model prefix for BASE_DIR."""
    if isinstance(node, dict):
        for k, v in node.items():
            node[k] = _remap_paths(v)
    elif isinstance(node, list):
        return [_remap_paths(v) for v in node]
    elif isinstance(node, str) and node.startswith(UPSTREAM_BASE_PREFIX):
        return BASE_DIR + node[len(UPSTREAM_BASE_PREFIX):]
    return node


def load_model(name='pro', checkpoint=None, device='cuda', geometry=True):
    entry = MODELS[name]
    cfg = Config.fromfile(entry['config'])
    cfg.model.pretrained_pth = None
    cfg.model.use_activation_checkpointing = False
    _remap_paths(cfg.model)
    model = BUILDER.build(cfg.model)
    state = guess_load_checkpoint(checkpoint or os.path.join(CKPT_DIR, entry['checkpoint']))
    _, unexpected = model.load_state_dict(state, strict=False)
    if unexpected:
        print(f"[puffin] {len(unexpected)} unexpected keys in checkpoint")
    del state
    model = model.to(device).to(model.dtype).eval()
    # Same inference setup as the free-view demo: perspective field anchored
    # at the seed view's roll/pitch/vfov and propagated through relative poses.
    model.geometry_state = geometry
    model.physical_propagation = 'offline_prop'
    model.cam_cfg_mode = 'fix'
    return model


def load_seed_image(path, res=640):
    """Center-crop to square, resize to res, [-1, 1] CHW tensor."""
    img = Image.open(path).convert('RGB')
    w, h = img.size
    s = min(w, h)
    img = img.crop(((w - s) // 2, (h - s) // 2, (w + s) // 2, (h + s) // 2))
    img = img.resize((res, res), Image.LANCZOS)
    t = torch.from_numpy(np.asarray(img, dtype=np.float32) / 255.0)
    return rearrange(t * 2.0 - 1.0, 'h w c -> c h w'), img


def intrinsics_from_vfov(vfov, res=640):
    f = res / (2.0 * math.tan(max(vfov, 1e-3) / 2.0))
    return np.array([[f, 0.0, res / 2.0], [0.0, f, res / 2.0], [0.0, 0.0, 1.0]])


def understand(model, pil_img):
    """Seed photo -> (caption, (roll, pitch, vfov, k1) in radians)."""
    return split_caption(image_to_text(model, pil_img))


def views_for_chunks(num_chunks, num_views=8):
    """Total poses a chunked run consumes (chunks overlap by one view)."""
    return num_views + (num_chunks - 1) * (num_views - 1)


def generate(model, seed_img, poses_c2w, K, cam_params, num_views=8,
             cfg_scale=4.0, num_steps=50, seed=42):
    """Chunked I2I along poses_c2w (list of 4x4, poses_c2w[0] = seed view).

    len(poses_c2w) must equal views_for_chunks(n). Returns upstream's result
    dict ('gen_images_tensor', 'depth_samples', ...).
    """
    t_all = len(poses_c2w)
    assert (t_all - 1) % (num_views - 1) == 0, \
        f"{t_all} poses do not split into chunks of {num_views} views"
    chunk = (t_all - 1) // (num_views - 1)
    res = seed_img.shape[-1]
    pose_strs = [np.array2string(np.asarray(p, dtype=np.float64)) for p in poses_c2w]
    intr_strs = [np.array2string(np.asarray(K, dtype=np.float64))] * t_all
    anchor = " ".join(f"{v:.8f}" for v in cam_params)
    sample = build_data_sample(seed_img, pose_strs, intr_strs, anchor, res=res)
    ns = SimpleNamespace(
        num_views=num_views, chunk=chunk, cfg_scale=cfg_scale,
        num_steps=num_steps, height=res, width=res, cfg_prompt='',
        no_depth_align_chunks=False, depth_align_mode='scale',
        glb_no_align=False, no_depth_global_align=False)
    batch = collect_batch_inputs([sample], ns)
    generator = torch.Generator(device=model.device).manual_seed(seed)
    with torch.no_grad():
        return run_chunked_generation(
            model, ns, batch, [sample], batch['cam_values'],
            [pose_strs], None, generator)


def yaw_pan(n, deg_per_view):
    """n OpenCV c2w poses turning in place about the camera's up axis."""
    poses = []
    for i in range(n):
        a = math.radians(deg_per_view * i)
        c, s = math.cos(a), math.sin(a)
        P = np.eye(4)
        P[:3, :3] = [[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]]
        poses.append(P)
    return poses
