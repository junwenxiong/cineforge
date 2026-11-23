# Colab 端：老电影"换成猫"重演。LTX-2.5 distilled + LTX-2.3 Union-Control IC-LoRA。
# 每镜：从原片切出这一段 → 算控制视频（depth 深度 / canny 边缘）→ 猫版首帧（本机 gpt-image 画好，经 /lab/kf 取）
#       → ltx_pipelines.ic_lora 生成，原片同期声冻结为目标音频（--no-refine-audio，输出带原声，口型跟着原声生成）。
# 原片由云机直接从 Internet Archive 下载（快，且不走隧道）；本机只收回成片 mp4、控制视频预览和日志。
# 由 Colab 单元 exec，需事先定义 B、T、W（W 以 v2v_ 开头，即任务单名）。HF 令牌只从派片服务内存取。
import hashlib, json, os, shlex, shutil, subprocess, threading, time, urllib.parse, urllib.request
from pathlib import Path

B = globals().get("B") or os.environ["FARM_B"]
T = globals().get("T") or os.environ["FARM_T"]
W = globals().get("W") or os.environ.get("FARM_W", "v2v_lab")
MODEL = globals().get("LAB_MODEL") or (W if W.startswith("v2v_") else "v2v_lab")
ROOT = Path("/content/ltx"); REPO = ROOT / "LTX-2"; MODELS = Path(os.environ.get("CINEFORGE_MODEL_CACHE") or (ROOT / "models"))
WORK = Path("/content/v2v"); SRC = WORK / "src"; OUT = WORK / "out"; OUT_SHARED = Path("/content/cineforge_outputs")
IDLE_SHUTDOWN_MIN = int(globals().get("IDLE_SHUTDOWN_MIN") or os.environ.get("CINEFORGE_IDLE_MIN") or 15)
AUTO_UNASSIGN = bool(globals().get("AUTO_UNASSIGN") or os.environ.get("CINEFORGE_AUTO_UNASSIGN") == "1")
POLL_STUDIO = bool(globals().get("POLL_STUDIO") or MODEL == "v2v_studio")
UNION = "ltx-2.3-22b-ic-lora-union-control-ref0.5.safetensors"
FILES = {
    "Lightricks/LTX-2.5": ["diffusion_models/ltx-2.5-22b-distilled-transformer-bf16.safetensors",
                           "text_encoders/gemma4-12b-with-proj-ltx-2.5-bf16.safetensors",
                           "vae/ltx-2.5-video-vae-bf16.safetensors",
                           "vae/ltx-2.5-audio-vae-bf16.safetensors",
                           "latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors"],
    "Lightricks/LTX-2.3-22b-IC-LoRA-Union-Control": [UNION],
    "depth-anything/Depth-Anything-V2-Small-hf": ["config.json", "model.safetensors", "preprocessor_config.json"],
}
ENV = dict(os.environ, HF_HOME=os.environ.get("HF_HOME") or "/content/hf", HF_XET_HIGH_PERFORMANCE="1", PYTHONUNBUFFERED="1", MPLBACKEND="Agg")
FPS = 24


def url(path, **q):
    q["t"] = T; q["w"] = W
    return f"{B}{path}?{urllib.parse.urlencode(q)}"


def get(path, timeout=120, **q):
    with urllib.request.urlopen(url(path, **q), timeout=timeout) as f:
        return f.read()


def post(path, data, timeout=300):
    for attempt in range(5):
        try:
            r = urllib.request.Request(url(path), data=data, method="POST",
                                       headers={"Content-Type": "application/octet-stream", "User-Agent": "cineforge-lab"})
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
    ok = out("python3 -c 'import torch, transformers, cv2; print(torch.__version__, transformers.__version__, cv2.__version__)'")
    if not ok:
        sh("pip install -q transformers opencv-python-headless", lf)
    log(f"install ok {time.time() - t0:.0f}s: " + out(f"cd {REPO} && uv run python -c 'import torch;print(torch.__version__, torch.cuda.get_device_name())'"))


