# Colab 端模型测试：daVinci-MagiHuman（GAIR/Sand.ai，15B 单流音视频联合模型，首帧+文本 → 带同步人声的视频）。
# 由 Colab 单元 exec，需事先定义 B（派片地址）、T（令牌）、W（机器名）。HF 令牌从派片服务内存取（/lab/secret），不落盘。
# 方案：distill 基础模型（448x256，8 步无 CFG）+ 1080p 潜空间超分（1920x1088，5 步）+ Turbo VAE 解码；
#       编码器：t5gemma-9b-9b-ul2（文本）、stable-audio-open-1.0（音频 VAE）、Wan2.2-TI2V-5B（视频 VAE）。
# 权重和环境只放 Colab 的 /content/magi；本机只收回 mp4/json/log（/lab/upload/magihuman/...）。
import json, os, shutil, subprocess, threading, time, urllib.parse, urllib.request
from pathlib import Path

B = globals().get("B") or os.environ["FARM_B"]
T = globals().get("T") or os.environ["FARM_T"]
W = globals().get("W") or os.environ.get("FARM_W", "lab")
ROOT = Path("/content/magi"); REPO = ROOT / "daVinci-MagiHuman"; MC = ROOT / "MagiCompiler"; VENV = ROOT / "venv"
CKPT = ROOT / "ckpt"; OUT = ROOT / "out"; IN = ROOT / "in"; WORK = ROOT / "work"
HF_HOME = "/content/hf"
MODEL = "magihuman"
# 代码与权重全部钉死版本（2026-11-20 核对）
DAVINCI_GIT, DAVINCI_SHA = "https://github.com/GAIR-NLP/daVinci-MagiHuman", "209209b7086eba2020c5439265221495a8357322"
MC_GIT, MC_SHA = "https://github.com/SandAI-org/MagiCompiler", "bf20441ad953bd6f7eb325a9175068e2a8d70cec"  # 2026-04-07，与上面代码同期
REPOS = [  # (仓库, 修订, allow_patterns, 本地目录)
    ("GAIR/daVinci-MagiHuman", "7fe95e50c11bd92bdadf94cd51dbec18427f8e0c",
     ["distill/*", "1080p_sr/*", "turbo_vae/*", "config.json"], "magihuman"),                       # 124.3GB
    ("google/t5gemma-9b-9b-ul2", "7071a2ace9c8353e12e723e5382cc7256ee41d9f",
     ["*.json", "*.safetensors", "tokenizer*"], "t5gemma-9b-9b-ul2"),                              # 40.7GB，授权仓库
    ("stabilityai/stable-audio-open-1.0", "f21265c1e2710b3bd2386596943f0007f55f802e",
     ["model_config.json", "model.safetensors", "LICENSE.md"], "stable-audio-open-1.0"),          # 4.9GB，授权仓库
    ("Wan-AI/Wan2.2-TI2V-5B", "921dbaf3f1674a56f47e83fb80a34bac8a8f203e", ["Wan2.2_VAE.pth"], "Wan2.2-TI2V-5B"),  # 2.8GB
]
NEED_GB = 173 + 15            # 权重 172.6GB + venv/uv 缓存/成片余量
TORCH = "torch==2.9.0 torchvision==0.24.0 torchaudio==2.9.0"   # MagiCompiler@bf20441 要求 triton==3.5.0（torch 2.9 配套）
SKIP_REQS = "mosaicml_streaming|psycopg2-binary|redis|redislite|boto3|debugpy|torchao"   # 推理代码不 import 的训练/服务依赖
ENV = dict(os.environ, HF_HOME=HF_HOME, HF_XET_HIGH_PERFORMANCE="1", HF_XET_CHUNK_CACHE_SIZE_BYTES="0",
           PYTHONUNBUFFERED="1", MPLBACKEND="Agg")


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


def dir_gb(p):
    return sum(f.stat().st_size for f in Path(p).rglob("*") if f.is_file()) / 1e9 if Path(p).exists() else 0


def install():
    t0 = time.time()
    ROOT.mkdir(parents=True, exist_ok=True)
    lf = str(ROOT / "install.log")
    if out("which uv") == "":
        sh("pip install -q uv", lf)
    for git, sha, dest in ((DAVINCI_GIT, DAVINCI_SHA, REPO), (MC_GIT, MC_SHA, MC)):
        if not (dest / ".git").exists() and sh(f"git init -q {dest} && cd {dest} && git fetch -q --depth 1 {git} {sha} "
                                               f"&& git checkout -q FETCH_HEAD", lf):
            raise RuntimeError(f"clone failed {git}\n" + tail(lf))
    py = f"{VENV}/bin/python"
    if not (VENV / ".magi_ok").exists():
        (ROOT / "constraints.txt").write_text(TORCH.replace(" ", "\n") + "\n")
        steps = [f"uv venv -p 3.12 {VENV}",
                 f"uv pip install -p {py} {TORCH} --index-url https://download.pytorch.org/whl/cu128",
                 f"grep -vE '^({SKIP_REQS})' {REPO}/requirements.txt > {ROOT}/req.txt",
                 f"uv pip install -p {py} -c {ROOT}/constraints.txt -r {ROOT}/req.txt "
                 f"depyf astor graphviz more-itertools regex requests",               # 后三个给 whisper/tiktoken（下面 --no-deps 装）
                 f"uv pip install -p {py} --no-deps -r {REPO}/requirements-nodeps.txt",
                 f"touch {VENV}/.magi_ok"]
        for s in steps:
            if sh(s, lf, cwd=ROOT):
                raise RuntimeError(f"install step failed: {s}\n" + tail(lf, 30))
    chk = (f"cd {ROOT} && PYTHONPATH={REPO}:{MC} {py} -c 'import torch, triton, magi_compiler, whisper; "
           f"from transformers.models.t5gemma import T5GemmaEncoderModel; import inference.pipeline; "
           f"print(torch.__version__, triton.__version__, torch.cuda.get_device_name())'")
    if sh(chk, lf):
        raise RuntimeError("import check failed\n" + tail(lf, 30))
    log(f"install ok {time.time() - t0:.0f}s: {tail(lf, 1)}")


