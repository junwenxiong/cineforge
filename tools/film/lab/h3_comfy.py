# Open-source MiniMax-H3 Colab worker (no DramaPie Box required).
# Runs headless ComfyUI (Comfy-Org/ComfyUI) with official Comfy-Org/MiniMax-H3
# quantized weights + 4-step Turbo LoRAs, supporting both:
#   1. Farm mode (B, T, W defined): claims jobs from farm_server.py (/claim -> /result/{id})
#      and mirrors finished clips to /content/cineforge_outputs/ for direct Colab download.
#   2. Standalone mode (STANDALONE_PROMPT defined, no B/T): generates directly on Colab
#      and writes the MP4 to /content/cineforge_outputs/.
import json
import os
import random
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

B = (globals().get("B") or os.environ.get("FARM_B") or "").rstrip("/")
T = globals().get("T") or os.environ.get("FARM_T") or ""
W = globals().get("W") or os.environ.get("FARM_W") or "h3_open_01"
FILMS = globals().get("FILMS") if "FILMS" in globals() else os.environ.get("FILM", "")
IDLE_SHUTDOWN_MIN = int(globals().get("IDLE_SHUTDOWN_MIN") or os.environ.get("CINEFORGE_IDLE_MIN") or 15)
AUTO_UNASSIGN = bool(globals().get("AUTO_UNASSIGN") or os.environ.get("CINEFORGE_AUTO_UNASSIGN") == "1")
H3_STEPS = int(globals().get("H3_STEPS") or os.environ.get("CINEFORGE_H3_STEPS") or 4)
H3_PRECISION = str(globals().get("H3_PRECISION") or os.environ.get("CINEFORGE_H3_PRECISION") or "auto").lower()

ROOT = Path("/content/comfy_h3")
COMFY = ROOT / "ComfyUI"
VENV = ROOT / "venv"
OUT_SHARED = Path("/content/cineforge_outputs")
COMFY_PORT = int(os.environ.get("CINEFORGE_COMFY_PORT") or 8188)
COMFY_URL = f"http://127.0.0.1:{COMFY_PORT}"
COMFY_GIT = "https://github.com/Comfy-Org/ComfyUI.git"
HF_REPO = "Comfy-Org/MiniMax-H3"

# Official Comfy-Org/MiniMax-H3 weight paths mapped into ComfyUI/models/
WEIGHT_SETS = {
    "int8": {
        "ref_unet": ("diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors",
                     "diffusion_models/minimax_h3_ref2va_int8_convrot.safetensors"),
        "fl_unet": ("diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors",
                    "diffusion_models/minimax_h3_fl2va_int8_convrot.safetensors"),
        "clip": ("text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
                 "text_encoders/qwen3vl_32b_minimax_h3_int8_convrot.safetensors"),
        "video_vae": ("vae/minimax_h3_video_vae_int8_convrot.safetensors",),
        "audio_vae": ("vae/minimax_h3_audio_vae_fp32.safetensors",),
        "ref_lora": ("loras/minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors",),
        "fl_lora": ("loras/minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors",),
    },
    "fp8": {
        "ref_unet": ("diffusion_models/minimax_h3_ref2va_pruned_fp8_scaled.safetensors",
                     "diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors"),
        "fl_unet": ("diffusion_models/minimax_h3_fl2va_pruned_fp8_scaled.safetensors",
                    "diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors"),
        "clip": ("text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
                 "text_encoders/qwen3vl_32b_minimax_h3_int8_convrot.safetensors"),
        "video_vae": ("vae/minimax_h3_video_vae_int8_convrot.safetensors",),
        "audio_vae": ("vae/minimax_h3_audio_vae_fp32.safetensors",),
        "ref_lora": ("loras/minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors",),
        "fl_lora": ("loras/minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors",),
    },
}

ENV = dict(
    os.environ,
    HF_HOME=os.environ.get("HF_HOME") or "/content/hf",
    HF_XET_HIGH_PERFORMANCE="1",
    PYTHONUNBUFFERED="1",
    MPLBACKEND="Agg",
)

