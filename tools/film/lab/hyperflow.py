# Colab 端模型测试：HyperFlow H3 Flash（Video Rebirth 对 MiniMax-H3 的 14B 少步蒸馏，Ref2VA，带同步音频）。
# 由 Colab 单元 exec，需事先定义 B（派片地址）、T（令牌）、W（机器名）。
# 权重和环境只放 Colab 的 /content；本机只收回 mp4、元数据和日志（/lab/upload/hyperflow/...）。
# 推理走官方 Python API（hyperflow_h3_flash.load_pipeline），权重只加载一次，同一进程内跑完全部镜头的 6 步和 8 步。
import fnmatch, json, os, shutil, subprocess, threading, time, urllib.parse, urllib.request
from pathlib import Path

B = globals().get("B") or os.environ["FARM_B"]
T = globals().get("T") or os.environ["FARM_T"]
W = globals().get("W") or os.environ.get("FARM_W", "lab")
ROOT = Path("/content/hyperflow"); REPO = ROOT / "repo"; VENV = ROOT / "venv"; OUT = ROOT / "out"; IN = ROOT / "in"
HF_HOME = "/content/hf"
MODEL = "hyperflow"
CODE_REPO, CODE_REV = "https://github.com/Video-Rebirth/hyperflow-h3-flash", "dc67ea77de7795a570a41f98dc97e48f66a5828b"
HF_REPO, HF_REV = "VideoRebirthAI/hyperflow-h3-flash", "6834923e1a9ca4d15a2349a622b6677bea1404cb"
HF_PATTERNS = ["ref2va_int8_convrot/*", "LICENSE", "NOTICE"]          # 只要 Python 用的 ref2va INT8 分片（16.3GB）
# 文本编码器/VAE 等取自 MiniMax-H3；与 pika_flex 同一版本（这些文件与 main 逐字节相同），同机可复用缓存。
# 不下载 transformer/ transformer_ref/ FL2VA/ Ref2VA/（各 66–144GB）。
BASE_REPO, BASE_REV = "MiniMaxAI/MiniMax-H3", "42ed227ee7df40d41602854ae760620d6eb651fe"
BASE_PATTERNS = ["text_encoder/*", "tokenizer/*", "processor/*", "vae/*", "audio_vae/*", "scheduler/*",
                 "audio_scheduler/*", "model_index.json", "modular_model_index.json", "LICENSE"]
TORCH = "torch==2.13.0+cu129 torchvision==0.28.0+cu129"               # 与 pika_flex 相同，已在 RTX PRO 6000 上验证
TORCH_INDEX = "https://download.pytorch.org/whl/cu129"
ENV = dict(os.environ, HF_HOME=HF_HOME, HF_XET_HIGH_PERFORMANCE="1", PYTHONUNBUFFERED="1", MPLBACKEND="Agg",
           PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True")


def url(path, **q):
    q["t"] = T; q["w"] = W
    return f"{B}{path}?{urllib.parse.urlencode(q)}"


def post(path, data, timeout=120):
    r = urllib.request.Request(url(path), data=data, method="POST",
                               headers={"Content-Type": "application/octet-stream", "User-Agent": "starcore-lab"})
    with urllib.request.urlopen(r, timeout=timeout) as f:
        return f.read()


def get(path, timeout=60, **q):
    with urllib.request.urlopen(url(path, **q), timeout=timeout) as f:
        return f.read()


def log(msg):
    print(msg, flush=True)
    try:
        post("/lab/log", str(msg)[:4000].encode())
    except Exception as e:
        print("log post failed", e, flush=True)


def sh(cmd, logfile=None, cwd=None):
    with open(logfile or os.devnull, "a") as lf:
        return subprocess.run(["bash", "-lc", cmd], stdout=lf, stderr=subprocess.STDOUT, cwd=cwd, env=ENV).returncode


def out(cmd):
    return subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True, env=ENV).stdout.strip()


def tail(f, n=15):
    return out(f"tail -n {n} {f}") if Path(f).exists() else ""