def download():
    t0 = time.time()
    token = ""
    while not token:                      # t5gemma / stable-audio 是授权仓库，必须带令牌
        try:
            token = get("/lab/secret", timeout=30).decode().strip()
        except Exception as e:
            print("secret fetch failed", e, flush=True)
        if not token:
            log("等待 HF 令牌（t5gemma、stable-audio-open 为授权仓库）…"); time.sleep(60)
    lf = str(ROOT / "download.log")
    items = sorted(REPOS, key=lambda r: r[0].startswith("GAIR"))   # 先下小的授权仓库，权限不对早失败
    code = ("import sys\nfrom huggingface_hub import HfApi, snapshot_download as s\napi = HfApi()\n"
            f"items = {items!r}\n"
            "for repo, rev, pats, sub in items:\n"
            "    try:\n        api.auth_check(repo)\n"
            "    except Exception as e:\n"
            "        print(f'ACCESS DENIED {repo}: {type(e).__name__}: {e}', flush=True); sys.exit(3)\n"
            "for repo, rev, pats, sub in items:\n"
            f"    print(s(repo, revision=rev, allow_patterns=pats, local_dir={str(CKPT)!r} + '/' + sub, max_workers=6), flush=True)\n")
    (ROOT / "_hf_fetch.py").write_text(code)
    env = dict(ENV, HF_TOKEN=token)
    for attempt in range(8):               # 429 限流：等一会儿续传（local_dir 里已完成的文件会跳过）
        with open(lf, "a") as lfh:
            rc = subprocess.run(["bash", "-lc", f"uv run --no-project --with 'huggingface-hub[hf_xet]==1.30.0' python {ROOT}/_hf_fetch.py"],
                                stdout=lfh, stderr=subprocess.STDOUT, env=env).returncode
        if rc in (0, 3):
            break
        log(f"download attempt {attempt + 1} rc={rc}, retry in {60 * (attempt + 1)}s: {tail(lf, 1)[-160:]}")
        time.sleep(60 * (attempt + 1))
    if rc == 3:
        raise RuntimeError("HF 令牌没有授权仓库的访问权：请用该账号在 huggingface.co/google/t5gemma-9b-9b-ul2 和 "
                           "huggingface.co/stabilityai/stable-audio-open-1.0 页面接受许可后重跑\n" + tail(lf, 4))
    if rc:
        raise RuntimeError(f"download failed rc={rc}\n" + tail(lf, 20))
    log(f"download ok {time.time() - t0:.0f}s size={out(f'du -sh {CKPT} | cut -f1')} free={free_gb():.0f}GB")


def write_config():
    m = CKPT / "magihuman"
    cfg = {"engine_config": {"load": str(m / "distill"), "cp_size": 1},
           "evaluation_config": {"cfg_number": 1, "num_inference_steps": 8,               # distill：8 步、无 CFG
                                 "audio_model_path": str(CKPT / "stable-audio-open-1.0"),
                                 "txt_model_path": str(CKPT / "t5gemma-9b-9b-ul2"),
                                 "vae_model_path": str(CKPT / "Wan2.2-TI2V-5B"),
                                 "use_sr_model": True, "sr_model_path": str(m / "1080p_sr"),
                                 "sr_num_inference_steps": 5, "sr_cfg_number": 1,       # 与官方 sr_1080p 示例一致
                                 "use_turbo_vae": True,
                                 "student_config_path": str(m / "turbo_vae/TurboV3-Wan22-TinyShallow_7_7.json"),
                                 "student_ckpt_path": str(m / "turbo_vae/checkpoint-340000.ckpt")}}
    (ROOT / "config.json").write_text(json.dumps(cfg, indent=1))