STATE = {"state": "boot", "done": 0, "failed": 0, "current": [], "gpu": "", "backend": "h3-open-comfyui"}
_RESOLVED = {}
_COMFY_PROC = None


def farm_url(path, **q):
    q["t"] = T
    q["w"] = W
    return f"{B}{path}?{urllib.parse.urlencode(q)}"


def farm_req(path, data=None, timeout=120, **q):
    r = urllib.request.Request(
        farm_url(path, **q),
        data=data,
        method="POST" if data is not None else "GET",
        headers={"Content-Type": "application/octet-stream", "User-Agent": "cineforge-h3-open"},
    )
    with urllib.request.urlopen(r, timeout=timeout) as f:
        return f.status, f.read()


def log(msg):
    line = f"[H3-Open] {msg}"
    print(line, flush=True)
    if B and T:
        try:
            farm_req("/lab/log", line[:4000].encode("utf-8"), timeout=20)
        except Exception:
            pass


def sh(cmd, logfile=None, cwd=None, env=None):
    with open(logfile or os.devnull, "a", encoding="utf-8") as lf:
        return subprocess.run(
            ["bash", "-lc", cmd],
            stdout=lf,
            stderr=subprocess.STDOUT,
            cwd=cwd,
            env=env or ENV,
        ).returncode


def out(cmd):
    return subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True, env=ENV).stdout.strip()


def tail(path, n=25):
    p = Path(path)
    if not p.exists():
        return ""
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-n:])


def get_hf_token():
    tok = os.environ.get("HF_TOKEN") or globals().get("HF_TOKEN") or ""
    if not tok and B and T:
        try:
            _, body = farm_req("/lab/secret", timeout=30)
            tok = body.decode("utf-8", "replace").strip()
        except Exception:
            pass
    return tok.strip()


def detect_gpu_vram_gb():
    info = out("nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits")
    if not info:
        return "CPU/Unknown", 0.0
    parts = [p.strip() for p in info.splitlines()[0].split(",")]
    name = parts[0]
    try:
        vram_gb = float(parts[1]) / 1024.0
    except (IndexError, ValueError):
        vram_gb = 0.0
    return name, vram_gb


def choose_precision(vram_gb):
    if H3_PRECISION in WEIGHT_SETS:
        return H3_PRECISION
    return "fp8" if vram_gb < 45 else "int8"


def install_comfy():
    t0 = time.time()
    ROOT.mkdir(parents=True, exist_ok=True)
    OUT_SHARED.mkdir(parents=True, exist_ok=True)
    lf = str(ROOT / "install.log")
    if out("which uv") == "":
        sh("pip install -q uv", lf)
    if not COMFY.exists():
        log("Cloning Comfy-Org/ComfyUI ...")
        if sh(f"git clone --depth 1 {COMFY_GIT} {COMFY}", lf):
            raise RuntimeError("ComfyUI clone failed:\n" + tail(lf))
    py = VENV / "bin" / "python"
    if not (ROOT / ".comfy_ok").exists():
        if not py.exists():
            if sh(f"uv venv -p 3.12 {VENV}", lf):
                sh(f"python3 -m venv {VENV}", lf)
        log("Installing ComfyUI + Hugging Face dependencies ...")
        if sh(f"uv pip install -p {py} torch torchvision torchaudio --extra-index-url https://download.pytorch.org/whl/cu124", lf):
            sh(f"{py} -m pip install -q torch torchvision torchaudio", lf)
        if sh(f"uv pip install -p {py} -r {COMFY}/requirements.txt 'huggingface-hub[hf_xet]' av imageio-ffmpeg", lf):
            if sh(f"{py} -m pip install -q -r {COMFY}/requirements.txt 'huggingface-hub[hf_xet]' av imageio-ffmpeg", lf):
                raise RuntimeError("ComfyUI dependency install failed:\n" + tail(lf, 35))
        (ROOT / ".comfy_ok").touch()
    ver = out(f"{py} -c 'import torch; print(torch.__version__, torch.cuda.is_available())'")
    log(f"ComfyUI ready in {time.time() - t0:.0f}s ({ver})")


