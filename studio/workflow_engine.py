"""Lite ComfyUI-style visual workflow engine for CineForge Studio.

Provides curated ComfyUI-compatible node-graph presets (MiniMax-H3 4-step R2V/T2V,
LTX-2.5 I2V, LTX-2.5 V2V Cat-Recast, Multi-Model Film Pipeline), external ComfyUI
JSON import/export, parameter validation, and runtime override extraction for
CloudCoordinator and Colab GPU workers.
"""

from __future__ import annotations

import copy
import json
import os
import re
import threading
from pathlib import Path
from typing import Any

from . import DATA_DIR, ensure_data_dirs

WORKFLOWS_DIR = DATA_DIR / "workflows"


def _ensure_wf_dir() -> None:
    ensure_data_dirs()
    WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _align_128(val: int, lo: int = 512, hi: int = 1920) -> int:
    clamped = max(lo, min(hi, int(val)))
    return max(lo, (clamped // 64) * 64)


# ---------- Curated Lite ComfyUI Workflow Presets ----------

WORKFLOW_PRESETS: dict[str, dict[str, Any]] = {
    "h3_r2v_4step": {
        "id": "h3_r2v_4step",
        "name": "MiniMax-H3 参考图生视频 · 4步极速流",
        "badge": "主力推荐 · 免 Box",
        "engine": "h3",
        "mode": "original",
        "description": "对应 Comfy-Org/MiniMax-H3 官方 R2V 节点流：多参考图锁定角色 + 4 步 Turbo LoRA + 原生立体声同步输出。",
        "nodes": [
            {
                "id": "n_loader",
                "type": "UNETLoader",
                "title": "MiniMax-H3 模型加载",
                "category": "loader",
                "x": 24,
                "y": 36,
                "enabled": True,
                "inputs": [],
                "outputs": [
                    {"name": "MODEL", "type": "MODEL"},
                    {"name": "CLIP", "type": "CLIP"},
                    {"name": "VAE", "type": "VAE"},
                ],
                "params": {
                    "unet_name": {
                        "label": "主干权重",
                        "type": "select",
                        "value": "minimax_h3_ref2va_pruned_int8_convrot.safetensors",
                        "options": [
                            "minimax_h3_ref2va_pruned_int8_convrot.safetensors",
                            "minimax_h3_ref2va_pruned_fp8_scaled.safetensors",
                            "minimax_h3_ref2va_bf16.safetensors",
                        ],
                    },
                    "clip_name": {
                        "label": "文本编码器",
                        "type": "select",
                        "value": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
                        "options": [
                            "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
                            "qwen3vl_32b_minimax_h3_int8_convrot.safetensors",
                        ],
                    },
                },
            },
            {
                "id": "n_lora",
                "type": "LoraLoaderModelOnly",
                "title": "4 步加速 Turbo LoRA",
                "category": "loader",
                "x": 300,
                "y": 36,
                "enabled": True,
                "inputs": [{"name": "model", "type": "MODEL"}],
                "outputs": [{"name": "MODEL", "type": "MODEL"}],
                "params": {
                    "lora_name": {
                        "label": "LoRA 权重",
                        "type": "select",
                        "value": "minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors",
                        "options": [
                            "minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors",
                            "MiniMax-H3-Ref2VA-Acc-8Step.safetensors",
                        ],
                    },
                    "strength_model": {
                        "label": "LoRA 强度",
                        "type": "number",
                        "value": 1.0,
                        "min": 0.0,
                        "max": 1.5,
                        "step": 0.05,
                    },
                },
            },
            {
                "id": "n_ref",
                "type": "LoadImage",
                "title": "角色 / 场景参考图",
                "category": "input",
                "x": 24,
                "y": 244,
                "enabled": True,
                "inputs": [],
                "outputs": [{"name": "IMAGE", "type": "IMAGE"}],
                "params": {
                    "ref_image_size": {
                        "label": "参考图缩放策略",
                        "type": "select",
                        "value": "match",
                        "options": ["match", "max"],
                    },
                    "ref_note": {
                        "label": "角色视觉锁备注",
                        "type": "text",
                        "value": "一图一主体，锁定角色脸部与服装细节",
                    },
                },
            },
            {
                "id": "n_cond",
                "type": "MiniMaxH3ReferenceToVideo",
                "title": "H3 多模态条件与潜空间",
                "category": "conditioning",
                "x": 300,
                "y": 236,
                "enabled": True,
                "inputs": [
                    {"name": "clip", "type": "CLIP"},
                    {"name": "vae", "type": "VAE"},
                    {"name": "ref_image_0", "type": "IMAGE"},
                ],
                "outputs": [
                    {"name": "CONDITIONING", "type": "CONDITIONING"},
                    {"name": "LATENT", "type": "LATENT"},
                ],
                "params": {
                    "prompt": {
                        "label": "导演分镜提示词（留空则按每镜脚本）",
                        "type": "textarea",
                        "value": "",
                    },
                    "width": {
                        "label": "宽度",
                        "type": "number",
                        "value": 1344,
                        "min": 640,
                        "max": 1920,
                        "step": 64,
                    },
                    "height": {
                        "label": "高度",
                        "type": "number",
                        "value": 768,
                        "min": 512,
                        "max": 1280,
                        "step": 64,
                    },
                    "seconds": {
                        "label": "单镜时长 (秒)",
                        "type": "number",
                        "value": 5,
                        "min": 3,
                        "max": 10,
                        "step": 1,
                    },
                },
            },
            {
                "id": "n_sampler",
                "type": "KSampler",
                "title": "H3 采样器 (KSampler)",
                "category": "sampler",
                "x": 580,
                "y": 130,
                "enabled": True,
                "inputs": [
                    {"name": "model", "type": "MODEL"},
                    {"name": "positive", "type": "CONDITIONING"},
                    {"name": "latent_image", "type": "LATENT"},
                ],
                "outputs": [{"name": "LATENT", "type": "LATENT"}],
                "params": {
                    "steps": {
                        "label": "采样步数",
                        "type": "number",
                        "value": 4,
                        "min": 2,
                        "max": 30,
                        "step": 1,
                    },
                    "seed": {
                        "label": "随机种子 (0=随机)",
                        "type": "number",
                        "value": 0,
                        "min": 0,
                        "max": 2147483647,
                        "step": 1,
                    },
                    "sampler_name": {
                        "label": "采样算法",
                        "type": "select",
                        "value": "res_multistep",
                        "options": ["res_multistep", "euler", "uni_pc"],
                    },
                    "scheduler": {
                        "label": "调度器",
                        "type": "select",
                        "value": "simple",
                        "options": ["simple", "normal", "sgm_uniform"],
                    },
                },
            },
            {
                "id": "n_output",
                "type": "SaveVideo",
                "title": "AV 解码与 MP4 输出",
                "category": "output",
                "x": 850,
                "y": 130,
                "enabled": True,
                "inputs": [
                    {"name": "samples", "type": "LATENT"},
                    {"name": "vae", "type": "VAE"},
                ],
                "outputs": [],
                "params": {
                    "fps": {
                        "label": "帧率",
                        "type": "select",
                        "value": "24",
                        "options": ["24"],
                    },
                    "codec": {
                        "label": "编码格式",
                        "type": "select",
                        "value": "h264",
                        "options": ["h264", "h265"],
                    },
                    "upscale_2x": {
                        "label": "后置 RelayVSR 2× 超分",
                        "type": "boolean",
                        "value": False,
                    },
                },
            },
        ],
        "edges": [
            {"from": "n_loader", "from_port": "MODEL", "to": "n_lora", "to_port": "model", "data_type": "MODEL"},
            {"from": "n_loader", "from_port": "CLIP", "to": "n_cond", "to_port": "clip", "data_type": "CLIP"},
            {"from": "n_loader", "from_port": "VAE", "to": "n_cond", "to_port": "vae", "data_type": "VAE"},
            {"from": "n_ref", "from_port": "IMAGE", "to": "n_cond", "to_port": "ref_image_0", "data_type": "IMAGE"},
            {"from": "n_lora", "from_port": "MODEL", "to": "n_sampler", "to_port": "model", "data_type": "MODEL"},
            {"from": "n_cond", "from_port": "CONDITIONING", "to": "n_sampler", "to_port": "positive", "data_type": "CONDITIONING"},
            {"from": "n_cond", "from_port": "LATENT", "to": "n_sampler", "to_port": "latent_image", "data_type": "LATENT"},
            {"from": "n_sampler", "from_port": "LATENT", "to": "n_output", "to_port": "samples", "data_type": "LATENT"},
        ],
    },
    "h3_t2v_4step": {
        "id": "h3_t2v_4step",
        "name": "MiniMax-H3 纯文本生视频 · 4步直出流",
        "badge": "零参考图直出",
        "engine": "h3",
        "mode": "original",
        "description": "无需参考图，直接用文字剧本通过 MiniMax-H3 FL2VA + 4 步 Turbo LoRA 生成带原生同步声音的视频。",
        "nodes": [
            {
                "id": "n_loader",
                "type": "UNETLoader",
                "title": "MiniMax-H3 FL2VA 加载",
                "category": "loader",
                "x": 40,
                "y": 70,
                "enabled": True,
                "inputs": [],
                "outputs": [
                    {"name": "MODEL", "type": "MODEL"},
                    {"name": "CLIP", "type": "CLIP"},
                    {"name": "VAE", "type": "VAE"},
                ],
                "params": {
                    "unet_name": {
                        "label": "主干权重",
                        "type": "select",
                        "value": "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
                        "options": [
                            "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
                            "minimax_h3_fl2va_pruned_fp8_scaled.safetensors",
                        ],
                    },
                    "clip_name": {
                        "label": "文本编码器",
                        "type": "select",
                        "value": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
                        "options": [
                            "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
                            "qwen3vl_32b_minimax_h3_int8_convrot.safetensors",
                        ],
                    },
                },
            },
            {
                "id": "n_lora",
                "type": "LoraLoaderModelOnly",
                "title": "FL2V 4步 Turbo LoRA",
                "category": "loader",
                "x": 330,
                "y": 40,
                "enabled": True,
                "inputs": [{"name": "model", "type": "MODEL"}],
                "outputs": [{"name": "MODEL", "type": "MODEL"}],
                "params": {
                    "lora_name": {
                        "label": "LoRA 权重",
                        "type": "select",
                        "value": "minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors",
                        "options": [
                            "minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors",
                            "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors",
                        ],
                    },
                    "strength_model": {"label": "LoRA 强度", "type": "number", "value": 1.0, "min": 0.0, "max": 1.5, "step": 0.05},
                },
            },
            {
                "id": "n_cond",
                "type": "MiniMaxH3ImageToVideo",
                "title": "H3 文本条件编码",
                "category": "conditioning",
                "x": 330,
                "y": 230,
                "enabled": True,
                "inputs": [{"name": "clip", "type": "CLIP"}, {"name": "vae", "type": "VAE"}],
                "outputs": [{"name": "CONDITIONING", "type": "CONDITIONING"}, {"name": "LATENT", "type": "LATENT"}],
                "params": {
                    "prompt": {"label": "纯文本提示词（留空则按每镜脚本）", "type": "textarea", "value": ""},
                    "width": {"label": "宽度", "type": "number", "value": 1344, "min": 640, "max": 1920, "step": 64},
                    "height": {"label": "高度", "type": "number", "value": 768, "min": 512, "max": 1280, "step": 64},
                    "seconds": {"label": "单镜时长 (秒)", "type": "number", "value": 5, "min": 3, "max": 10, "step": 1},
                },
            },
            {
                "id": "n_sampler",
                "type": "KSampler",
                "title": "H3 采样器",
                "category": "sampler",
                "x": 580,
                "y": 60,
                "enabled": True,
                "inputs": [
                    {"name": "model", "type": "MODEL"},
                    {"name": "positive", "type": "CONDITIONING"},
                    {"name": "latent_image", "type": "LATENT"},
                ],
                "outputs": [{"name": "LATENT", "type": "LATENT"}],
                "params": {
                    "steps": {"label": "采样步数", "type": "number", "value": 4, "min": 2, "max": 30, "step": 1},
                    "seed": {"label": "随机种子 (0=随机)", "type": "number", "value": 0, "min": 0, "max": 2147483647, "step": 1},
                    "sampler_name": {"label": "采样算法", "type": "select", "value": "res_multistep", "options": ["res_multistep", "euler"]},
                },
            },
            {
                "id": "n_upscale",
                "type": "RelayVSR_X2",
                "title": "RelayVSR 2× 超分（可选）",
                "category": "post",
                "x": 580,
                "y": 260,
                "enabled": False,
                "inputs": [{"name": "samples", "type": "LATENT"}],
                "outputs": [{"name": "VIDEO", "type": "VIDEO"}],
                "params": {"sr_ratio": {"label": "放大倍率", "type": "select", "value": "2x", "options": ["2x"]}},
            },
            {
                "id": "n_output",
                "type": "SaveVideo",
                "title": "AV 解码与输出",
                "category": "output",
                "x": 850,
                "y": 140,
                "enabled": True,
                "inputs": [{"name": "samples", "type": "LATENT"}, {"name": "enhanced", "type": "VIDEO"}],
                "outputs": [],
                "params": {"fps": {"label": "帧率", "type": "select", "value": "24", "options": ["24"]}},
            },
        ],
        "edges": [
            {"from": "n_loader", "from_port": "MODEL", "to": "n_lora", "to_port": "model", "data_type": "MODEL"},
            {"from": "n_loader", "from_port": "CLIP", "to": "n_cond", "to_port": "clip", "data_type": "CLIP"},
            {"from": "n_loader", "from_port": "VAE", "to": "n_cond", "to_port": "vae", "data_type": "VAE"},
            {"from": "n_lora", "from_port": "MODEL", "to": "n_sampler", "to_port": "model", "data_type": "MODEL"},
            {"from": "n_cond", "from_port": "CONDITIONING", "to": "n_sampler", "to_port": "positive", "data_type": "CONDITIONING"},
            {"from": "n_cond", "from_port": "LATENT", "to": "n_sampler", "to_port": "latent_image", "data_type": "LATENT"},
            {"from": "n_sampler", "from_port": "LATENT", "to": "n_upscale", "to_port": "samples", "data_type": "LATENT"},
            {"from": "n_sampler", "from_port": "LATENT", "to": "n_output", "to_port": "samples", "data_type": "LATENT"},
            {"from": "n_upscale", "from_port": "VIDEO", "to": "n_output", "to_port": "enhanced", "data_type": "VIDEO"},
        ],
    },
    "ltx25_i2v": {
        "id": "ltx25_i2v",
        "name": "LTX-2.5 首帧图生视频流 (Distilled / DFR)",
        "badge": "人像特写 & 口型强",
        "engine": "ltx",
        "mode": "original",
        "description": "单首帧关键帧驱动 Lightricks LTX-2.5 22B 音视频联合生成，适合人物近景、中文对白口型与精细补拍。",
        "nodes": [
            {
                "id": "n_kf",
                "type": "LoadImage",
                "title": "首帧关键帧 (1344×768)",
                "category": "input",
                "x": 40,
                "y": 70,
                "enabled": True,
                "inputs": [],
                "outputs": [{"name": "IMAGE", "type": "IMAGE"}],
                "params": {
                    "fit_mode": {"label": "裁切适配", "type": "select", "value": "center_crop", "options": ["center_crop"]},
                },
            },
            {
                "id": "n_ltx_model",
                "type": "LTX25ModelLoader",
                "title": "LTX-2.5 22B + Gemma4 加载",
                "category": "loader",
                "x": 40,
                "y": 245,
                "enabled": True,
                "inputs": [],
                "outputs": [{"name": "MODEL", "type": "MODEL"}],
                "params": {
                    "pipeline": {
                        "label": "推理管线",
                        "type": "select",
                        "value": "distilled",
                        "options": ["distilled", "dfr"],
                    },
                },
            },
            {
                "id": "n_ltx_run",
                "type": "LTX25ImageToVideo",
                "title": "LTX-2.5 音视频联合生成",
                "category": "sampler",
                "x": 380,
                "y": 140,
                "enabled": True,
                "inputs": [
                    {"name": "model", "type": "MODEL"},
                    {"name": "keyframe", "type": "IMAGE"},
                ],
                "outputs": [{"name": "VIDEO", "type": "VIDEO"}],
                "params": {
                    "prompt": {"label": "提示词覆盖（留空用分镜脚本）", "type": "textarea", "value": ""},
                    "width": {"label": "宽度", "type": "number", "value": 1344, "min": 768, "max": 1344, "step": 64},
                    "height": {"label": "高度", "type": "number", "value": 768, "min": 512, "max": 768, "step": 64},
                    "seconds": {"label": "时长 (秒)", "type": "number", "value": 5, "min": 3, "max": 10, "step": 1},
                    "seed": {"label": "随机种子", "type": "number", "value": 42, "min": 0, "max": 2147483647, "step": 1},
                },
            },
            {
                "id": "n_output",
                "type": "SaveVideo",
                "title": "解码校验与成片回传",
                "category": "output",
                "x": 740,
                "y": 140,
                "enabled": True,
                "inputs": [{"name": "video", "type": "VIDEO"}],
                "outputs": [],
                "params": {"fps": {"label": "帧率", "type": "select", "value": "24", "options": ["24"]}},
            },
        ],
        "edges": [
            {"from": "n_kf", "from_port": "IMAGE", "to": "n_ltx_run", "to_port": "keyframe", "data_type": "IMAGE"},
            {"from": "n_ltx_model", "from_port": "MODEL", "to": "n_ltx_run", "to_port": "model", "data_type": "MODEL"},
            {"from": "n_ltx_run", "from_port": "VIDEO", "to": "n_output", "to_port": "video", "data_type": "VIDEO"},
        ],
    },
    "ltx25_v2v_cat": {
        "id": "ltx25_v2v_cat",
        "name": "LTX-2.5 V2V 视频换角 / 猫咪重演流",
        "badge": "爆款 V2V · 护爪去字幕",
        "engine": "v2v",
        "mode": "v2v",
        "description": "真人原片 → 抹除硬字幕 → Depth/Canny 运动控制 + 护爪遮罩 → LTX-2.5 Union-Control IC-LoRA 原声口型重演 + 左右对照合成。",
        "nodes": [
            {
                "id": "n_src",
                "type": "LoadVideo",
                "title": "原片视频输入",
                "category": "input",
                "x": 30,
                "y": 50,
                "enabled": True,
                "inputs": [],
                "outputs": [
                    {"name": "VIDEO", "type": "VIDEO"},
                    {"name": "AUDIO", "type": "AUDIO"},
                ],
                "params": {
                    "keep_audio": {"label": "保留原声对口型", "type": "boolean", "value": True},
                },
            },
            {
                "id": "n_ctrl",
                "type": "V2VControlPreprocess",
                "title": "去字幕 + 深度/边缘 + 护爪遮罩",
                "category": "conditioning",
                "x": 310,
                "y": 50,
                "enabled": True,
                "inputs": [{"name": "video", "type": "VIDEO"}],
                "outputs": [
                    {"name": "CONTROL", "type": "VIDEO"},
                    {"name": "MASK", "type": "MASK"},
                ],
                "params": {
                    "control": {"label": "控制信号", "type": "select", "value": "depth", "options": ["depth", "canny"]},
                    "desub": {"label": "自动抹除底部硬字幕", "type": "boolean", "value": True},
                    "paw_guard": {"label": "护爪防穿帮（融化人手轮廓）", "type": "boolean", "value": True},
                },
            },
            {
                "id": "n_kf",
                "type": "LoadImage",
                "title": "目标主角定妆首帧",
                "category": "input",
                "x": 310,
                "y": 250,
                "enabled": True,
                "inputs": [],
                "outputs": [{"name": "IMAGE", "type": "IMAGE"}],
                "params": {
                    "image_strength": {"label": "首帧锁定强度", "type": "number", "value": 1.0, "min": 0.4, "max": 1.0, "step": 0.05},
                },
            },
            {
                "id": "n_v2v",
                "type": "LTX25UnionControlICLoRA",
                "title": "LTX-2.5 Union-Control IC-LoRA",
                "category": "sampler",
                "x": 610,
                "y": 130,
                "enabled": True,
                "inputs": [
                    {"name": "control", "type": "VIDEO"},
                    {"name": "mask", "type": "MASK"},
                    {"name": "keyframe", "type": "IMAGE"},
                    {"name": "audio", "type": "AUDIO"},
                ],
                "outputs": [{"name": "VIDEO", "type": "VIDEO"}],
                "params": {
                    "lora_strength": {"label": "IC-LoRA 强度", "type": "number", "value": 1.0, "min": 0.5, "max": 1.2, "step": 0.05},
                    "width": {"label": "宽 (需128倍数)", "type": "select", "value": "1024", "options": ["768", "1024", "1152", "1280"]},
                    "height": {"label": "高 (需128倍数)", "type": "select", "value": "768", "options": ["768", "1024", "1280"]},
                    "seed": {"label": "随机种子", "type": "number", "value": 42, "min": 0, "max": 2147483647, "step": 1},
                },
            },
            {
                "id": "n_output",
                "type": "SideBySideMux",
                "title": "纯净猫咪版 + 左右对照输出",
                "category": "output",
                "x": 910,
                "y": 130,
                "enabled": True,
                "inputs": [{"name": "video", "type": "VIDEO"}],
                "outputs": [],
                "params": {
                    "export_sbs": {"label": "同时生成左右原片对照版", "type": "boolean", "value": True},
                },
            },
        ],
        "edges": [
            {"from": "n_src", "from_port": "VIDEO", "to": "n_ctrl", "to_port": "video", "data_type": "VIDEO"},
            {"from": "n_src", "from_port": "AUDIO", "to": "n_v2v", "to_port": "audio", "data_type": "AUDIO"},
            {"from": "n_ctrl", "from_port": "CONTROL", "to": "n_v2v", "to_port": "control", "data_type": "VIDEO"},
            {"from": "n_ctrl", "from_port": "MASK", "to": "n_v2v", "to_port": "mask", "data_type": "MASK"},
            {"from": "n_kf", "from_port": "IMAGE", "to": "n_v2v", "to_port": "keyframe", "data_type": "IMAGE"},
            {"from": "n_v2v", "from_port": "VIDEO", "to": "n_output", "to_port": "video", "data_type": "VIDEO"},
        ],
    },
    "multi_model_film": {
        "id": "multi_model_film",
        "name": "多模型混拍全片流 (H3 + LTX-2.5 + RelayVSR)",
        "badge": "整片制片推荐",
        "engine": "h3",
        "mode": "original",
        "description": "一条工作流串联多模型：剧本拆镜 → 按镜头路由至 MiniMax-H3 / LTX-2.5 → 可选 RelayVSR 2× 增强 → 自动精剪成片。",
        "nodes": [
            {
                "id": "n_story",
                "type": "CineForgeStoryBrief",
                "title": "剧本与视觉锁输入",
                "category": "input",
                "x": 36,
                "y": 130,
                "enabled": True,
                "inputs": [],
                "outputs": [
                    {"name": "SHOTS", "type": "CONDITIONING"},
                    {"name": "REFS", "type": "IMAGE"},
                ],
                "params": {
                    "seconds": {"label": "默认单镜时长 (秒)", "type": "number", "value": 5, "min": 3, "max": 8, "step": 1},
                },
            },
            {
                "id": "n_router",
                "type": "MultiModelRouter",
                "title": "多模型分镜路由",
                "category": "conditioning",
                "x": 320,
                "y": 130,
                "enabled": True,
                "inputs": [
                    {"name": "shots", "type": "CONDITIONING"},
                    {"name": "refs", "type": "IMAGE"},
                ],
                "outputs": [
                    {"name": "H3_QUEUE", "type": "MODEL"},
                    {"name": "LTX_QUEUE", "type": "MODEL"},
                ],
                "params": {
                    "default_engine": {
                        "label": "默认主力模型",
                        "type": "select",
                        "value": "h3",
                        "options": ["h3", "ltx"],
                    },
                    "steps": {"label": "H3 步数", "type": "number", "value": 4, "min": 2, "max": 20, "step": 1},
                },
            },
            {
                "id": "n_colab",
                "type": "ColabFarmExecute",
                "title": "Colab 多卡并行渲染",
                "category": "sampler",
                "x": 610,
                "y": 60,
                "enabled": True,
                "inputs": [
                    {"name": "h3", "type": "MODEL"},
                    {"name": "ltx", "type": "MODEL"},
                ],
                "outputs": [{"name": "CLIPS", "type": "VIDEO"}],
                "params": {
                    "width": {"label": "宽度", "type": "number", "value": 1344, "min": 640, "max": 1920, "step": 64},
                    "height": {"label": "高度", "type": "number", "value": 768, "min": 512, "max": 1280, "step": 64},
                },
            },
            {
                "id": "n_upscale",
                "type": "RelayVSR_X2",
                "title": "RelayVSR 2× 超分（可选）",
                "category": "post",
                "x": 610,
                "y": 265,
                "enabled": False,
                "inputs": [{"name": "clips", "type": "VIDEO"}],
                "outputs": [{"name": "HD_CLIPS", "type": "VIDEO"}],
                "params": {"sr_ratio": {"label": "倍率", "type": "select", "value": "2x", "options": ["2x"]}},
            },
            {
                "id": "n_master",
                "type": "FFmpegMasterCut",
                "title": "自动拼接配乐母版",
                "category": "output",
                "x": 900,
                "y": 145,
                "enabled": True,
                "inputs": [
                    {"name": "clips", "type": "VIDEO"},
                    {"name": "hd_clips", "type": "VIDEO"},
                ],
                "outputs": [],
                "params": {"codec": {"label": "封装编码", "type": "select", "value": "h264", "options": ["h264"]}},
            },
        ],
        "edges": [
            {"from": "n_story", "from_port": "SHOTS", "to": "n_router", "to_port": "shots", "data_type": "CONDITIONING"},
            {"from": "n_story", "from_port": "REFS", "to": "n_router", "to_port": "refs", "data_type": "IMAGE"},
            {"from": "n_router", "from_port": "H3_QUEUE", "to": "n_colab", "to_port": "h3", "data_type": "MODEL"},
            {"from": "n_router", "from_port": "LTX_QUEUE", "to": "n_colab", "to_port": "ltx", "data_type": "MODEL"},
            {"from": "n_colab", "from_port": "CLIPS", "to": "n_upscale", "to_port": "clips", "data_type": "VIDEO"},
            {"from": "n_colab", "from_port": "CLIPS", "to": "n_master", "to_port": "clips", "data_type": "VIDEO"},
            {"from": "n_upscale", "from_port": "HD_CLIPS", "to": "n_master", "to_port": "hd_clips", "data_type": "VIDEO"},
        ],
    },
}


def list_workflow_presets() -> list[dict[str, Any]]:
    return [
        {
            "id": p["id"],
            "name": p["name"],
            "badge": p["badge"],
            "engine": p["engine"],
            "mode": p["mode"],
            "description": p["description"],
            "node_count": len(p["nodes"]),
            "edge_count": len(p["edges"]),
        }
        for p in WORKFLOW_PRESETS.values()
    ]


def _default_preset_for_detail(detail: dict[str, Any]) -> str:
    proj = detail.get("project") or {}
    shots = detail.get("shots") or []
    if proj.get("mode") == "v2v":
        return "ltx25_v2v_cat"
    if shots and all(str(s.get("engine") or "").lower().startswith("ltx") for s in shots):
        return "ltx25_i2v"
    if not (detail.get("refs") or []):
        return "h3_t2v_4step"
    return "h3_r2v_4step"


def build_default_workflow(detail: dict[str, Any], preset_id: str | None = None) -> dict[str, Any]:
    proj = detail.get("project") or {}
    pid = str(proj.get("id") or "project")
    chosen = preset_id if preset_id in WORKFLOW_PRESETS else _default_preset_for_detail(detail)
    wf = copy.deepcopy(WORKFLOW_PRESETS[chosen])
    wf["project_id"] = pid
    wf["preset_id"] = chosen
    wf["schema"] = "cineforge-comfy-lite/v1"

    aspect = str(proj.get("aspect") or ("4:3" if proj.get("mode") == "v2v" else "16:9"))
    if aspect == "9:16":
        w, h = (768, 1280)
    elif aspect == "4:3":
        w, h = (1024, 768)
    else:
        w, h = (1344, 768)

    for node in wf["nodes"]:
        params = node.get("params") or {}
        if "width" in params:
            if params["width"].get("type") == "select":
                params["width"]["value"] = str(w) if str(w) in (params["width"].get("options") or []) else params["width"]["value"]
            else:
                params["width"]["value"] = w
        if "height" in params:
            if params["height"].get("type") == "select":
                params["height"]["value"] = str(h) if str(h) in (params["height"].get("options") or []) else params["height"]["value"]
            else:
                params["height"]["value"] = h
        if node.get("type") == "V2VControlPreprocess":
            v2v_opts = proj.get("v2v_options") or {}
            if "desub" in params and "desub" in v2v_opts:
                params["desub"]["value"] = bool(v2v_opts["desub"])
            if "paw_guard" in params and "paw_guard" in v2v_opts:
                params["paw_guard"]["value"] = bool(v2v_opts["paw_guard"])
    return wf


def _workflow_file(project_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_-]*", project_id):
        raise ValueError("Invalid project_id")
    return WORKFLOWS_DIR / f"{project_id}.json"


def load_saved_workflow(project_id: str) -> dict[str, Any] | None:
    try:
        p = _workflow_file(project_id)
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("nodes"), list):
                return data
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return None


def get_project_workflow(detail: dict[str, Any], *, preset_id: str | None = None) -> dict[str, Any]:
    pid = str((detail.get("project") or {}).get("id") or "")
    if preset_id and preset_id in WORKFLOW_PRESETS:
        wf = build_default_workflow(detail, preset_id=preset_id)
    else:
        wf = load_saved_workflow(pid) or build_default_workflow(detail)
    wf["presets"] = list_workflow_presets()
    wf["runtime_overrides"] = extract_runtime_overrides(wf)
    wf["comfyui_api"] = compile_to_comfyui_api(wf, detail=detail)
    return wf


def validate_and_normalize_workflow(project_id: str, raw: dict[str, Any], detail: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("Workflow payload must be a JSON object")

    preset_id = str(raw.get("preset_id") or raw.get("id") or "").strip()
    if raw.get("apply_preset") and preset_id in WORKFLOW_PRESETS:
        wf = build_default_workflow(detail or {"project": {"id": project_id}}, preset_id=preset_id)
        return wf

    nodes_in = raw.get("nodes")
    if not isinstance(nodes_in, list) or not nodes_in:
        raise ValueError("Workflow must contain a non-empty 'nodes' list")
    if len(nodes_in) > 40:
        raise ValueError("Workflow exceeds maximum 40 nodes")

    norm_nodes: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for idx, n in enumerate(nodes_in):
        if not isinstance(n, dict):
            raise ValueError(f"Node #{idx} must be an object")
        nid = str(n.get("id") or f"node_{idx + 1}").strip()[:48]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", nid):
            nid = f"node_{idx + 1}"
        if nid in seen_ids:
            nid = f"{nid}_{idx}"
        seen_ids.add(nid)
        norm_params: dict[str, Any] = {}
        raw_params = n.get("params") if isinstance(n.get("params"), dict) else {}
        for pk, pv in raw_params.items():
            key = str(pk)[:48]
            if isinstance(pv, dict) and "value" in pv:
                item = dict(pv)
                if item.get("type") == "number":
                    try:
                        val = float(item["value"])
                    except (TypeError, ValueError):
                        val = 0.0
                    if "min" in item:
                        val = max(float(item["min"]), val)
                    if "max" in item:
                        val = min(float(item["max"]), val)
                    item["value"] = int(val) if float(item.get("step", 1)) >= 1 else round(val, 3)
                elif item.get("type") == "boolean":
                    item["value"] = bool(item["value"])
                else:
                    item["value"] = str(item["value"])[:4000]
                norm_params[key] = item
            else:
                norm_params[key] = {"label": key, "type": "text", "value": str(pv)[:4000]}
        norm_nodes.append(
            {
                "id": nid,
                "type": str(n.get("type") or "CustomNode")[:64],
                "title": str(n.get("title") or n.get("type") or nid)[:80],
                "category": str(n.get("category") or "conditioning")[:24],
                "x": max(0, min(2400, int(round(float(n.get("x", 40 + (idx % 4) * 280)))))),
                "y": max(0, min(1600, int(round(float(n.get("y", 40 + (idx // 4) * 200)))))),
                "enabled": bool(n.get("enabled", True)),
                "inputs": list(n.get("inputs") or [])[:12],
                "outputs": list(n.get("outputs") or [])[:12],
                "params": norm_params,
            }
        )

    edges_in = raw.get("edges") if isinstance(raw.get("edges"), list) else []
    norm_edges: list[dict[str, Any]] = []
    for e in edges_in[:80]:
        if not isinstance(e, dict):
            continue
        src = str(e.get("from") or "")
        dst = str(e.get("to") or "")
        if src in seen_ids and dst in seen_ids and src != dst:
            norm_edges.append(
                {
                    "from": src,
                    "from_port": str(e.get("from_port") or "OUT")[:32],
                    "to": dst,
                    "to_port": str(e.get("to_port") or "IN")[:32],
                    "data_type": str(e.get("data_type") or "ANY")[:24],
                }
            )

    engine = str(raw.get("engine") or "").lower()
    if engine not in ("h3", "ltx", "v2v"):
        engine = _infer_engine_from_nodes(norm_nodes)

    return {
        "schema": "cineforge-comfy-lite/v1",
        "id": str(raw.get("id") or preset_id or f"wf_{project_id}")[:64],
        "preset_id": preset_id if preset_id in WORKFLOW_PRESETS else "custom",
        "project_id": project_id,
        "name": str(raw.get("name") or "自定义 ComfyUI 工作流")[:80],
        "badge": str(raw.get("badge") or "自定义节点流")[:40],
        "engine": engine,
        "mode": "v2v" if engine == "v2v" else "original",
        "description": str(raw.get("description") or "")[:300],
        "nodes": norm_nodes,
        "edges": norm_edges,
    }


def _infer_engine_from_nodes(nodes: list[dict[str, Any]]) -> str:
    types = " ".join(str(n.get("type") or "").lower() for n in nodes if n.get("enabled", True))
    if "v2v" in types or "unioncontrol" in types or "ic_lora" in types:
        return "v2v"
    if "ltx25" in types or "ltx" in types:
        return "ltx"
    for n in nodes:
        if n.get("type") == "MultiModelRouter" and n.get("enabled", True):
            val = ((n.get("params") or {}).get("default_engine") or {}).get("value")
            if str(val).lower() == "ltx":
                return "ltx"
    return "h3"


def save_project_workflow(project_id: str, raw: dict[str, Any], detail: dict[str, Any] | None = None) -> dict[str, Any]:
    _ensure_wf_dir()
    wf = validate_and_normalize_workflow(project_id, raw, detail=detail)
    _atomic_write_json(_workflow_file(project_id), wf)
    out = dict(wf)
    out["presets"] = list_workflow_presets()
    out["runtime_overrides"] = extract_runtime_overrides(wf)
    out["comfyui_api"] = compile_to_comfyui_api(wf, detail=detail)
    return out


def import_external_workflow(project_id: str, raw: Any, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    """Import either a CineForge Lite workflow JSON or a native ComfyUI API / UI JSON."""
    if not isinstance(raw, dict):
        raise ValueError("导入内容必须是 JSON 对象")

    # Case 1: Already a CineForge Lite workflow
    if raw.get("schema", "").startswith("cineforge-comfy-lite") or (
        isinstance(raw.get("nodes"), list) and raw.get("nodes") and isinstance(raw["nodes"][0], dict) and "params" in raw["nodes"][0]
    ):
        return save_project_workflow(project_id, raw, detail=detail)

    # Case 2: Standard ComfyUI UI workflow ({nodes: [...], links: [...]})
    if isinstance(raw.get("nodes"), list) and "links" in raw:
        nodes = []
        edges = []
        id_map: dict[Any, str] = {}
        for idx, cn in enumerate(raw["nodes"][:40]):
            if not isinstance(cn, dict):
                continue
            nid = f"c_{cn.get('id', idx + 1)}"
            id_map[cn.get("id")] = nid
            pos = cn.get("pos") or [40 + (idx % 4) * 280, 40 + (idx // 4) * 200]
            x = pos[0] if isinstance(pos, list) and len(pos) >= 2 else 40 + (idx % 4) * 280
            y = pos[1] if isinstance(pos, list) and len(pos) >= 2 else 40 + (idx // 4) * 200
            widgets = cn.get("widgets_values") or []
            params = {
                f"widget_{wi}": {"label": f"参数 {wi + 1}", "type": "text", "value": str(wv)[:500]}
                for wi, wv in enumerate(widgets[:8])
            }
            nodes.append(
                {
                    "id": nid,
                    "type": str(cn.get("type") or "ComfyNode"),
                    "title": str(cn.get("title") or cn.get("type") or nid),
                    "category": _categorize_comfy_class(str(cn.get("type") or "")),
                    "x": max(20, min(1800, int(round(float(x))))),
                    "y": max(20, min(1200, int(round(float(y))))),
                    "enabled": int(cn.get("mode", 0)) == 0,
                    "inputs": [{"name": str(inp.get("name") or "in"), "type": str(inp.get("type") or "ANY")} for inp in (cn.get("inputs") or []) if isinstance(inp, dict)],
                    "outputs": [{"name": str(outp.get("name") or "out"), "type": str(outp.get("type") or "ANY")} for outp in (cn.get("outputs") or []) if isinstance(outp, dict)],
                    "params": params,
                }
            )
        for lk in (raw.get("links") or [])[:80]:
            if isinstance(lk, list) and len(lk) >= 6:
                src = id_map.get(lk[1])
                dst = id_map.get(lk[3])
                if src and dst and src != dst:
                    edges.append(
                        {
                            "from": src,
                            "from_port": str(lk[2]),
                            "to": dst,
                            "to_port": str(lk[4]),
                            "data_type": str(lk[5] or "ANY"),
                        }
                    )
        return save_project_workflow(
            project_id,
            {"name": "导入的 ComfyUI 工作流", "badge": "ComfyUI UI 导入", "nodes": nodes, "edges": edges},
            detail=detail,
        )

    # Case 3: Standard ComfyUI API prompt JSON ({ "1": { "class_type": "...", "inputs": {...} } })
    api_entries = [
        (str(k), v)
        for k, v in raw.items()
        if isinstance(v, dict) and isinstance(v.get("class_type"), str)
    ]
    if api_entries:
        nodes = []
        edges = []
        for idx, (nid, entry) in enumerate(api_entries[:40]):
            cls_type = entry["class_type"]
            raw_in = entry.get("inputs") if isinstance(entry.get("inputs"), dict) else {}
            in_ports = []
            params = {}
            for k, v in raw_in.items():
                if isinstance(v, list) and len(v) == 2 and isinstance(v[0], (str, int)):
                    in_ports.append({"name": str(k), "type": "ANY"})
                    edges.append(
                        {
                            "from": f"n_{v[0]}",
                            "from_port": f"OUT_{v[1]}",
                            "to": f"n_{nid}",
                            "to_port": str(k),
                            "data_type": "ANY",
                        }
                    )
                else:
                    ptype = "boolean" if isinstance(v, bool) else ("number" if isinstance(v, (int, float)) else "text")
                    params[str(k)] = {"label": str(k), "type": ptype, "value": v}
            nodes.append(
                {
                    "id": f"n_{nid}",
                    "type": cls_type,
                    "title": (entry.get("_meta") or {}).get("title") or cls_type,
                    "category": _categorize_comfy_class(cls_type),
                    "x": 40 + (idx % 4) * 280,
                    "y": 40 + (idx // 4) * 200,
                    "enabled": True,
                    "inputs": in_ports,
                    "outputs": [{"name": "OUT_0", "type": "ANY"}],
                    "params": params,
                }
            )
        return save_project_workflow(
            project_id,
            {"name": "导入的 ComfyUI API 流", "badge": "ComfyUI API 导入", "nodes": nodes, "edges": edges},
            detail=detail,
        )

    raise ValueError("无法识别的工作流 JSON 格式（支持 CineForge Lite 或标准 ComfyUI API / UI JSON）")


def _categorize_comfy_class(cls_name: str) -> str:
    low = cls_name.lower()
    if any(k in low for k in ("loader", "lora", "vae", "clip")):
        return "loader"
    if any(k in low for k in ("loadimage", "loadvideo", "story")):
        return "input"
    if any(k in low for k in ("sampler", "ltx25", "colab", "ic_lora", "union")):
        return "sampler"
    if any(k in low for k in ("save", "mux", "master", "createvideo")):
        return "output"
    if any(k in low for k in ("vsr", "upscale", "enhance")):
        return "post"
    return "conditioning"


def extract_runtime_overrides(wf: dict[str, Any]) -> dict[str, Any]:
    """Extract flat execution overrides from the active nodes in a Lite ComfyUI graph."""
    ov: dict[str, Any] = {
        "engine": str(wf.get("engine") or "h3"),
        "upscale_2x": False,
    }
    for node in wf.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        ntype = str(node.get("type") or "")
        enabled = bool(node.get("enabled", True))
        params = node.get("params") or {}

        def _val(key: str, default: Any = None) -> Any:
            item = params.get(key)
            return item.get("value", default) if isinstance(item, dict) else default

        if ntype == "SaveVideo" and _val("upscale_2x") is not None:
            ov["upscale_2x"] = bool(_val("upscale_2x"))
        if ntype == "RelayVSR_X2":
            ov["upscale_2x"] = enabled
            continue
        if not enabled:
            if ntype == "LoraLoaderModelOnly":
                ov["lora_strength"] = 0.0
            continue

        if ntype == "LoraLoaderModelOnly":
            ov["lora_name"] = _val("lora_name")
            ov["lora_strength"] = float(_val("strength_model", 1.0))
        elif ntype == "UNETLoader":
            ov["unet_name"] = _val("unet_name")
            ov["clip_name"] = _val("clip_name")
        elif ntype in ("MiniMaxH3ReferenceToVideo", "MiniMaxH3ImageToVideo", "LTX25ImageToVideo"):
            if _val("prompt"):
                ov["prompt_override"] = str(_val("prompt")).strip()
            if _val("width") is not None:
                ov["width"] = _align_128(int(float(_val("width"))))
            if _val("height") is not None:
                ov["height"] = _align_128(int(float(_val("height"))))
            if _val("seconds") is not None:
                ov["seconds"] = max(3, min(10, int(round(float(_val("seconds"))))))
            if _val("seed") is not None:
                ov["seed"] = int(float(_val("seed")))
        elif ntype == "KSampler":
            if _val("steps") is not None:
                ov["steps"] = max(2, min(30, int(float(_val("steps")))))
            if _val("seed") is not None:
                ov["seed"] = int(float(_val("seed")))
            if _val("sampler_name"):
                ov["sampler_name"] = str(_val("sampler_name"))
        elif ntype == "V2VControlPreprocess":
            ov["control"] = str(_val("control", "depth"))
            ov["desub"] = bool(_val("desub", True))
            ov["paw_guard"] = bool(_val("paw_guard", True))
        elif ntype == "LoadVideo":
            ov["keep_audio"] = bool(_val("keep_audio", True))
        elif ntype == "LTX25UnionControlICLoRA":
            ov["engine"] = "v2v"
            if _val("lora_strength") is not None:
                ov["lora_strength"] = float(_val("lora_strength"))
            if _val("width") is not None:
                ov["width"] = int(float(_val("width")))
            if _val("height") is not None:
                ov["height"] = int(float(_val("height")))
            if _val("seed") is not None:
                ov["seed"] = int(float(_val("seed")))
        elif ntype == "LTX25ModelLoader":
            ov["engine"] = "ltx"
            ov["ltx_pipeline"] = str(_val("pipeline", "distilled"))
        elif ntype == "MultiModelRouter":
            ov["engine"] = str(_val("default_engine", "h3"))
            if _val("steps") is not None:
                ov["steps"] = max(2, min(30, int(float(_val("steps")))))
        elif ntype == "ColabFarmExecute":
            if _val("width") is not None:
                ov["width"] = _align_128(int(float(_val("width"))))
            if _val("height") is not None:
                ov["height"] = _align_128(int(float(_val("height"))))
    return ov


def compile_to_comfyui_api(wf: dict[str, Any], detail: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compile the CineForge Lite workflow into a clean, valid ComfyUI API prompt JSON."""
    ov = extract_runtime_overrides(wf)
    proj = (detail or {}).get("project") or {}
    shots = (detail or {}).get("shots") or []
    first_prompt = ov.get("prompt_override") or (shots[0].get("prompt") if shots else "") or proj.get("idea") or "Cinematic film shot"
    seconds = int(ov.get("seconds") or (shots[0].get("seconds") if shots else 5) or 5)
    width = int(ov.get("width") or 1344)
    height = int(ov.get("height") or 768)
    steps = int(ov.get("steps") or 4)
    seed = int(ov.get("seed") or 42)
    engine = ov.get("engine", "h3")

    if engine == "h3":
        frames = int(17 * max(1, round((max(24, seconds * 24) - 5) / 17)) + 5)
        unet = ov.get("unet_name") or "minimax_h3_ref2va_pruned_int8_convrot.safetensors"
        clip = ov.get("clip_name") or "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
        lora = ov.get("lora_name") or "minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors"
        lora_strength = float(ov.get("lora_strength", 1.0))
        is_r2v = "ref2va" in unet
        graph: dict[str, Any] = {
            "1": {"class_type": "UNETLoader", "inputs": {"unet_name": unet, "weight_dtype": "default"}, "_meta": {"title": "MiniMax-H3 Backbone"}},
            "2": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["1", 0], "lora_name": lora, "strength_model": lora_strength}, "_meta": {"title": "H3 4-Step Turbo LoRA"}},
            "3": {"class_type": "CLIPLoader", "inputs": {"clip_name": clip, "type": "minimax_h3"}, "_meta": {"title": "Qwen3-VL Text Encoder"}},
            "4": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_video_vae_int8_convrot.safetensors"}, "_meta": {"title": "H3 Video VAE"}},
            "5": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_audio_vae_fp32.safetensors"}, "_meta": {"title": "H3 Audio VAE"}},
        }
        if is_r2v:
            graph["6"] = {"class_type": "LoadImage", "inputs": {"image": "ref_01.png"}, "_meta": {"title": "Reference Image 1"}}
            graph["10"] = {
                "class_type": "MiniMaxH3ReferenceToVideo",
                "inputs": {
                    "clip": ["3", 0],
                    "vae": ["4", 0],
                    "audio_vae": ["5", 0],
                    "ref_image_0": ["6", 0],
                    "prompt": first_prompt,
                    "width": width,
                    "height": height,
                    "length": frames,
                    "ref_image_size": "match",
                },
                "_meta": {"title": "MiniMax-H3 Ref2VA Conditioning"},
            }
        else:
            graph["10"] = {
                "class_type": "MiniMaxH3ImageToVideo",
                "inputs": {
                    "clip": ["3", 0],
                    "vae": ["4", 0],
                    "prompt": first_prompt,
                    "width": width,
                    "height": height,
                    "length": frames,
                },
                "_meta": {"title": "MiniMax-H3 Text/FL2VA Conditioning"},
            }
        graph["11"] = {
            "class_type": "KSampler",
            "inputs": {
                "model": ["2", 0],
                "positive": ["10", 0],
                "negative": ["10", 0],
                "latent_image": ["10", 1],
                "seed": seed,
                "steps": steps,
                "cfg": 1.0,
                "sampler_name": ov.get("sampler_name") or "res_multistep",
                "scheduler": "simple",
                "denoise": 1.0,
            },
            "_meta": {"title": "H3 Sampler"},
        }
        graph["12"] = {"class_type": "MiniMaxH3SeparateAVLatent", "inputs": {"av_latent": ["11", 0]}, "_meta": {"title": "Split AV Latent"}}
        graph["13"] = {"class_type": "VAEDecode", "inputs": {"samples": ["12", 0], "vae": ["4", 0]}, "_meta": {"title": "Video Decode"}}
        graph["14"] = {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["12", 1], "vae": ["5", 0]}, "_meta": {"title": "Audio Decode"}}
        graph["15"] = {"class_type": "CreateVideo", "inputs": {"images": ["13", 0], "audio": ["14", 0], "fps": 24.0}, "_meta": {"title": "Mux Video + Audio"}}
        graph["16"] = {"class_type": "SaveVideo", "inputs": {"video": ["15", 0], "filename_prefix": f"cineforge_{proj.get('id', 'shot')}", "format": "mp4", "codec": "h264"}, "_meta": {"title": "Save MP4"}}
        return graph

    # Non-H3 (LTX-2.5 / V2V): emit clean ComfyUI-compatible node dictionary
    api_graph: dict[str, Any] = {}
    id_to_num = {n["id"]: str(i + 1) for i, n in enumerate(wf.get("nodes") or [])}
    edge_map: dict[tuple[str, str], tuple[str, int]] = {}
    for e in wf.get("edges") or []:
        edge_map[(e["to"], e["to_port"])] = (id_to_num.get(e["from"], "1"), 0)

    for node in wf.get("nodes") or []:
        if not node.get("enabled", True):
            continue
        nid = id_to_num[node["id"]]
        inputs: dict[str, Any] = {}
        for inp in node.get("inputs") or []:
            link = edge_map.get((node["id"], inp.get("name", "")))
            if link:
                inputs[inp["name"]] = [link[0], link[1]]
        for pk, pv in (node.get("params") or {}).items():
            inputs[pk] = pv.get("value") if isinstance(pv, dict) else pv
        api_graph[nid] = {
            "class_type": node.get("type", "CustomNode"),
            "inputs": inputs,
            "_meta": {"title": node.get("title", node.get("type", nid))},
        }
    return api_graph
