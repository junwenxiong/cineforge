# Colab 端模型测试：Pika-H3-Flex（MiniMax-H3 的开源后训练版，Ref2VA 6 步，带同步音频）。
# 由 Colab 单元 exec，需事先定义 B（派片地址）、T（令牌）、W（机器名）。
# 权重和环境只放 Colab 的 /content；本机只收回 mp4 和元数据（/lab/upload/pika_flex/...）。
import json, os, shutil, subprocess, threading, time, urllib.parse, urllib.request
from pathlib import Path

B = globals().get("B") or os.environ["FARM_B"]
T = globals().get("T") or os.environ["FARM_T"]
W = globals().get("W") or os.environ.get("FARM_W", "lab")
ROOT = Path("/content/pika"); REPO = ROOT / "repo"; VENV = ROOT / "venv"; OUT = ROOT / "out"; IN = ROOT / "in"
HF_HOME = "/content/hf"
MODEL = "pika_flex"
PIKA_REPO, PIKA_REV = "Pika-Labs/Pika-H3-Flex", "0ddf55ad7067ca1e76812253bd7b4600df87f759"
BASE_REPO, BASE_REV = "MiniMaxAI/MiniMax-H3", "42ed227ee7df40d41602854ae760620d6eb651fe"
BASE_PATTERNS = ["transformer_ref/*", "text_encoder/*", "tokenizer/*", "processor/*", "vae/*", "audio_vae/*", "*.json",
                 "LICENSE", "NOTICE", "licenses/*"]
ENV = dict(os.environ, HF_HOME=HF_HOME, HF_XET_HIGH_PERFORMANCE="1", PYTHONUNBUFFERED="1", MPLBACKEND="Agg")


def url(path, **q):
    q["t"] = T; q["w"] = W
    return f"{B}{path}?{urllib.parse.urlencode(q)}"


def post(path, data, timeout=120):
    r = urllib.request.Request(url(path), data=data, method="POST",
                               headers={"Content-Type": "application/octet-stream", "User-Agent": "starcore-lab"})
    with urllib.request.urlopen(r, timeout=timeout) as f:
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


def install():
    t0 = time.time()
    ROOT.mkdir(parents=True, exist_ok=True)
    lf = str(ROOT / "install.log")
    if out("which uv") == "":
        sh("pip install -q uv", lf)
    if not REPO.exists():
        if sh(f"git clone --depth 1 https://github.com/Pika-Labs/Pika-H3-Flex {REPO}", lf):
            raise RuntimeError("clone failed\n" + tail(lf))
    if not (VENV / "bin/pika-h3-pro").exists():
        steps = [f"uv venv -p 3.12 {VENV}",
                 f"uv pip install -p {VENV}/bin/python --index-strategy unsafe-best-match -r requirements.txt",
                 f"{VENV}/bin/python tools/apply_diffusers_patches.py",
                 f"uv pip install -p {VENV}/bin/python --no-deps -e ."]
        for s in steps:
            if sh(s, lf, cwd=REPO):
                raise RuntimeError(f"install step failed: {s}\n" + tail(lf, 30))
    log(f"install ok {time.time() - t0:.0f}s: " + out(f"{VENV}/bin/python -c 'import torch;print(torch.__version__, torch.cuda.get_device_name())'"))


def download():
    t0 = time.time()
    lf = str(ROOT / "download.log")
    code = (f"from huggingface_hub import snapshot_download as s\n"
            f"s({PIKA_REPO!r}, revision={PIKA_REV!r}, allow_patterns=['ref2va/*','LICENSE','NOTICE','licenses/*'])\n"
            f"s({BASE_REPO!r}, revision={BASE_REV!r}, allow_patterns={BASE_PATTERNS!r}, max_workers=16)\n")
    (ROOT / "_hf_fetch.py").write_text(code)
    code = code.replace("max_workers=16", "max_workers=6")
    (ROOT / "_hf_fetch.py").write_text(code)
    try:                                   # 带令牌下载，限流额度高于匿名
        with urllib.request.urlopen(url("/lab/secret"), timeout=30) as f:
            token = f.read().decode().strip()
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
    size = out(f"du -sh {HF_HOME} | cut -f1")
    if rc:
        raise RuntimeError(f"download failed rc={rc}\n" + tail(lf, 20))
    log(f"download ok {time.time() - t0:.0f}s size={size} free={free_gb():.0f}GB")