def download_weights(precision, need_fl=False):
    t0 = time.time()
    lf = str(ROOT / "download.log")
    py = VENV / "bin" / "python"
    token = get_hf_token()
    env = dict(ENV, HF_TOKEN=token) if token else dict(ENV)
    models_root = COMFY / "models"
    spec = WEIGHT_SETS[precision]
    keys = ["ref_unet", "clip", "video_vae", "audio_vae", "ref_lora"]
    if need_fl:
        keys += ["fl_unet", "fl_lora"]

    fetch_script = ROOT / "_hf_fetch_h3.py"
    fetch_script.write_text(
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "from huggingface_hub import hf_hub_download\n"
        "repo = sys.argv[1]\n"
        "models_root = Path(sys.argv[2])\n"
        "spec = json.loads(sys.argv[3])\n"
        "resolved = {}\n"
        "for key, candidates in spec.items():\n"
        "    last_err = None\n"
        "    for rel in candidates:\n"
        "        try:\n"
        "            p = hf_hub_download(repo_id=repo, filename=rel, local_dir=str(models_root))\n"
        "            resolved[key] = Path(rel).name\n"
        "            print(f'OK {key} -> {p}', flush=True)\n"
        "            break\n"
        "        except Exception as exc:\n"
        "            last_err = exc\n"
        "            print(f'TRY_NEXT {key} {rel}: {exc}', flush=True)\n"
        "    if key not in resolved:\n"
        "        raise RuntimeError(f'Failed to download {key}: {last_err}')\n"
        "Path(sys.argv[4]).write_text(json.dumps(resolved, indent=2), encoding='utf-8')\n",
        encoding="utf-8",
    )
    wanted = {k: list(spec[k]) for k in keys}
    res_file = ROOT / "resolved_weights.json"
    log(f"Downloading official {HF_REPO} ({precision}) weights into {models_root} ...")
    cmd = f"{py} {fetch_script} {HF_REPO!r} {str(models_root)!r} {json.dumps(wanted)!r} {str(res_file)!r}"
    rc = sh(cmd, lf, env=env)
    if rc != 0 or not res_file.is_file():
        raise RuntimeError("MiniMax-H3 weight download failed:\n" + tail(lf, 30))
    _RESOLVED.update(json.loads(res_file.read_text(encoding="utf-8")))
    log(f"Weights ready in {time.time() - t0:.0f}s: {_RESOLVED}")