def free_gb(p="/content"):
    return shutil.disk_usage(p).free / 1e9


def snapshot(repo, rev):
    return Path(HF_HOME) / "hub" / f"models--{repo.replace('/', '--')}" / "snapshots" / rev


def need_gb():
    """还需下载的 GB：按 Hub 文件清单逐个比对本地缓存 blob（同机已有 pika_flex 缓存时只差 16GB）。"""
    total = 0
    for repo, rev, pats in ((HF_REPO, HF_REV, HF_PATTERNS), (BASE_REPO, BASE_REV, BASE_PATTERNS)):
        with urllib.request.urlopen(f"https://huggingface.co/api/models/{repo}/revision/{rev}?blobs=true", timeout=60) as f:
            info = json.loads(f.read())
        blobs = snapshot(repo, rev).parent.parent / "blobs"
        for s in info["siblings"]:
            if any(fnmatch.fnmatch(s["rfilename"], p) for p in pats):
                key = (s.get("lfs") or {}).get("sha256") or s.get("blobId")
                if not (blobs / key).exists():
                    total += s.get("size") or 0
    return total / 1e9


def install():
    t0 = time.time()
    ROOT.mkdir(parents=True, exist_ok=True)
    lf = str(ROOT / "install.log")
    if out("which uv") == "":
        sh("pip install -q uv", lf)
    if not REPO.exists():
        if sh(f"git clone --depth 1 {CODE_REPO} {REPO} && cd {REPO} && "
              f"(git checkout {CODE_REV} || (git fetch --depth 1 origin {CODE_REV} && git checkout {CODE_REV}))", lf):
            raise RuntimeError("clone failed\n" + tail(lf))
    if not (VENV / "bin/hyperflow-h3-flash").exists():
        # Hopper 才用得上 FlashAttention-3（kernels）；Blackwell/Ampere 走 SDPA，不装多余依赖
        extra = "[hopper]" if out("nvidia-smi --query-gpu=compute_cap --format=csv,noheader | head -1").startswith("9.") else ""
        steps = [f"uv venv -p 3.12 {VENV}",
                 f"uv pip install -p {VENV}/bin/python --extra-index-url {TORCH_INDEX} --index-strategy unsafe-best-match "
                 f"{TORCH} -e '.{extra}'"]
        for s in steps:
            if sh(s, lf, cwd=REPO):
                raise RuntimeError(f"install step failed: {s}\n" + tail(lf, 30))
    log(f"install ok {time.time() - t0:.0f}s: " + out(
        f"{VENV}/bin/python -c 'import torch,triton,diffusers,transformers;"
        f"print(torch.__version__, triton.__version__, diffusers.__version__, transformers.__version__, torch.cuda.get_device_name())'"))


def download():
    t0 = time.time()
    lf = str(ROOT / "download.log")
    code = (f"from huggingface_hub import snapshot_download as s\n"
            f"print(s({HF_REPO!r}, revision={HF_REV!r}, allow_patterns={HF_PATTERNS!r}), flush=True)\n"
            f"print(s({BASE_REPO!r}, revision={BASE_REV!r}, allow_patterns={BASE_PATTERNS!r}, max_workers=6), flush=True)\n")
    (ROOT / "_hf_fetch.py").write_text(code)
    try:                                   # 带令牌下载，限流额度高于匿名（两个仓库都公开，拿不到也能下）
        token = get("/lab/secret", timeout=30).decode().strip()
    except Exception:
        token = ""
    env = dict(ENV, HF_TOKEN=token) if token else ENV
    for attempt in range(8):               # 429 限流：等一会儿续传（已下载的分块会复用）
        with open(lf, "a") as lfh:
            rc = subprocess.run(["bash", "-lc", f"uv run --no-project --with 'huggingface-hub[hf_xet]==1.30.0' python {ROOT}/_hf_fetch.py"],
                                stdout=lfh, stderr=subprocess.STDOUT, env=env).returncode
        if rc == 0:
            break
        log(f"download attempt {attempt + 1} rc={rc}, retry in {60 * (attempt + 1)}s: {tail(lf, 1)[-160:]}")
        time.sleep(60 * (attempt + 1))
    if rc:
        raise RuntimeError(f"download failed rc={rc}\n" + tail(lf, 20))
    for repo, rev in ((HF_REPO, HF_REV), (BASE_REPO, BASE_REV)):
        if not snapshot(repo, rev).is_dir():
            raise RuntimeError(f"snapshot missing: {snapshot(repo, rev)}")
    log(f"download ok {time.time() - t0:.0f}s hf={out(f'du -sh {HF_HOME} | cut -f1')} free={free_gb():.0f}GB")