def download():
    t0 = time.time()
    token = os.environ.get("HF_TOKEN") or globals().get("HF_TOKEN") or ""
    while not token:
        try:
            token = get("/lab/secret").decode().strip()
        except Exception:
            token = ""
        if not token:
            log("等待 HF 令牌（LTX-2.5 为授权仓库；可在本机 .env 或 Colab Secrets 中设置 HF_TOKEN）…"); time.sleep(30)
    lf = str(ROOT / "download.log")
    code = "from huggingface_hub import hf_hub_download as d\n"
    for repo, files in FILES.items():
        dest = MODELS / "depth" if repo.startswith("depth-anything") else MODELS
        for f in files:
            code += f"print(d({repo!r}, {f!r}, local_dir={str(dest)!r}), flush=True)\n"
    (ROOT / "_hf_fetch.py").write_text(code)
    rc = sh(f"uv run --no-project --with 'huggingface-hub[hf_xet]' python {ROOT}/_hf_fetch.py", lf, env=dict(ENV, HF_TOKEN=token))
    if rc:
        raise RuntimeError(f"download failed rc={rc}\n" + tail(lf, 20))
    log(f"download ok {time.time() - t0:.0f}s size={out(f'du -sh {MODELS} | cut -f1')}")


def fetch_source(job):
    """原片只下载一次，按 md5 校验。source_url 可以是公网直链，也可以是 "sources/<文件>" 或 "studio/data/uploads/<文件>"
    （本机已下好或访客上传的片段，经派片服务 /lab/src 取，适合 B 站等云机不能直连的来源）。"""
    SRC.mkdir(parents=True, exist_ok=True)
    su = job["source_url"]
    f = SRC / Path(urllib.parse.urlparse(su).path).name
    if not f.exists():
        t0 = time.time()
        tmp = f.with_suffix(".part")
        if su.startswith("sources/") or su.startswith("studio/data/uploads/"):
            tmp.write_bytes(get("/lab/src", timeout=600, p=su))
        elif sh(f"curl -s -L --retry 5 -o {shlex.quote(str(tmp))} {shlex.quote(su)}"):
            raise RuntimeError("source download failed")
        md5 = hashlib.md5(tmp.read_bytes()).hexdigest()
        if job.get("source_md5") and md5 != job["source_md5"]:
            raise RuntimeError(f"source md5 mismatch {md5}")
        tmp.replace(f)
        log(f"source ok {f.name} {f.stat().st_size / 1e6:.0f}MB {time.time() - t0:.0f}s")
    return f