def main():
    env = out("nvidia-smi --query-gpu=name,memory.total --format=csv,noheader; free -g | head -2; df -h /content | tail -1")
    log(f"lab start {MODEL}\n{env}")
    (ROOT / "dl.py").unlink(missing_ok=True)   # 旧名 dl.py 会被 setuptools 的 `import dl` 误加载（torch 编译时触发），删掉
    have = dir_gb(CKPT)                    # 续传：已下载部分也算进可用空间
    if free_gb() + have < NEED_GB:
        big = out("du -sh /content/* 2>/dev/null | sort -h | tail -5")
        log(f"磁盘只剩 {free_gb():.0f}GB（已有 MagiHuman 权重 {have:.0f}GB），共需约 {NEED_GB}GB，放弃。/content 大目录：\n{big}")
        return
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
        log(f"... free={free_gb():.0f}GB ckpt={out(f'du -sh {CKPT} 2>/dev/null | cut -f1')} "
            f"install_tail={tail(str(ROOT / 'install.log'), 1)[-120:]}")
    if errs:
        if (ROOT / "install.log").exists():
            post(f"/lab/upload/{MODEL}/install.log", (ROOT / "install.log").read_bytes())
        return
    jobs = json.loads(get("/lab/jobs", m=MODEL))
    (ROOT / "magihuman_batch.py").write_bytes(get("/lab/file/magihuman_batch.py"))
    write_config()
    for d in (IN, OUT, WORK):
        d.mkdir(parents=True, exist_ok=True)
    batch = []
    for job in jobs:
        img = IN / f"{job['id']}.png"
        img.write_bytes(get("/lab/kf", p=job["keyframe"]))
        batch.append({"id": job["id"], "prompt": job["prompt"], "image": str(img), "seconds": int(job["seconds"]),
                      "seed": job.get("seed", 42), "br_width": job.get("br_width", 448), "br_height": job.get("br_height", 256),
                      "sr_width": job.get("sr_width", 1920), "sr_height": job.get("sr_height", 1088),
                      "output": str(OUT / f"{job['id']}.mp4")})
    (ROOT / "batch.json").write_text(json.dumps(batch, ensure_ascii=False))
    for b in batch:                        # 单元重跑时清掉上一轮的结果，否则会被当成"已回传"而跳过新结果
        for f in (Path(b["output"]), Path(b["output"]).with_suffix(".json")):
            f.unlink(missing_ok=True)
    sent, lock = set(), threading.Lock()

    def upload_ready():                    # 每镜写完 json 即回传，不等整批结束
        with lock:
            for b in batch:
                mp4 = Path(b["output"]); js = mp4.with_suffix(".json")
                if js.exists() and b["id"] not in sent:
                    for f in (mp4, js):
                        if f.exists():
                            post(f"/lab/upload/{MODEL}/{f.name}", f.read_bytes(), timeout=600)
                    sent.add(b["id"])
                    meta = json.loads(js.read_text())
                    log(f"{'done' if meta.get('ok') else 'FAIL'} {b['id']} wall={meta.get('wall_seconds')}s "
                        f"peak={meta.get('peak_allocated_gib')}GiB steps={meta.get('steps')} {meta.get('error', '')[:300]}")

    def run_batch(tag, extra_env):
        lf = str(ROOT / f"batch_{tag}.log")
        t0 = time.time()
        stop = threading.Event()

        def progress():                    # 每分钟回传进度和显存，避免看起来像卡死（首次 MagiCompiler 编译要几分钟）
            while not stop.wait(60):
                gpu = out("nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader")
                log(f"batch[{tag}] running {time.time() - t0:.0f}s gpu={gpu} | {tail(lf, 1)[-200:]}")
                try:
                    upload_ready()
                except Exception as e:
                    print("upload failed", e, flush=True)
        threading.Thread(target=progress, daemon=True).start()
        cmd = (f"PYTHONPATH={REPO}:{MC} MAGI_BATCH={ROOT}/batch.json CPU_OFFLOAD=true SR2_1080={'true' if max(b['sr_height'] for b in batch) >= 1080 else 'false'} "
               f"PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True NCCL_ALGO='^NVLS' {extra_env} "
               f"{VENV}/bin/torchrun --standalone --nproc_per_node=1 {ROOT}/magihuman_batch.py --config-load-path {ROOT}/config.json")
        rc = sh(cmd, lf, cwd=WORK)
        stop.set()
        log(f"batch[{tag}] rc={rc} {time.time() - t0:.0f}s\n" + tail(lf, 20))
        post(f"/lab/upload/{MODEL}/batch_{tag}.log", Path(lf).read_bytes())
        return rc

    run_batch("compiled", os.environ.get("MAGI_EXTRA_ENV", ""))
    ok = [b for b in batch if Path(b["output"]).with_suffix(".json").exists()
          and json.loads(Path(b["output"]).with_suffix(".json").read_text()).get("ok")]
    if not ok and "MAGI_COMPILE_COMPILE_MODE" not in os.environ.get("MAGI_EXTRA_ENV", ""):
        upload_ready()                     # 先把编译版的失败记录传回，再用纯 eager 重跑一次
        log("没有一镜成功，关闭 MagiCompiler 编译（eager）重跑")
        for b in batch:
            Path(b["output"]).with_suffix(".json").unlink(missing_ok=True)
        sent.clear()
        run_batch("eager", "MAGI_COMPILE_COMPILE_MODE=NONE")
    upload_ready()
    log("lab finished")


main()