# 在 venv 里运行的推理进程：管线只加载一次，按 6 步→8 步顺序跑完所有镜头；每条写 <id>_s<n>.mp4/.json/.log。
RUNNER = r'''
import gc, json, logging, sys, time, traceback
from pathlib import Path
import torch
spec = json.loads(Path(sys.argv[1]).read_text())
OUT = Path(spec["out"])
logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("hyperflow_h3_flash").setLevel(logging.INFO)
import diffusers, transformers, hyperflow_h3_flash
from diffusers.utils.export_utils import encode_video
from diffusers.modular_pipelines.minimax_h3 import MiniMaxH3ImageReference as ImageReference
from hyperflow_h3_flash import load_pipeline
from hyperflow_h3_flash.pipeline import FPS, MAX_FRAMES, MIN_FRAMES, resolve_canvas, resolve_offload

def p(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)

def frames_for(seconds):            # 最接近目标时长的 17n+5 帧（6 s -> 141 帧 = 5.9 s）
    want = round(seconds * FPS)
    return min(range(MIN_FRAMES, MAX_FRAMES + 1, 17), key=lambda n: (abs(n - want), n))

state = {"pipe": None, "offload": spec.get("offload", "auto"), "attention": spec.get("attention", "auto"), "load_s": 0.0}

def ensure():
    if state["pipe"] is not None:
        return
    gc.collect(); torch.cuda.empty_cache()
    t0 = time.perf_counter()
    try:
        state["pipe"] = load_pipeline("ref2va", weights=spec["weights"], base_model=spec["base_model"],
                                      offload=state["offload"], attention_backend=state["attention"])
    except Exception:
        if state["attention"] == "sdpa":
            raise
        p("load failed with attention", state["attention"], "-> retry sdpa\n" + traceback.format_exc()[-1500:])
        state["attention"] = "sdpa"; gc.collect(); torch.cuda.empty_cache()
        state["pipe"] = load_pipeline("ref2va", weights=spec["weights"], base_model=spec["base_model"],
                                      offload=state["offload"], attention_backend="sdpa")
    state["load_s"] = time.perf_counter() - t0
    state["fresh"] = True             # 加载后第一条含 Triton INT8 内核编译（约 1 分钟）
    p(f"pipeline loaded {state['load_s']:.0f}s offload={resolve_offload(state['offload'], torch.device('cuda'))} "
      f"attention={state['attention']} vram={torch.cuda.memory_allocated() / 2**30:.1f}GiB")

steps_all = sorted({s for j in spec["jobs"] for s in j["steps"]})
todo = [(s, j) for s in steps_all for j in spec["jobs"] if s in j["steps"]]
dev = torch.device("cuda")
height, width = resolve_canvas()
p(f"torch {torch.__version__} diffusers {diffusers.__version__} transformers {transformers.__version__} "
  f"hyperflow {hyperflow_h3_flash.__version__} gpu {torch.cuda.get_device_name()} jobs {len(todo)}")
for k, (steps, job) in enumerate(todo, 1):
    tag = f"{job['id']}_s{steps}"
    if (OUT / f"{tag}.json").exists():
        p(f"[{k}/{len(todo)}] skip {tag} (done)"); continue
    nf = frames_for(job["seconds"])
    lines = [f"{tag} steps={steps} seed={job['seed']} frames={nf} refs={[Path(r).name for r in job['refs']]}"]
    p(f"[{k}/{len(todo)}] start", lines[0])
    for attempt in range(2):
        oom = False
        try:
            ensure()
            pipe, fresh = state["pipe"], state.pop("fresh", False)
            refs = [ImageReference.from_file(r) for r in job["refs"]]   # 顺序即 <Picture 1..n>
            torch.cuda.synchronize(); torch.cuda.reset_peak_memory_stats(dev)
            t0 = time.perf_counter()
            res = pipe(prompt=job["prompt"], references=refs, num_frames=nf, num_inference_steps=steps,
                       generator=torch.Generator().manual_seed(job["seed"]), output=["videos", "audio", "sampling_rate"])
            torch.cuda.synchronize(); gen_s = time.perf_counter() - t0
            peak, peak_res = torch.cuda.max_memory_allocated(dev) / 2**30, torch.cuda.max_memory_reserved(dev) / 2**30
            t1 = time.perf_counter()
            encode_video(res["videos"][0], fps=FPS, output_path=str(OUT / f"{tag}.mp4"),
                         audio=res["audio"][0], audio_sample_rate=res["sampling_rate"])
            enc_s = time.perf_counter() - t1
            del res
            meta = {"id": job["id"], "variant": f"s{steps}", "model": "hyperflow-h3-flash ref2va_int8_convrot",
                    "weights_rev": spec["weights_rev"], "base_rev": spec["base_rev"], "code_rev": spec["code_rev"],
                    "steps": steps, "seed": job["seed"], "num_frames": nf, "fps": FPS, "seconds_out": round(nf / FPS, 3),
                    "height": height, "width": width, "refs": [Path(r).name for r in job["refs"]],
                    "wall_seconds": round(gen_s + enc_s, 2), "generate_seconds": round(gen_s, 2),
                    "encode_seconds": round(enc_s, 2), "includes_kernel_compile": fresh,
                    "pipeline_load_seconds": round(state["load_s"], 1),
                    "peak_vram_allocated_gib": round(peak, 2), "peak_vram_reserved_gib": round(peak_res, 2),
                    "offload": resolve_offload(state["offload"], dev), "attention": state["attention"],
                    "gpu": torch.cuda.get_device_name(), "torch": torch.__version__,
                    "diffusers": diffusers.__version__, "transformers": transformers.__version__,
                    "prompt": job["prompt"]}
            lines.append(f"done gen={gen_s:.1f}s enc={enc_s:.1f}s peak={peak:.1f}GiB reserved={peak_res:.1f}GiB "
                         f"offload={meta['offload']} compile={fresh}")
            (OUT / f"{tag}.log").write_text("\n".join(lines) + "\n")
            (OUT / f"{tag}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))   # json 最后写 = 完成标记
            p(f"[{k}/{len(todo)}] done", lines[-1])
            break
        except torch.OutOfMemoryError:
            lines.append(f"OOM offload={state['offload']}\n" + traceback.format_exc()[-3000:])
            oom = True
        except Exception:
            lines.append("FAIL\n" + traceback.format_exc()[-6000:])
            p(f"[{k}/{len(todo)}] FAIL {tag}\n" + lines[-1])
            (OUT / f"{tag}.log").write_text("\n".join(lines) + "\n")
            break
        if oom:                         # 全放显存放不下：换成 model 级卸载重建一次，后续镜头沿用
            p(f"[{k}/{len(todo)}] OOM {tag} offload={state['offload']}")
            if attempt or state["offload"] == "model":
                (OUT / f"{tag}.log").write_text("\n".join(lines) + "\n"); break
            state["pipe"] = pipe = res = None; state["offload"] = "model"
            gc.collect(); torch.cuda.empty_cache()
p("runner finished")
'''