def comfy_get(path, timeout=30):
    with urllib.request.urlopen(f"{COMFY_URL}{path}", timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def comfy_post(path, payload, timeout=60):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{COMFY_URL}{path}",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def start_comfy_server():
    global _COMFY_PROC
    try:
        comfy_get("/system_stats", timeout=3)
        return
    except Exception:
        pass
    py = VENV / "bin" / "python"
    lf = open(ROOT / "comfy_server.log", "a", encoding="utf-8")
    extra_flags = ["--listen", "127.0.0.1", "--port", str(COMFY_PORT), "--disable-auto-launch"]
    _, vram_gb = detect_gpu_vram_gb()
    if vram_gb and vram_gb < 48:
        extra_flags.append("--lowvram")
    _COMFY_PROC = subprocess.Popen(
        [str(py), str(COMFY / "main.py"), *extra_flags],
        cwd=str(COMFY),
        stdout=lf,
        stderr=subprocess.STDOUT,
        env=ENV,
    )
    for _ in range(120):
        if _COMFY_PROC.poll() is not None:
            raise RuntimeError("ComfyUI server exited early:\n" + tail(ROOT / "comfy_server.log", 40))
        try:
            comfy_get("/system_stats", timeout=3)
            log(f"ComfyUI headless API listening on {COMFY_URL}")
            return
        except Exception:
            time.sleep(1.5)
    raise RuntimeError("ComfyUI server timed out waiting to start:\n" + tail(ROOT / "comfy_server.log", 40))


def _align_h3_frames(seconds):
    # MiniMax-H3 native grid: 17k + 5 frames at 24 fps (124 ~= 5.2s, 141 ~= 5.9s)
    want = max(24, int(round(float(seconds) * 24)))
    k = max(1, round((want - 5) / 17))
    return int(17 * k + 5)


def _pick_clip_type(obj_info):
    try:
        opts = obj_info["CLIPLoader"]["input"]["required"]["type"][0]
        for cand in ("minimax_h3", "minimax", "qwen_image", "luma"):
            if cand in opts:
                return cand
    except Exception:
        pass
    return "minimax_h3"


def _find_separate_av_node(obj_info):
    for name in ("MiniMaxH3SeparateAVLatent", "LTXVSeparateAVLatent", "SeparateAVLatent"):
        if name in obj_info:
            return name
    for name in obj_info:
        if "SeparateAV" in name:
            return name
    return None


def _find_audio_decode_node(obj_info):
    for name in ("VAEDecodeAudio", "MiniMaxH3AudioDecode", "LTXVAudioVAEDecode"):
        if name in obj_info:
            return name
    return None


def build_h3_workflow(prompt_text, ref_filenames, seconds=5, width=1344, height=768, seed=None, steps=4, prefix="cf_h3", lora_strength=1.0, sampler_name=None):
    """Build a ComfyUI API prompt graph using live /object_info inspection for native MiniMax-H3 nodes."""
    obj_info = comfy_get("/object_info", timeout=30)
    use_ref = bool(ref_filenames) and "MiniMaxH3ReferenceToVideo" in obj_info
    if not use_ref and "MiniMaxH3ImageToVideo" not in obj_info and "MiniMaxH3ReferenceToVideo" not in obj_info:
        raise RuntimeError(
            "This ComfyUI build is missing native MiniMax H3 nodes (MiniMaxH3ReferenceToVideo / MiniMaxH3ImageToVideo). "
            "Please update ComfyUI."
        )

    seed = int(seed if seed is not None else random.randint(1, 2**31 - 1))
    length = _align_h3_frames(seconds)
    clip_type = _pick_clip_type(obj_info)
    unet_name = _RESOLVED["ref_unet"] if use_ref else _RESOLVED.get("fl_unet", _RESOLVED["ref_unet"])
    lora_name = _RESOLVED["ref_lora"] if use_ref else _RESOLVED.get("fl_lora", _RESOLVED["ref_lora"])

    graph = {}
    graph["1"] = {
        "class_type": "UNETLoader",
        "inputs": {"unet_name": unet_name, "weight_dtype": "default"},
    }
    graph["2"] = {
        "class_type": "LoraLoaderModelOnly",
        "inputs": {"model": ["1", 0], "lora_name": lora_name, "strength_model": float(lora_strength)},
    }
    graph["3"] = {
        "class_type": "CLIPLoader",
        "inputs": {"clip_name": _RESOLVED["clip"], "type": clip_type},
    }
    graph["4"] = {
        "class_type": "VAELoader",
        "inputs": {"vae_name": _RESOLVED["video_vae"]},
    }
    graph["5"] = {
        "class_type": "VAELoader",
        "inputs": {"vae_name": _RESOLVED["audio_vae"]},
    }

    # Optional sigma shift node if registered
    model_ref = ["2", 0]
    if "MiniMaxH3SigmaShift" in obj_info:
        shift_schema = obj_info["MiniMaxH3SigmaShift"].get("input", {})
        shift_inputs = {"model": model_ref}
        all_keys = {**shift_schema.get("required", {}), **shift_schema.get("optional", {})}
        if "video_shift" in all_keys:
            shift_inputs["video_shift"] = 12.0
        if "audio_shift" in all_keys:
            shift_inputs["audio_shift"] = 3.0
        if "shift" in all_keys:
            shift_inputs["shift"] = 12.0
        graph["6"] = {"class_type": "MiniMaxH3SigmaShift", "inputs": shift_inputs}
        model_ref = ["6", 0]

    # Load reference images
    img_node_refs = []
    for idx, fname in enumerate(ref_filenames[:5]):
        nid = str(20 + idx)
        graph[nid] = {"class_type": "LoadImage", "inputs": {"image": fname}}
        img_node_refs.append([nid, 0])

    # Conditioning + AV Latent node
    if use_ref or "MiniMaxH3ImageToVideo" not in obj_info:
        cond_cls = "MiniMaxH3ReferenceToVideo"
        schema = obj_info[cond_cls].get("input", {})
        all_in = {**schema.get("required", {}), **schema.get("optional", {})}
        c_inputs = {
            "clip": ["3", 0],
            "vae": ["4", 0],
            "prompt": prompt_text,
            "width": int(width),
            "height": int(height),
            "length": int(length),
        }
        if "audio_vae" in all_in:
            c_inputs["audio_vae"] = ["5", 0]
        if "ref_image_size" in all_in:
            c_inputs["ref_image_size"] = "match"
        for idx, iref in enumerate(img_node_refs):
            for key_pat in (f"ref_image_{idx}", f"ref_image_{idx + 1}", f"image_{idx + 1}"):
                if key_pat in all_in or idx == 0:
                    c_inputs[key_pat if key_pat in all_in else f"ref_image_{idx}"] = iref
                    break
        graph["10"] = {"class_type": cond_cls, "inputs": c_inputs}
    else:
        cond_cls = "MiniMaxH3ImageToVideo"
        graph["10"] = {
            "class_type": cond_cls,
            "inputs": {
                "clip": ["3", 0],
                "vae": ["4", 0],
                "prompt": prompt_text,
                "width": int(width),
                "height": int(height),
                "length": int(length),
            },
        }

    # Guidance-distilled H3: cfg=1.0, 4 steps with Turbo LoRA
    graph["11"] = {
        "class_type": "KSampler",
        "inputs": {
            "model": model_ref,
            "positive": ["10", 0],
            "negative": ["10", 0],
            "latent_image": ["10", 1],
            "seed": seed,
            "steps": max(2, int(steps)),
            "cfg": 1.0,
            "sampler_name": sampler_name or ("res_multistep" if "res_multistep" in str(obj_info.get("KSampler", "")) else "euler"),
            "scheduler": "simple",
            "denoise": 1.0,
        },
    }

    sep_cls = _find_separate_av_node(obj_info)
    aud_cls = _find_audio_decode_node(obj_info)
    if sep_cls:
        graph["12"] = {"class_type": sep_cls, "inputs": {"av_latent": ["11", 0]}}
        # Handle input key naming variation ("av_latent" vs "samples")
        sep_req = obj_info[sep_cls].get("input", {}).get("required", {})
        if "samples" in sep_req and "av_latent" not in sep_req:
            graph["12"]["inputs"] = {"samples": ["11", 0]}
        vid_latent_ref = ["12", 0]
        aud_latent_ref = ["12", 1]
    else:
        vid_latent_ref = ["11", 0]
        aud_latent_ref = None

    graph["13"] = {"class_type": "VAEDecode", "inputs": {"samples": vid_latent_ref, "vae": ["4", 0]}}

    audio_ref = None
    if aud_latent_ref and aud_cls:
        aud_req = obj_info[aud_cls].get("input", {}).get("required", {})
        sample_key = "samples" if "samples" in aud_req else next(iter(aud_req.keys()), "samples")
        vae_key = "vae" if "vae" in aud_req else "audio_vae"
        graph["14"] = {"class_type": aud_cls, "inputs": {sample_key: aud_latent_ref, vae_key: ["5", 0]}}
        audio_ref = ["14", 0]

    if "CreateVideo" in obj_info and "SaveVideo" in obj_info:
        cv_inputs = {"images": ["13", 0], "fps": 24.0}
        if audio_ref:
            cv_inputs["audio"] = audio_ref
        graph["15"] = {"class_type": "CreateVideo", "inputs": cv_inputs}
        graph["16"] = {
            "class_type": "SaveVideo",
            "inputs": {"video": ["15", 0], "filename_prefix": prefix, "format": "mp4", "codec": "h264"},
        }
    else:
        # Fallback: SaveAnimatedWEBP / VHS_VideoCombine if CreateVideo absent
        graph["16"] = {
            "class_type": "SaveImage",
            "inputs": {"images": ["13", 0], "filename_prefix": prefix},
        }
    return graph, seed, length


def run_comfy_prompt(graph, out_mp4: Path, timeout=900):
    resp = comfy_post("/prompt", {"prompt": graph, "client_id": W})
    prompt_id = resp.get("prompt_id")
    if not prompt_id:
        raise RuntimeError(f"ComfyUI rejected workflow: {resp}")
    t0 = time.time()
    while time.time() - t0 < timeout:
        hist = comfy_get(f"/history/{prompt_id}", timeout=30)
        if prompt_id in hist:
            entry = hist[prompt_id]
            status = entry.get("status") or {}
            if status.get("status_str") == "error":
                raise RuntimeError(f"ComfyUI execution error: {json.dumps(status, ensure_ascii=False)[:600]}")
            outputs = entry.get("outputs") or {}
            for node_out in outputs.values():
                for bucket in ("videos", "gifs", "images"):
                    for item in node_out.get(bucket) or []:
                        fname = item.get("filename") or ""
                        sub = item.get("subfolder") or ""
                        if fname.lower().endswith(".mp4"):
                            src = COMFY / "output" / sub / fname if sub else COMFY / "output" / fname
                            if src.is_file():
                                out_mp4.parent.mkdir(parents=True, exist_ok=True)
                                shutil.copy2(src, out_mp4)
                                return time.time() - t0
            raise RuntimeError(f"ComfyUI finished without producing an MP4: {outputs}")
        time.sleep(2.0)
    raise RuntimeError(f"ComfyUI timed out after {timeout}s")


def generate_shot(sid, prompt_text, ref_paths, seconds=5, width=1344, height=768, seed=None, steps=None, lora_strength=1.0, sampler_name=None):
    comfy_in = COMFY / "input"
    comfy_in.mkdir(parents=True, exist_ok=True)
    ref_names = []
    for idx, p in enumerate(ref_paths[:5]):
        src = Path(p)
        if src.is_file():
            dst_name = f"{sid}_ref{idx}{src.suffix.lower() or '.png'}"
            shutil.copy2(src, comfy_in / dst_name)
            ref_names.append(dst_name)

    use_steps = int(steps) if steps is not None else H3_STEPS
    graph, used_seed, frames = build_h3_workflow(
        prompt_text=prompt_text,
        ref_filenames=ref_names,
        seconds=seconds,
        width=width,
        height=height,
        seed=seed,
        steps=use_steps,
        prefix=f"cf_{sid}",
        lora_strength=lora_strength,
        sampler_name=sampler_name,
    )
    out_mp4 = OUT_SHARED / f"{sid}.mp4"
    wall = run_comfy_prompt(graph, out_mp4)
    return out_mp4, {
        "wall_sec": round(wall, 1),
        "seed": used_seed,
        "frames": frames,
        "size": [width, height],
        "steps": use_steps,
        "engine": "h3-open-comfyui",
        "lora": _RESOLVED.get("ref_lora"),
    }


def heartbeat_loop():
    while True:
        try:
            farm_req("/heartbeat", json.dumps(STATE).encode("utf-8"), timeout=20)
        except Exception:
            pass
        time.sleep(30)


def download_job_refs(job):
    sid = job["id"]
    cache_dir = ROOT / "ref_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for r in job.get("refs") or []:
        cache = cache_dir / (r["url"].replace("/", "_") + "_" + r["name"])
        for attempt in range(5):
            try:
                if not cache.exists():
                    _, data = farm_req(r["url"], timeout=120)
                    tmp = cache.with_suffix(".part")
                    tmp.write_bytes(data)
                    tmp.replace(cache)
                paths.append(cache)
                break
            except Exception as exc:
                if attempt == 4:
                    raise
                log(f"ref retry {r['name']}: {exc}")
                time.sleep(4 * (attempt + 1))
    return paths


def main():
    gpu_name, vram_gb = detect_gpu_vram_gb()
    STATE["gpu"] = f"{gpu_name}, {vram_gb:.1f} GB"
    log(f"GPU: {STATE['gpu']}")
    if 0 < vram_gb < 20:
        log("WARNING: GPU VRAM < 20 GB (e.g. T4 15 GB) is too small for MiniMax-H3. Recommend Colab A100 / H100 / G4.")

    precision = choose_precision(vram_gb)
    standalone_prompt = globals().get("STANDALONE_PROMPT") or os.environ.get("CINEFORGE_STANDALONE_PROMPT") or ""
    standalone_refs = list(globals().get("STANDALONE_REFS") or [])
    standalone_sec = int(globals().get("STANDALONE_SECONDS") or 5)
    need_fl = bool(standalone_prompt and not standalone_refs)

    install_comfy()
    download_weights(precision, need_fl=need_fl)
    start_comfy_server()

    if standalone_prompt and (not B or not T):
        sid = globals().get("STANDALONE_ID") or f"h3_standalone_{int(time.time())}"
        log(f"Running standalone MiniMax-H3 shot: {sid} ({standalone_sec}s, {H3_STEPS} steps) ...")
        out_mp4, meta = generate_shot(sid, standalone_prompt, standalone_refs, seconds=standalone_sec)
        log(f"DONE standalone shot -> {out_mp4} ({meta})")
        return

    if not B or not T:
        raise RuntimeError("Missing FARM_URL (B) / FARM_TOKEN (T). Set them for Farm mode, or set STANDALONE_PROMPT.")

    if not globals().get("_H3_OPEN_HB"):
        globals()["_H3_OPEN_HB"] = True
        threading.Thread(target=heartbeat_loop, daemon=True).start()

    STATE["state"] = "running"
    empty_since = None
    idle_limit = max(60, IDLE_SHUTDOWN_MIN * 60)

    while True:
        try:
            code, body = farm_req("/claim", b"", timeout=60, **({"films": FILMS} if FILMS else {}))
        except Exception as exc:
            log(f"claim error: {exc}")
            time.sleep(10)
            continue

        if code == 200 and body:
            empty_since = None
            job = json.loads(body.decode("utf-8"))
            sid = job["id"]
            STATE["state"] = "running"
            STATE["current"] = [sid]
            log(f"Claimed {sid} ({job.get('seconds', 5)}s)")
            try:
                ref_paths = download_job_refs(job)
                out_mp4, meta = generate_shot(
                    sid=sid,
                    prompt_text=job["prompt"],
                    ref_paths=ref_paths,
                    seconds=int(job.get("seconds") or 5),
                    width=int(job.get("width") or 1344),
                    height=int(job.get("height") or 768),
                    seed=job.get("seed"),
                    steps=job.get("steps"),
                    lora_strength=float(job.get("lora_strength", 1.0)),
                    sampler_name=job.get("sampler_name"),
                )
                mp4_bytes = out_mp4.read_bytes()
                for attempt in range(4):
                    try:
                        farm_req(f"/result/{sid}", mp4_bytes, timeout=300, meta=json.dumps(meta))
                        break
                    except Exception as exc:
                        if attempt == 3:
                            raise
                        log(f"upload retry {sid}: {exc}")
                        time.sleep(8 * (attempt + 1))
                STATE["done"] += 1
                log(f"Uploaded {sid} ({len(mp4_bytes) / 1e6:.1f} MB, {meta['wall_sec']}s) -> also saved at {out_mp4}")
            except Exception as exc:
                STATE["failed"] += 1
                log(f"FAILED {sid}: {exc}")
                try:
                    farm_req(f"/fail/{sid}", str(exc)[:1000].encode("utf-8"), timeout=30)
                except Exception:
                    pass
            finally:
                STATE["current"] = []
            continue

        empty_since = empty_since or time.time()
        STATE["state"] = "idle"
        if time.time() - empty_since > idle_limit:
            log("Idle limit reached; exiting.")
            STATE["state"] = "finished"
            try:
                farm_req("/heartbeat", json.dumps(STATE).encode("utf-8"), timeout=20)
            except Exception:
                pass
            if AUTO_UNASSIGN:
                try:
                    from google.colab import runtime  # type: ignore
                    runtime.unassign()
                except Exception as exc:
                    log(f"unassign skipped: {exc}")
            return
        time.sleep(6)


main()