def run_job(job):
    sid = job["id"]
    IN.mkdir(parents=True, exist_ok=True); OUT.mkdir(parents=True, exist_ok=True)
    refs = []
    for r in job["refs"]:
        dest = IN / r["name"]
        with urllib.request.urlopen(url(r["url"]), timeout=120) as f:
            dest.write_bytes(f.read())
        refs.append(f"--ref image:{dest}")
    pf = IN / f"{sid}.txt"
    pf.write_text(job["prompt"])
    mp4 = OUT / f"{sid}.mp4"
    lf = str(OUT / f"{sid}.log")
    extra = "--cpu-offload" if job.get("cpu_offload") else ""
    cmd = (f"{VENV}/bin/pika-h3-pro --task ref2va --prompt-file {pf} {' '.join(refs)} "
           f"--resolution {job.get('resolution', '768p')} --aspect 16:9 --duration {max(5, int(job['seconds']))} "
           f"--seed {job.get('seed', 42)} --model-repo {PIKA_REPO} --revision {PIKA_REV} {extra} --output {mp4}")
    t0 = time.time()
    rc = sh(cmd, lf)
    wall = time.time() - t0
    if rc or not mp4.exists():
        log(f"FAIL {sid} rc={rc} {wall:.0f}s\n" + tail(lf, 25))
        post(f"/lab/upload/{MODEL}/{sid}.log", Path(lf).read_bytes())
        return False
    meta = json.loads(mp4.with_suffix(".json").read_text())
    meta["wall_seconds"] = wall
    post(f"/lab/upload/{MODEL}/{sid}.mp4", mp4.read_bytes(), timeout=600)
    post(f"/lab/upload/{MODEL}/{sid}.json", json.dumps(meta, ensure_ascii=False, indent=1).encode())
    log(f"done {sid} wall={wall:.0f}s timings={ {k: round(v) for k, v in meta.get('timings', {}).items()} } "
        f"peak={meta.get('sampling_peak_allocated_bytes', 0) / 2**30:.0f}GiB")
    return True


def main():
    env = out("nvidia-smi --query-gpu=name,memory.total --format=csv,noheader; python3 --version; free -g | head -2; df -h /content | tail -1")
    log(f"lab start {MODEL}\n{env}")
    have = shutil.disk_usage("/content").used / 1e9 if Path(HF_HOME).exists() else 0   # 续传：已下载部分也算进可用空间
    if free_gb() + have < 165:
        log(f"磁盘只剩 {free_gb():.0f}GB，ref2va 权重约 147GB，放弃"); return
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
    with urllib.request.urlopen(url("/lab/jobs"), timeout=60) as f:
        jobs = json.loads(f.read())
    # 批量推理：编码器、Transformer、解码器各只加载一次（tools/film/lab/pika_batch.py）
    with urllib.request.urlopen(url("/lab/file/pika_batch.py"), timeout=60) as f:
        (ROOT / "pika_batch.py").write_bytes(f.read())
    IN.mkdir(parents=True, exist_ok=True); OUT.mkdir(parents=True, exist_ok=True)
    batch = []
    for job in jobs:
        refs = []
        for r in job["refs"]:
            dest = IN / r["name"]
            with urllib.request.urlopen(url(r["url"]), timeout=120) as f:
                dest.write_bytes(f.read())
            refs.append(str(dest))
        batch.append({"id": job["id"], "prompt": job["prompt"], "seconds": max(5, int(job["seconds"])),
                      "resolution": job.get("resolution", "768p"), "seed": job.get("seed", 42), "refs": refs,
                      "output": str(OUT / f"{job['id']}_batch.mp4")})
    (ROOT / "batch.json").write_text(json.dumps(batch, ensure_ascii=False))
    lf = str(ROOT / "batch.log")
    t0 = time.time()
    stop = threading.Event()
    def progress():                        # 批量推理期间每分钟回传最新进度，避免看起来像卡死
        while not stop.wait(60):
            gpu = out("nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader")
            log(f"batch running {time.time() - t0:.0f}s gpu={gpu} | {tail(lf, 1)[-200:]}")
    threading.Thread(target=progress, daemon=True).start()
    rc = sh(f"{VENV}/bin/python {ROOT}/pika_batch.py {ROOT}/batch.json", lf)
    stop.set()
    log(f"batch rc={rc} {time.time() - t0:.0f}s\n" + tail(lf, 20))
    post(f"/lab/upload/{MODEL}/batch.log", Path(lf).read_bytes())
    for b in batch:
        mp4 = Path(b["output"])
        for f in (mp4, mp4.with_suffix(".json")):
            if f.exists():
                post(f"/lab/upload/{MODEL}/{f.name}", f.read_bytes(), timeout=600)
    log("lab finished")


main()