def main():
    env = out("nvidia-smi --query-gpu=name,memory.total,compute_cap --format=csv,noheader; python3 --version; free -g | head -2; df -h /content | tail -1")
    log(f"lab start {MODEL}\n{env}")
    try:
        need = need_gb()
    except Exception as e:
        need = 95.0; log(f"need_gb check failed ({e}); assume {need}GB")
    if free_gb() < need + 20:              # +20GB 给 venv（torch 约 10GB）和成片
        log(f"磁盘只剩 {free_gb():.0f}GB，还需下载 {need:.0f}GB（+20GB 余量），放弃。"
            f"若本机有 pika_flex 缓存，可删 MiniMax-H3 的 transformer_ref 分片（约 66GB）后重试"); return
    log(f"disk ok: free={free_gb():.0f}GB need={need:.1f}GB")
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
        log(f"... free={free_gb():.0f}GB hf={out(f'du -sh {HF_HOME} 2>/dev/null | cut -f1')} "
            f"install_tail={tail(str(ROOT / 'install.log'), 1)[-120:]}")
    if errs:
        return
    jobs = json.loads(get("/lab/jobs", m=MODEL))
    IN.mkdir(parents=True, exist_ok=True); OUT.mkdir(parents=True, exist_ok=True)
    batch = []
    for job in jobs:
        refs = []
        for r in job["refs"]:
            dest = IN / r["name"]
            dest.write_bytes(get(r["url"], timeout=120))
            refs.append(str(dest))
        batch.append({"id": job["id"], "prompt": job["prompt"], "seconds": float(job["seconds"]),
                      "seed": int(job.get("seed", 42)), "steps": [int(s) for s in job.get("steps", [6, 8])], "refs": refs})
    spec = {"jobs": batch, "out": str(OUT), "weights": str(snapshot(HF_REPO, HF_REV)),
            "base_model": str(snapshot(BASE_REPO, BASE_REV)), "weights_rev": HF_REV, "base_rev": BASE_REV,
            "code_rev": CODE_REV, "offload": "auto", "attention": "auto"}
    (ROOT / "batch.json").write_text(json.dumps(spec, ensure_ascii=False))
    (ROOT / "hf_run.py").write_text(RUNNER)
    lf = str(ROOT / "batch.log")
    sent = set()
    def upload_done(final=False):          # json 出现即该条完成，立刻回传，不等整批
        for j in sorted(OUT.glob("*.json")):
            if j.stem in sent:
                continue
            for f in (j.with_suffix(".mp4"), j, j.with_suffix(".log")):
                if f.exists():
                    post(f"/lab/upload/{MODEL}/{f.name}", f.read_bytes(), timeout=600)
            sent.add(j.stem)
        if final:                          # 失败条目只有 .log
            for f in sorted(OUT.glob("*.log")):
                if f.stem not in sent:
                    post(f"/lab/upload/{MODEL}/{f.name}", f.read_bytes()); sent.add(f.stem)
    t0 = time.time()
    with open(lf, "a") as lfh:
        proc = subprocess.Popen(["bash", "-lc", f"cd {ROOT} && {VENV}/bin/python {ROOT}/hf_run.py {ROOT}/batch.json"],
                                stdout=lfh, stderr=subprocess.STDOUT, env=ENV)
    while proc.poll() is None:             # 每分钟回传进度，避免看起来像卡死
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            pass
        gpu = out("nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader")
        log(f"batch running {time.time() - t0:.0f}s gpu={gpu} done={len(sent)} | {tail(lf, 1)[-200:]}")
        try:
            upload_done()
        except Exception as e:
            log(f"upload retry later: {e}")
    log(f"batch rc={proc.returncode} {time.time() - t0:.0f}s\n" + tail(lf, 20))
    upload_done(final=True)
    post(f"/lab/upload/{MODEL}/batch.log", Path(lf).read_bytes())
    summary = []
    for j in sorted(OUT.glob("*.json")):
        m = json.loads(j.read_text())
        summary.append(f"{j.stem}: gen={m['generate_seconds']}s peak={m['peak_vram_allocated_gib']}GiB compile={m['includes_kernel_compile']}")
    log("lab finished\n" + "\n".join(summary))


main()