CONTROL_PY = r'''
import sys, subprocess, numpy as np, cv2
src, dst, kind, w, h = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5])
raw = subprocess.run(["ffmpeg", "-v", "error", "-i", src, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
frames = np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3)
CLEAN = len(sys.argv) > 9 and sys.argv[9] == "1"
if CLEAN:   # 先从原片里抹掉烧录字幕（白色细笔画），深度图里就不会有字形
    frames = frames.copy(); y0s = int(h * 0.78)
    for i in range(len(frames)):
        band = frames[i, y0s:]
        g = cv2.cvtColor(band, cv2.COLOR_RGB2GRAY)
        th = cv2.morphologyEx(g, cv2.MORPH_TOPHAT, np.ones((max(9, h // 60),) * 2, np.uint8))
        m = (((th > 40) & (g > 160)).astype(np.uint8)) * 255
        if m.sum() > 255 * 30:
            m = cv2.dilate(m, np.ones((max(11, h // 50) | 1,) * 2, np.uint8))   # 连黑色描边一起盖住
            frames[i, y0s:] = cv2.inpaint(np.ascontiguousarray(band), m, 7, cv2.INPAINT_TELEA)
if kind == "depth":
    import torch
    from transformers import pipeline
    pipe = pipeline("depth-estimation", model=sys.argv[6], device=0, torch_dtype=torch.float16)
    from PIL import Image
    ds = []
    for i in range(0, len(frames), 16):
        res = pipe([Image.fromarray(f) for f in frames[i:i + 16]])
        ds += [np.asarray(r["predicted_depth"].float().cpu()) for r in res]
    stack = np.stack([cv2.resize(d, (w, h), interpolation=cv2.INTER_CUBIC) for d in ds])
    lo, hi = np.percentile(stack, 1), np.percentile(stack, 99)       # 整镜统一归一化，避免逐帧闪烁
    out = (np.clip((stack - lo) / max(hi - lo, 1e-6), 0, 1) * 255).astype(np.uint8)   # 近处亮
else:
    outs = []
    for f in frames:
        g = cv2.bilateralFilter(cv2.cvtColor(f, cv2.COLOR_RGB2GRAY), 9, 60, 60)   # 压老胶片颗粒
        m = float(np.median(g))
        outs.append(cv2.Canny(g, int(max(0, 0.66 * m)), int(min(255, 1.33 * m))))
    out = np.stack(outs)
# 字幕带清理：原片烧录字幕会在深度/边缘图底部留下一排字形小点，模型照着画出乱码字幕。
# 底部 20% 做大核中值滤波（只抹掉细小字形，人物轮廓保留），上沿羽化过渡。
if CLEAN:
    y0 = int(h * 0.78); k = max(3, (h // 25) | 1)
    ramp = np.clip((np.arange(h - y0) - 0) / max(1, (h - y0) * 0.25), 0, 1)[:, None]
    for i in range(len(out)):
        band = out[i, y0:].copy()
        if kind == "canny":
            out[i, y0:] = (band * (1 - ramp)).astype(np.uint8)
        else:
            out[i, y0:] = (band * (1 - ramp) + cv2.medianBlur(band, k) * ramp).astype(np.uint8)
# 手部"融化"：真人手指轮廓会让模型照画人手。在手的位置把控制信号抹成一团光滑的"手套"，
# 模型就按提示词画猫爪；同时输出一个注意力遮罩视频，手部区域控制强度降到 HAND_ATTN。
import json, os
hf = sys.argv[7] if len(sys.argv) > 7 and sys.argv[7] != "-" else ""
mask = np.ones(out.shape, np.float32)
if hf and os.path.exists(hf):
    boxes = json.load(open(hf))["boxes"]
    attn = float(sys.argv[8])
    for i in range(len(out)):
        bs = boxes.get(str(i), [])
        if not bs:
            continue
        # 整帧画柔边椭圆（不按框裁切，否则模糊后留下硬边方块，模型会把它画成一张纸）
        soft = np.zeros((h, w), np.float32); size = 0
        for x0, y0, x1, y1 in bs:
            a, b, c, e = int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h)
            if c - a < 4 or e - b < 4:
                continue
            cv2.ellipse(soft, ((a + c) // 2, (b + e) // 2), ((c - a) // 2, (e - b) // 2), 0, 0, 360, 1, -1)
            size = max(size, min(c - a, e - b))
        if not size:
            continue
        soft = np.clip(cv2.GaussianBlur(soft, (0, 0), max(2, size / 6)) * 1.25, 0, 1)
        frame = out[i].astype(np.float32)
        # 只留低频：手臂和手是一团，手指（约为手框的 1/8 宽）被抹平；canny 直接擦掉手指线
        blob = np.zeros_like(frame) if kind == "canny" else cv2.GaussianBlur(frame, (0, 0), max(3, size / 4))
        out[i] = np.clip(frame * (1 - soft) + blob * soft, 0, 255).astype(np.uint8)
        mask[i] = np.minimum(mask[i], 1 - soft * (1 - attn))
    mv = (np.repeat(mask[..., None], 3, axis=3) * 255).astype(np.uint8)
    q = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", "24",
                          "-i", "-", "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", dst.replace(".mp4", "_mask.mp4")],
                         stdin=subprocess.PIPE)
    q.stdin.write(mv.tobytes()); q.stdin.close(); q.wait()
    print("hands melted in", sum(1 for i in range(len(out)) if boxes.get(str(i))), "frames")
rgb = np.repeat(out[..., None], 3, axis=3)
p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", "24",
                      "-i", "-", "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", dst], stdin=subprocess.PIPE)
p.stdin.write(rgb.tobytes()); p.stdin.close(); p.wait()
print("control", kind, len(frames), "frames")
'''


