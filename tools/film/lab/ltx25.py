# Colab 端模型测试：LTX-2.5（Lightricks，22B 音视频联合模型，原生同步声音）。
# 由 Colab 单元 exec，需事先定义 B、T、W。HF 令牌从派片服务内存取（/lab/secret），不落盘到项目。
# 权重只放 Colab 的 /content/ltx；本机只收回 mp4 和元数据（/lab/upload/ltx25/...）。
import re
import json, os, shutil, subprocess, threading, time, urllib.parse, urllib.request
from pathlib import Path

B = globals().get("B") or os.environ["FARM_B"]
T = globals().get("T") or os.environ["FARM_T"]
W = globals().get("W") or os.environ.get("FARM_W", "lab")
ROOT = Path("/content/ltx"); REPO = ROOT / "LTX-2"; MODELS = ROOT / "models"; OUT = ROOT / "out"; IN = ROOT / "in"
def worker_config(worker, override=None):
    shard = re.search(r"_(\d+)of(\d+)$", worker)
    index, count = (int(shard[1]), int(shard[2])) if shard else (0, 1)
    if count < 1 or not 0 <= index < count:
        raise ValueError("LTX shard suffix is zero-based: _0of2, _1of2")
    base = worker[:shard.start()] if shard else re.sub(r"_\d+$", "", worker)
    model = override or (base if base.startswith("ltx_") else "ltxv2" if worker.startswith("ltxv2") else "ltx25")
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_-]*", model):
        raise ValueError("Invalid lab model name")
    return model, index, count


MODEL, SHARD_INDEX, SHARD_COUNT = worker_config(W, globals().get("LAB_MODEL"))
FILES = {
    "Lightricks/LTX-2.5": ["diffusion_models/ltx-2.5-22b-distilled-transformer-bf16.safetensors",
                           "text_encoders/gemma4-12b-with-proj-ltx-2.5-bf16.safetensors",
                           "vae/ltx-2.5-video-vae-bf16.safetensors",
                           "vae/ltx-2.5-audio-vae-bf16.safetensors",
                           "latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors"],
    "Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler": ["ltx-2.5-22b-ic-lora-pixel-spatial-upscaler-x2-1.0.safetensors"],
}
ENV = dict(os.environ, HF_HOME="/content/hf", HF_XET_HIGH_PERFORMANCE="1", PYTHONUNBUFFERED="1", MPLBACKEND="Agg")


def url(path, **q):
    q["t"] = T; q["w"] = W
    return f"{B}{path}?{urllib.parse.urlencode(q)}"


def get(path, timeout=120, **q):
    with urllib.request.urlopen(url(path, **q), timeout=timeout) as f:
        return f.read()


def post(path, data, timeout=120):
    for attempt in range(5):
        try:
            r = urllib.request.Request(url(path), data=data, method="POST",
                                       headers={"Content-Type": "application/octet-stream", "User-Agent": "starcore-lab"})
            with urllib.request.urlopen(r, timeout=timeout) as f:
                return f.read()
        except Exception as e:
            if attempt == 4:
                raise
            print("post retry", path, e, flush=True); time.sleep(8 * (attempt + 1))


def log(msg):
    print(msg, flush=True)
    try:
        post("/lab/log", str(msg)[:4000].encode())
    except Exception as e:
        print("log post failed", e, flush=True)


def sh(cmd, logfile=None, cwd=None, env=None):
    with open(logfile or os.devnull, "a") as lf:
        return subprocess.run(["bash", "-lc", cmd], stdout=lf, stderr=subprocess.STDOUT, cwd=cwd, env=env or ENV).returncode


def out(cmd):
    return subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True, env=ENV).stdout.strip()


def tail(f, n=15):
    return out(f"tail -n {n} {f}") if Path(f).exists() else ""


def free_gb(p="/content"):
    return shutil.disk_usage(p).free / 1e9


def install():
    t0 = time.time()
    ROOT.mkdir(parents=True, exist_ok=True)
    lf = str(ROOT / "install.log")
    if out("which uv") == "":
        sh("pip install -q uv", lf)
    if not REPO.exists() and sh(f"git clone --depth 1 https://github.com/Lightricks/LTX-2 {REPO}", lf):
        raise RuntimeError("clone failed\n" + tail(lf))
    if sh("uv sync --extra natten", lf, cwd=REPO):
        raise RuntimeError("uv sync failed\n" + tail(lf, 30))
    log(f"install ok {time.time() - t0:.0f}s: " + out(f"cd {REPO} && uv run python -c 'import torch;print(torch.__version__, torch.cuda.get_device_name())'"))


def download():
    t0 = time.time()
    token = ""
    while not token:                      # 等用户授权后由本机写入派片服务内存
        token = get("/lab/secret").decode().strip()
        if not token:
            log("等待 HF 令牌（LTX-2.5 为授权仓库）…"); time.sleep(60)
    lf = str(ROOT / "download.log")
    env = dict(ENV, HF_TOKEN=token)
    code = "from huggingface_hub import hf_hub_download as d\n"
    for repo, files in FILES.items():
        for f in files:
            line = f"print(d({repo!r}, {f!r}, local_dir={str(MODELS)!r}), flush=True)"
            if "IC-LoRA" in repo:   # DFR 用的细节 LoRA 是单独授权仓库，没授权就只跑快速版
                line = f"try:\n    {line}\nexcept Exception as e:\n    print('optional skipped', e, flush=True)"
            code += line + "\n"
    (ROOT / "_hf_fetch.py").write_text(code)
    rc = sh(f"uv run --no-project --with 'huggingface-hub[hf_xet]' python {ROOT}/_hf_fetch.py", lf, env=env)
    if rc:
        raise RuntimeError(f"download failed rc={rc}\n" + tail(lf, 20))
    log(f"download ok {time.time() - t0:.0f}s size={out(f'du -sh {MODELS} | cut -f1')} free={free_gb():.0f}GB")


def run_job(job, pipeline):
    sid = job["id"]
    IN.mkdir(parents=True, exist_ok=True); OUT.mkdir(parents=True, exist_ok=True)
    img = IN / f"{sid}.png"
    img.write_bytes(get("/lab/kf", p=job["keyframe"]))
    mp4 = OUT / f"{sid}_{pipeline}.mp4"
    lf = str(OUT / f"{sid}_{pipeline}.log")
    m = MODELS
    common = (f"--transformer-path {m}/diffusion_models/ltx-2.5-22b-distilled-transformer-bf16.safetensors "
              f"--text-encoder-path {m}/text_encoders/gemma4-12b-with-proj-ltx-2.5-bf16.safetensors "
              f"--video-vae-path {m}/vae/ltx-2.5-video-vae-bf16.safetensors "
              f"--audio-vae-path {m}/vae/ltx-2.5-audio-vae-bf16.safetensors "
              f"--spatial-upsampler-path {m}/latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors ")
    if pipeline == "dfr":
        common += f"--detailing-lora {m}/ltx-2.5-22b-ic-lora-pixel-spatial-upscaler-x2-1.0.safetensors "
    module = "ltx_pipelines.dfr_pipeline" if pipeline == "dfr" else "ltx_pipelines.distilled"
    pf = IN / f"{sid}.txt"
    pf.write_text(job["prompt"])
    frames = int(job["seconds"]) * 24 + 1
    cmd = (f"uv run python -m {module} {common} --width 1344 --height 768 --num-frames {frames} --frame-rate 24 "
           f"--image {img} 0 1.0 --seed {job.get('seed', 42)} --output-path {mp4} --prompt \"$(cat {pf})\"")
    t0 = time.time()
    rc = sh(cmd, lf, cwd=REPO)
    wall = time.time() - t0
    if rc or not mp4.exists():
        log(f"FAIL {sid} {pipeline} rc={rc} {wall:.0f}s\n" + tail(lf, 25))
        post(f"/lab/upload/{MODEL}/{sid}_{pipeline}.log", Path(lf).read_bytes())
        return False
    post(f"/lab/upload/{MODEL}/{sid}_{pipeline}.mp4", mp4.read_bytes(), timeout=600)
    post(f"/lab/upload/{MODEL}/{sid}_{pipeline}.log", Path(lf).read_bytes())
    log(f"done {sid} {pipeline} wall={wall:.0f}s")
    return True


def main():
    env = out("nvidia-smi --query-gpu=name,memory.total --format=csv,noheader; free -g | head -2; df -h /content | tail -1")
    log(f"lab start {MODEL}\n{env}")
    errs = []

    def guard(f):
        try:
            f()
        except Exception as e:
            errs.append(e); log(f"ERROR {f.__name__}: {e}")
    th = [threading.Thread(target=guard, args=(f,)) for f in (install, download)]
    for t in th: t.start()
    while any(t.is_alive() for t in th):
        time.sleep(60)
        log(f"... free={free_gb():.0f}GB models={out(f'du -sh {MODELS} 2>/dev/null | cut -f1')} install_tail={tail(str(ROOT / 'install.log'), 1)[-120:]}")
    if errs:
        return
    jobs = json.loads(get("/lab/jobs", m=MODEL))
    jobs = [job for index, job in enumerate(jobs) if index % SHARD_COUNT == SHARD_INDEX]
    dfr_ok = (MODELS / "ltx-2.5-22b-ic-lora-pixel-spatial-upscaler-x2-1.0.safetensors").exists()
    pipes = [x for x in os.environ.get("LTX_PIPES", "distilled" if (MODEL == "ltxv2" or MODEL.startswith("ltx_")) else "dfr").split(",") if x != "dfr" or dfr_ok]
    pipes = globals().get("PIPES") or pipes
    for pipeline in pipes:   # 先快速版跑完 3 镜，再跑正片质量版
        for job in jobs:
            try:   # 任务单会被本机裁剪（别的机器已拍完的镜头被删掉）：每镜开拍前重读，已不在单上的跳过
                if job["id"] not in {j["id"] for j in json.loads(get("/lab/jobs", m=MODEL))}:
                    continue
            except Exception as e:
                print("jobs refresh failed", e, flush=True)
            run_job(job, pipeline)
    log("lab finished")


main()