def run_job(job, src):
    sid = job["id"]
    d = WORK / "jobs" / sid; d.mkdir(parents=True, exist_ok=True); OUT.mkdir(parents=True, exist_ok=True)
    w, h = job.get("width", 1024), job.get("height", 768)
    n = ((max(9, round(job["dur"] * FPS)) - 1 + 7) // 8) * 8 + 1          # LTX 帧数须为 8k+1
    clip_dur = n / FPS
    lf = str(OUT / f"{sid}.log")
    clip, wav, ctrl = d / "clip.mp4", d / "clip.wav", d / f"control_{job['control']}.mp4"
    crop = f"crop={job['crop']}," if job.get("crop") else ""   # 去黑边：w:h:x:y（源像素）
    vf_arg = shlex.quote(f"{crop}fps={FPS},scale={w}:{h}:flags=lanczos,setsar=1,tpad=stop_mode=clone:stop_duration=2")
    if sh(f"ffmpeg -v error -y -ss {job['start']:.3f} -i {shlex.quote(str(src))} -t {clip_dur:.4f} -an "
          f"-vf {vf_arg} "
          f"-frames:v {n} -c:v libx264 -crf 12 -pix_fmt yuv420p {shlex.quote(str(clip))}", lf):
        raise RuntimeError("clip cut failed\n" + tail(lf))
    if sh(f"ffmpeg -v error -y -ss {job['start']:.3f} -i {shlex.quote(str(src))} -t {clip_dur:.4f} -vn -ac 2 -ar 48000 "
          f"-af apad=whole_dur={clip_dur:.4f} {shlex.quote(str(wav))}", lf):
        raise RuntimeError("audio cut failed\n" + tail(lf))
    (WORK / "control.py").write_text(CONTROL_PY)
    hands = ""
    if job.get("hands"):            # 本机 hand_mask.py 算好的手部框（随任务单下发）
        hj = d / "hands.json"; hj.write_text(json.dumps(job["hands"])); hands = str(hj)
        ctrl = d / f"control_{job['control']}_paws.mp4"
    ctrl = ctrl.with_name(ctrl.stem + "_v3.mp4")     # 控制算法改了就换版本号，别复用旧缓存
    if not ctrl.exists() and sh(f"python3 {WORK}/control.py {clip} {ctrl} {job['control']} {w} {h} {MODELS}/depth "
                                f"{hands or '-'} {job.get('hand_attn', 0.1)} {int(job.get('clean_band', True))}", lf):
        raise RuntimeError("control failed\n" + tail(lf, 20))
    kf = d / "kf.png"; kf.write_bytes(get("/lab/kf", p=job["keyframe"]))
    # 长镜头中途构图变了（摇镜换人）：在对应时刻再给一张猫版关键帧作引导，防止后段漂回真人
    guides = ""
    for i, (t, path, s) in enumerate(job.get("guides", [])):
        g = d / f"guide{i}.png"; g.write_bytes(get("/lab/kf", p=path))
        guides += f"--image {g} {min(n - 1, int(round(t * FPS)))} {s} "
    pf = d / "prompt.txt"; pf.write_text(job["prompt"])
    m = MODELS
    common = (f"--transformer-path {m}/diffusion_models/ltx-2.5-22b-distilled-transformer-bf16.safetensors "
              f"--text-encoder-path {m}/text_encoders/gemma4-12b-with-proj-ltx-2.5-bf16.safetensors "
              f"--video-vae-path {m}/vae/ltx-2.5-video-vae-bf16.safetensors "
              f"--audio-vae-path {m}/vae/ltx-2.5-audio-vae-bf16.safetensors "
              f"--spatial-upsampler-path {m}/latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors ")
    mp4 = OUT / f"{sid}.mp4"
    mk = Path(str(ctrl).replace(".mp4", "_mask.mp4"))
    amask = f"--conditioning-attention-mask {mk} 1.0 " if hands and mk.exists() else ""
    # 20 秒以内一次生成（实测 481 帧单卡可跑）；更长的长镜头分段生成，段间重叠 33 帧衔接
    # 原声做音频条件：口型跟着对白，但模型容易顺手"配上字幕"；no_audio 时不给原声，拼片时再铺回去
    audio = "" if job.get("no_audio") else f"--audio-path {wav} --no-refine-audio "
    if n > job.get("max_single_frames", 481):
        common += f"--chunk-pixel-frames {job.get('chunk_frames', 241)} --chunk-carry-frames {job.get('chunk_carry', 33)} "
    cmd = (f"uv run python -m ltx_pipelines.ic_lora {common} --lora {m}/{UNION} {job.get('lora_strength', 1.0)} "
           f"--video-conditioning {ctrl} {job.get('strength', 1.0)} {amask}--image {kf} 0 {job.get('image_strength', 1.0)} {guides}"
           f"{audio}--width {w} --height {h} --num-frames {n} --frame-rate {FPS} "
           f"--seed {job.get('seed', 42)} --output-path {mp4} --prompt \"$(cat {pf})\"")
    t0 = time.time()
    rc = sh(cmd, lf, cwd=REPO)
    wall = time.time() - t0
    if rc or not mp4.exists():
        log(f"FAIL {sid} rc={rc} {wall:.0f}s\n" + tail(lf, 25))
        post(f"/lab/upload/{MODEL}/{sid}.log", Path(lf).read_bytes())
        return
    OUT_SHARED.mkdir(parents=True, exist_ok=True)
    shutil.copy2(mp4, OUT_SHARED / f"{sid}.mp4")
    prev = OUT / f"{sid}_control.mp4"   # 控制视频小预览，供本机检查
    sh(f"ffmpeg -v error -y -i {shlex.quote(str(ctrl))} -vf scale=320:-2 -c:v libx264 -crf 30 {shlex.quote(str(prev))}")
    post(f"/lab/upload/{MODEL}/{sid}.mp4", mp4.read_bytes(), timeout=600)
    if prev.exists():
        post(f"/lab/upload/{MODEL}/{sid}_control.mp4", prev.read_bytes())
    post(f"/lab/upload/{MODEL}/{sid}.log", Path(lf).read_bytes())
    log(f"done {sid} {job['control']} frames={n} wall={wall:.0f}s")


def main():
    log(f"lab start {MODEL}\n" + out("nvidia-smi --query-gpu=name,memory.total --format=csv,noheader; df -h /content | tail -1"))
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
        log(f"... models={out(f'du -sh {MODELS} 2>/dev/null | cut -f1')} install_tail={tail(str(ROOT / 'install.log'), 1)[-100:]}")
    if errs:
        return
    if POLL_STUDIO:
        done_file = WORK / "v2v_uploaded.txt"
        done_ids = set(done_file.read_text().split()) if done_file.exists() else set()
        srcs = {}
        empty_since = None
        idle_limit = max(60, IDLE_SHUTDOWN_MIN * 60)
        log(f"v2v studio poll loop started (model={MODEL}, idle={IDLE_SHUTDOWN_MIN}m)")
        while True:
            try:
                raw_jobs = get("/lab/jobs", m=MODEL)
                jobs = json.loads(raw_jobs) if raw_jobs.strip() else []
            except Exception as e:
                print("jobs poll error", e, flush=True)
                jobs = []
            pending = [j for j in jobs if j.get("id") and j["id"] not in done_ids]
            if pending:
                empty_since = None
                job = pending[0]
                try:
                    if job["source_url"] not in srcs:
                        srcs[job["source_url"]] = fetch_source(job)
                    run_job(job, srcs[job["source_url"]])
                except Exception as e:
                    log(f"FAIL {job['id']} {e}"[:3000])
                done_ids.add(job["id"])
                with done_file.open("a") as df:
                    df.write(job["id"] + "\n")
                continue
            empty_since = empty_since or time.time()
            if time.time() - empty_since > idle_limit:
                log("v2v studio idle limit reached; exiting")
                if AUTO_UNASSIGN:
                    try:
                        from google.colab import runtime  # type: ignore
                        runtime.unassign()
                    except Exception as exc:
                        print("[IdleGuard] unassign skipped:", exc, flush=True)
                return
            time.sleep(15)
    else:
        jobs = json.loads(get("/lab/jobs", m=MODEL))
        srcs = {}                # 一张任务单可以混用多部原片
        for job in jobs:
            try:   # 每镜开拍前重读任务单，已删掉的跳过
                if job["id"] not in {j["id"] for j in json.loads(get("/lab/jobs", m=MODEL))}:
                    continue
            except Exception as e:
                print("jobs refresh failed", e, flush=True)
            try:
                if job["source_url"] not in srcs:
                    srcs[job["source_url"]] = fetch_source(job)
                run_job(job, srcs[job["source_url"]])
            except Exception as e:
                log(f"FAIL {job['id']} {e}"[:3000])
        log("lab finished")


main()
