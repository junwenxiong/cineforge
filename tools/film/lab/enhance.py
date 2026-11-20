# Colab 端画质增强测试：对已有 H3 成片（1344x768 24fps 带音频）跑开源视频增强模型，比较清晰度/画面感。
#   A. lightx2v/RelayVSR_X2（Apache-2.0，原生 2x 超分 -> 2688x1536，LightX2V 推理）
#   B. Efficient-Large-Model/Open-H3-Regenerate-2K-IC（MiniMax H3 社区许可；H3 Ref2VA transformer_ref + IC LoRA，
#      把 768P 草稿在上下文中重生成到 1080P，up3 采样 3 步）
# 由 Colab 单元 exec，需事先定义 B（派片地址）、T（令牌）、W（机器名）。
# 输入：/lab/jobs?m=enhance（renders/farm/lab_jobs_enhance.json），片子经 /lab/kf?p=assets/starcore/lab_kf_enhance/<id>.mp4 取
#      （farm_server 没有直接读 renders/<id>/raw.mp4 的入口，所以本机把 raw.mp4 拷到 lab_kf_enhance/ 下）。
# 输出：/lab/upload/enhance/<id>_relayvsr.mp4、<id>_regen.mp4、enhance_results.json、各阶段日志。
# 顺序：RelayVSR 安装+下载（11GB）-> 4 条推理并上传；Regenerate 环境安装同时进行，RelayVSR 权重下完后开始下 ~163GB，
#      与 RelayVSR 推理并行；GPU 同一时间只跑一个模型。
import json, math, os, re, shutil, subprocess, threading, time, urllib.parse, urllib.request
from pathlib import Path

B = globals().get("B") or os.environ["FARM_B"]
T = globals().get("T") or os.environ["FARM_T"]
W = globals().get("W") or os.environ.get("FARM_W", "lab")
MODEL = "enhance"
ROOT = Path("/content/enh"); IN = ROOT / "in"; OUT = ROOT / "out"; LOGS = ROOT / "logs"
HF_HOME = "/content/hf"
LX, LXV = ROOT / "LightX2V", ROOT / "venv_lx"           # RelayVSR 推理框架
ICV = ROOT / "venv_ic"                                  # Regenerate-IC 推理环境（代码随 HF 仓库 infer/）
VSR_DIR, IC_DIR = ROOT / "models/RelayVSR_X2", ROOT / "models/regen_ic"

LX_GIT, LX_REV = "https://github.com/ModelTC/LightX2V", "f2a56171bfe6555bd66a15d86e5c45c0d169add4"     # 2026-11-20 main
VSR_REPO, VSR_REV = "lightx2v/RelayVSR_X2", "bdaba6f33b6ec0b7f8a7d0c32c871e2539d1193b"
IC_REPO, IC_REV = "Efficient-Large-Model/Open-H3-Regenerate-2K-IC", "54a7104b204fb46486cf85c2f600942118186d57"
IC_CODE = "github.com/NVlabs/Sana@cf67a3acad7511acb85053e56a05e5dd24c82ba0 models/Open-H3-Regenerate-2K/IC（与 HF infer/ 相同）"
VSR_FILES = ["wan_x2.safetensors", "flash_x2.safetensors"]                              # 10.13 + 0.13 GB
IC_BASE = ["transformer_ref/*", "vae/*", "text_encoder/*", "tokenizer/*", "processor/*", "scheduler/*",
           "model_index.json", "modular_model_index.json", "LICENSE", "README.md"]          # 同 infer/download.py
IC_PATTERNS = (["config.json", "LICENSE", "LICENSE-Qwen.txt", "NOTICE", "infer/*", "lora/*", "assets/*",
                "latent_upsampler/*", "vae_fast/*"] + [f"base_model/{p}" for p in IC_BASE])   # 1080p 也要全部，约 163GB
VSR_GB, IC_GB, VENV_GB, RESERVE_GB = 10.3, 163.0, 20.0, 30.0
IC_PIP = ["torch", "torchvision", "diffusers==0.43.0", "transformers==5.6.0", "accelerate", "safetensors",
          "huggingface_hub", "kernels==0.14.0", "av==16.1.0", "einops", "numpy"]   # infer/requirements.txt，按其说明钉版本
LX_SKIP = {"sgl-kernel", "alibabacloud_dypnsapi20170525", "redis", "tos", "pymongo", "asyncpg", "aioboto3", "aio-pika",
           "modelscope", "swanlab", "decord", "qtorch"}      # 解析失败时的精简安装：去掉服务端/其它模型用的包
WIN, MIN_REAL, MIN_OVERLAP, XFADE = 124, 113, 24, 8     # Regenerate 每次 124 帧（5.17s）；长片分窗，重叠段中部淡化 8 帧
ENV = dict(os.environ, HF_HOME=HF_HOME, HF_XET_HIGH_PERFORMANCE="1", HF_XET_CHUNK_CACHE_SIZE_BYTES="0",
           PYTHONUNBUFFERED="1", MPLBACKEND="Agg")
RESULTS = {"model": MODEL, "worker": W, "revisions": {"LightX2V": LX_REV, VSR_REPO: VSR_REV, IC_REPO: IC_REV, "ic_code": IC_CODE},
           "env": {}, "downloads": {}, "clips": {}, "errors": []}
STAGE = {"now": "start", "log": None}
T0 = time.time()


def url(path, **q):
    q["t"] = T; q["w"] = W
    return f"{B}{path}?{urllib.parse.urlencode(q)}"


def post(path, data, timeout=120):
    r = urllib.request.Request(url(path), data=data, method="POST",
                               headers={"Content-Type": "application/octet-stream", "User-Agent": "starcore-lab"})
    with urllib.request.urlopen(r, timeout=timeout) as f:
        return f.read()


def get(path, timeout=120, **q):
    with urllib.request.urlopen(url(path, **q), timeout=timeout) as f:
        return f.read()


def log(msg):
    print(msg, flush=True)
    try:
        post("/lab/log", f"[{MODEL}] {msg}"[:4000].encode())
    except Exception as e:
        print("log post failed", e, flush=True)


def upload(name, data, timeout=600):
    for attempt in range(3):
        try:
            post(f"/lab/upload/{MODEL}/{name}", data, timeout=timeout); return True
        except Exception as e:
            log(f"upload {name} attempt {attempt + 1} failed: {e}"); time.sleep(10 * (attempt + 1))
    return False


def upload_file(p, tail_lines=None):
    p = Path(p)
    if p.exists():
        data = p.read_bytes() if tail_lines is None else tail(p, tail_lines).encode()
        upload(p.name, data)


def sh(cmd, logfile=None, cwd=None, env=None):
    with open(logfile or os.devnull, "a") as lf:
        return subprocess.run(["bash", "-lc", cmd], stdout=lf, stderr=subprocess.STDOUT, cwd=cwd, env=env or ENV).returncode


def out(cmd):
    return subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True, env=ENV).stdout.strip()


def tail(f, n=15):
    return out(f"tail -n {n} '{f}'") if Path(f).exists() else ""


def free_gb(p="/content"):
    return shutil.disk_usage(p).free / 1e9


def du_gb(p):
    return float(out(f"du -sb '{p}' 2>/dev/null | cut -f1") or 0) / 1e9 if Path(p).exists() else 0.0


def gpu_mem_mib():
    try:
        return int(out("nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits").splitlines()[0])
    except Exception:
        return 0


class Vram:
    """nvidia-smi 每 0.5s 采样一次显存（含 CUDA 上下文和缓存分配器预留）；mark() 取上次 mark 以来的峰值。"""
    def __init__(self):
        self.peak = self.seg = 0; self.stop = threading.Event()
        self.th = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self.stop.wait(0.5):
            m = gpu_mem_mib(); self.peak = max(self.peak, m); self.seg = max(self.seg, m)

    def mark(self):
        m, self.seg = self.seg, 0
        return round(m / 1024, 2)

    def __enter__(self):
        self.th.start(); return self

    def __exit__(self, *a):
        self.stop.set(); self.th.join(2)


def probe(p):
    """解码校验 + 帧数/尺寸/音频，失败返回 None。"""
    if not Path(p).exists() or sh(f"ffmpeg -nostdin -v error -xerror -i '{p}' -f null -"):
        return None
    v = out(f"ffprobe -v error -count_frames -select_streams v:0 -show_entries stream=nb_read_frames,width,height,codec_name "
            f"-of csv=p=0 '{p}'").split(",")
    a = out(f"ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of csv=p=0 '{p}'")
    return {"codec": v[0], "width": int(v[1]), "height": int(v[2]), "frames": int(v[3]), "audio": a or None,
            "mb": round(Path(p).stat().st_size / 1e6, 2)}


def mux_audio(video, src, dst):
    """增强后的画面 + 原片音轨（不重编码）。"""
    return sh(f"ffmpeg -nostdin -y -v error -i '{video}' -i '{src}' -map 0:v:0 -map 1:a:0 -c:v copy -c:a copy "
              f"-movflags +faststart '{dst}'", LOGS / "ffmpeg.log")


def hf_token():
    try:
        return get("/lab/secret", timeout=30).decode().strip()
    except Exception:
        return ""


def hf_download(name, code, est_gb, d):
    """在独立的 uv 临时环境里跑 huggingface-hub 下载；429/断线时等待后续传。"""
    t0 = time.time(); lf = LOGS / f"download_{name}.log"
    script = ROOT / f"dl_{name}.py"; script.write_text(code)
    token = hf_token()
    env = dict(ENV, HF_TOKEN=token) if token else ENV
    rc = 1
    for attempt in range(8):
        with open(lf, "a") as lfh:
            rc = subprocess.run(["bash", "-lc", f"uv run --no-project --with 'huggingface-hub[hf_xet]==1.30.0' python {script}"],
                                stdout=lfh, stderr=subprocess.STDOUT, env=env).returncode
        if rc == 0:
            break
        log(f"download {name} attempt {attempt + 1} rc={rc}, retry in {60 * (attempt + 1)}s: {tail(lf, 1)[-160:]}")
        time.sleep(60 * (attempt + 1))
    if rc:
        raise RuntimeError(f"download {name} failed rc={rc}\n" + tail(lf, 20))
    RESULTS["downloads"][name] = {"seconds": round(time.time() - t0), "gb": round(du_gb(d), 2), "est_gb": est_gb}
    log(f"download {name} ok {time.time() - t0:.0f}s size={du_gb(d):.1f}GB free={free_gb():.0f}GB")


def ensure_uv(lf):
    if out("which uv") == "":
        sh("pip install -q uv", lf)


def install_lightx2v():
    t0 = time.time(); lf = LOGS / "install_lightx2v.log"
    if not (LX / ".git").exists():
        for s in [f"git init -q {LX}", f"git -C {LX} remote add origin {LX_GIT}", f"git -C {LX} fetch -q --depth 1 origin {LX_REV}",
                  f"git -C {LX} checkout -q FETCH_HEAD"]:
            if sh(s, lf):
                raise RuntimeError(f"LightX2V clone failed: {s}\n" + tail(lf))
    ok = LXV / ".enh_ok"
    if not ok.exists():
        if not LXV.exists() and sh(f"uv venv -p 3.12 {LXV}", lf):
            raise RuntimeError("uv venv failed\n" + tail(lf))
        py = f"{LXV}/bin/python"
        if sh(f"uv pip install -p {py} -r requirements.txt 'av>=17' 'torchada>=0.1.10'", lf, cwd=LX):
            log("LightX2V 完整 requirements 安装失败，改用精简依赖重试: " + tail(lf, 3)[-300:])
            reqs = [l.strip() for l in (LX / "requirements.txt").read_text().splitlines()
                    if l.strip() and not l.startswith("#") and re.split(r"[<>=!\[ ]", l.strip())[0] not in LX_SKIP]
            (ROOT / "lx_req_min.txt").write_text("\n".join(reqs + ["av>=17", "torchada>=0.1.10"]) + "\n")
            if sh(f"uv pip install -p {py} -r {ROOT}/lx_req_min.txt", lf, cwd=LX):
                raise RuntimeError("LightX2V install failed\n" + tail(lf, 30))
        chk = f"cd {LX} && PYTHONPATH={LX} {py} -c 'import lightx2v.models.runners.relayvsr.relayvsr_runner'"
        if sh(chk, lf):
            raise RuntimeError("LightX2V import check failed\n" + tail(lf, 30))
        ok.touch()
    v = out(f"{LXV}/bin/python -c 'import torch;print(torch.__version__, torch.cuda.get_device_name())'")
    RESULTS["env"]["lightx2v_torch"] = v
    log(f"install lightx2v ok {time.time() - t0:.0f}s: {v}")


def install_ic():
    t0 = time.time(); lf = LOGS / "install_ic.log"
    ok = ICV / ".enh_ok"
    if not ok.exists():
        if not ICV.exists() and sh(f"uv venv -p 3.12 {ICV}", lf):
            raise RuntimeError("uv venv failed\n" + tail(lf))
        pkgs = " ".join(f"'{p}'" for p in IC_PIP)
        if sh(f"uv pip install -p {ICV}/bin/python {pkgs}", lf):
            raise RuntimeError("Regenerate-IC install failed\n" + tail(lf, 30))
        chk = (f"{ICV}/bin/python -c 'from diffusers import MiniMaxH3Transformer3DModel, AutoencoderKLMiniMaxH3; "
               f"from diffusers.modular_pipelines.minimax_h3.encoders import MiniMaxH3Ref2VATextEncoderStep'")
        if sh(chk, lf):
            raise RuntimeError("Regenerate-IC import check failed\n" + tail(lf, 30))
        ok.touch()
    v = out(f"{ICV}/bin/python -c 'import torch,diffusers,transformers;print(torch.__version__, diffusers.__version__, transformers.__version__)'")
    RESULTS["env"]["ic_torch_diffusers_transformers"] = v
    log(f"install regen-ic ok {time.time() - t0:.0f}s: {v}")


def download_vsr():
    hf_download("relayvsr", f"from huggingface_hub import snapshot_download as s\n"
                f"s({VSR_REPO!r}, revision={VSR_REV!r}, local_dir={str(VSR_DIR)!r}, allow_patterns={VSR_FILES!r}, max_workers=8)\n",
                VSR_GB, VSR_DIR)


def download_ic():
    # 官方 infer/download.py 的内容：本仓库组件 + base_model/（H3 @ 42ed227 原样拷贝）+ 按字节区间取 LMS Sharp 的 adaln_t_table
    hf_download("regen_ic", f"import sys\nfrom pathlib import Path\nfrom huggingface_hub import snapshot_download as s\n"
                f"s({IC_REPO!r}, revision={IC_REV!r}, local_dir={str(IC_DIR)!r}, allow_patterns={IC_PATTERNS!r}, max_workers=8)\n"
                f"sys.path.insert(0, {str(IC_DIR / 'infer')!r})\nfrom download import fetch_curve\n"
                f"c = Path({str(IC_DIR / 'sharp/lms_curve.bin')!r})\nc.exists() or fetch_curve(c)\n", IC_GB, IC_DIR)


def lx_env():
    return dict(ENV, PYTHONPATH=str(LX), MOONCAKE_CONFIG_PATH=f"{LX}/configs/mooncake/mooncake_config.json",
                TOKENIZERS_PARALLELISM="false", PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True",
                PYTORCH_ALLOC_CONF="expandable_segments:True", DTYPE="BF16", SENSITIVE_LAYER_DTYPE="None",
                PROFILING_DEBUG_LEVEL="2", CUDA_VISIBLE_DEVICES="0")


def run_relayvsr(clips):
    cfg = json.loads((LX / "configs/relayvsr/relayvsr_x2.json").read_text())
    cfg.update(video_codec="libx264", video_crf=16, ffmpeg_preset="veryfast")   # 官方默认 libx265 ultrafast；改 H.264 便于本机直接播放
    (ROOT / "relayvsr_x2_lab.json").write_text(json.dumps(cfg, indent=1))
    RESULTS["env"]["relayvsr_config"] = cfg
    for c in clips:
        sid = c["id"]; inp = IN / f"{sid}.mp4"
        tmp, final, lf = OUT / f"{sid}_relayvsr_noaudio.mp4", OUT / f"{sid}_relayvsr.mp4", LOGS / f"relayvsr_{sid}.log"
        STAGE.update(now=f"relayvsr {sid}", log=lf)
        cmd = (f"{LXV}/bin/python -m lightx2v.infer --model_cls relayvsr_x2 --task sr --model_path {VSR_DIR} "
               f"--config_json {ROOT}/relayvsr_x2_lab.json --video_path {inp} --sr_ratio 2 --save_result_path {tmp} --seed 42")
        t0 = time.time()
        with Vram() as vm:
            rc = sh(cmd, lf, cwd=LX, env=lx_env())
        wall = time.time() - t0
        m = re.findall(r"RUN pipeline[^\n]*?([\d.]+)\s*(?:s|sec|seconds)\b", Path(lf).read_text(errors="replace"))
        r = {"wall_s": round(wall, 1), "pipeline_s": float(m[-1]) if m else None, "peak_vram_gib": round(vm.peak / 1024, 2), "rc": rc}
        if rc == 0 and tmp.exists() and mux_audio(tmp, inp, final) == 0:
            r["out"] = probe(final)
        RESULTS["clips"].setdefault(sid, {})["relayvsr"] = r
        upload_file(lf)
        if r.get("out"):
            upload(final.name, final.read_bytes())
            log(f"relayvsr {sid} ok wall={wall:.0f}s pipeline={r['pipeline_s']}s peak={r['peak_vram_gib']}GiB out={r['out']}")
        else:
            log(f"relayvsr {sid} FAIL rc={rc} {wall:.0f}s\n" + tail(lf, 25))
        upload("enhance_results.json", json.dumps(RESULTS, ensure_ascii=False, indent=1).encode())


def windows(n):
    """Regenerate 每次只吃 124 帧：n<=124 一窗；更长时均匀铺多窗，相邻至少重叠 24 帧。"""
    if n < MIN_REAL:
        raise ValueError(f"{n} frames < {MIN_REAL}")
    if n <= WIN:
        return [0]
    k = math.ceil((n - WIN) / (WIN - MIN_OVERLAP)) + 1
    return [round(i * (n - WIN) / (k - 1)) for i in range(k)]


def stitch(starts, wins, src, n, dst):
    """各窗 1080p 结果在重叠段中部做 8 帧淡化拼接，裁到原帧数，再接回原片音轨。"""
    ins = " ".join(f"-i '{w}'" for w in wins) + f" -i '{src}'"
    if len(wins) == 1:
        cmd = (f"ffmpeg -nostdin -y -v error {ins} -map 0:v:0 -map 1:a:0 -c:v copy -c:a copy -movflags +faststart '{dst}'")
        return sh(cmd, LOGS / "ffmpeg.log")
    parts, prev = ["[0:v]settb=AVTB,setpts=PTS-STARTPTS[c0]"], "c0"
    for i in range(1, len(wins)):
        ts = (starts[i] + starts[i - 1] + WIN) // 2 - XFADE // 2          # 全片时间轴上淡化开始的帧
        parts.append(f"[{i}:v]trim=start_frame={ts - starts[i]},setpts=PTS-STARTPTS,settb=AVTB[t{i}]")
        parts.append(f"[{prev}][t{i}]xfade=transition=fade:duration={XFADE / 24:.6f}:offset={ts / 24:.6f}[c{i}]")
        prev = f"c{i}"
    parts.append(f"[{prev}]trim=end_frame={n},setpts=PTS-STARTPTS,format=yuv420p[v]")
    cmd = (f"ffmpeg -nostdin -y -v error {ins} -filter_complex \"{';'.join(parts)}\" -map '[v]' -map {len(wins)}:a:0 "
           f"-r 24 -c:v libx264 -preset slow -crf 14 -c:a copy -movflags +faststart '{dst}'")
    return sh(cmd, LOGS / "ffmpeg.log")


def run_regen(clips):
    att = "_flash_3_hub" if out("nvidia-smi --query-gpu=compute_cap --format=csv,noheader").startswith("9.") else "native"
    RESULTS["env"]["regen_attention"] = att          # FA3 hub 内核只支持 Hopper；Blackwell 用 PyTorch SDPA
    plan, lines = {}, []
    for c in clips:
        sid, n = c["id"], c["frames"]
        starts = windows(n); plan[sid] = {"starts": starts, "wins": [], "inputs": []}
        for k, s in enumerate(starts):
            wi, wo = IN / f"{sid}_w{k}.mp4", OUT / f"{sid}_w{k}_regen.mp4"
            e = min(s + WIN, n)
            if sh(f"ffmpeg -nostdin -y -v error -i '{IN / f'{sid}.mp4'}' -vf 'trim=start_frame={s}:end_frame={e},setpts=PTS-STARTPTS' "
                  f"-an -r 24 -c:v libx264 -crf 0 -preset fast -pix_fmt yuv420p '{wi}'", LOGS / "ffmpeg.log"):
                raise RuntimeError(f"window extract failed {sid} w{k}\n" + tail(LOGS / "ffmpeg.log"))
            plan[sid]["wins"].append(wo); plan[sid]["inputs"].append(wi)
            lines.append(json.dumps({"input": str(wi), "output": str(wo), "caption": c.get("caption", "")}, ensure_ascii=False))
    (ROOT / "regen_jobs.jsonl").write_text("\n".join(lines) + "\n")
    lf = LOGS / "regen.log"
    STAGE.update(now="regen", log=lf)
    cmd = (f"{ICV}/bin/python infer.py --weights {IC_DIR} --jobs {ROOT}/regen_jobs.jsonl --resolution 1080p --sampler up3 "
           f"--seed 0 --attention {att}")
    marks, done = [], threading.Event()

    def watch(vm):                                       # 日志每出一行阶段结果，就记下该段的显存峰值
        pos = 0
        while not done.wait(1):
            if not lf.exists():
                continue
            with open(lf, errors="replace") as f:
                f.seek(pos); new = f.read(); pos = f.tell()
            for line in new.splitlines():
                if any(k in line for k in ("encoded ", "model ready", " steps in ", " wrote ")):
                    marks.append({"line": line.strip()[:400], "peak_vram_gib": vm.mark(), "t": round(time.time() - t_run, 1)})
    t_run = time.time()
    with Vram() as vm:
        wt = threading.Thread(target=watch, args=(vm,), daemon=True); wt.start()
        rc = sh(cmd, lf, cwd=IC_DIR / "infer", env=dict(ENV, PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True"))
        time.sleep(1.5); done.set(); wt.join(5)
    wall = time.time() - t_run
    RESULTS["regen_run"] = {"rc": rc, "wall_s": round(wall, 1), "process_peak_vram_gib": round(vm.peak / 1024, 2), "stages": marks}
    upload_file(lf)
    if rc:
        log(f"regen FAIL rc={rc} {wall:.0f}s\n" + tail(lf, 30))
    for c in clips:
        sid = c["id"]; p = plan[sid]
        names = [str(w) for w in p["inputs"]] + [str(w) for w in p["wins"]]
        mine = [m for m in marks if any(nm in m["line"] for nm in names)]
        samp = [float(x) for m in mine for x in re.findall(r"steps in ([\d.]+) s", m["line"])]
        dec = [float(x) for m in mine for x in re.findall(r"decode ([\d.]+) s", m["line"])]
        r = {"windows": p["starts"], "sampling_s": samp, "decode_s": dec, "rc": rc,
             "peak_vram_gib": max([m["peak_vram_gib"] for m in mine] or [0]),
             "note": "wall_s = 本片各窗采样+解码；文本编码/模型加载为 4 片共用，见 regen_run.stages"}
        final = OUT / f"{sid}_regen.mp4"
        if all(Path(w).exists() for w in p["wins"]):
            t0 = time.time()
            if stitch(p["starts"], p["wins"], IN / f"{sid}.mp4", c["frames"], final) == 0:
                r["out"] = probe(final)
            r["stitch_s"] = round(time.time() - t0, 1)
        r["wall_s"] = round(sum(samp) + sum(dec) + r.get("stitch_s", 0), 1)
        RESULTS["clips"].setdefault(sid, {})["regen"] = r
        if r.get("out"):
            upload(final.name, final.read_bytes())
            log(f"regen {sid} ok windows={p['starts']} sampling={samp} decode={dec} peak={r['peak_vram_gib']}GiB out={r['out']}")
        else:
            log(f"regen {sid} FAIL (windows present={[Path(w).exists() for w in p['wins']]})\n" + tail(LOGS / "ffmpeg.log", 5))
    upload("enhance_results.json", json.dumps(RESULTS, ensure_ascii=False, indent=1).encode())


def main():
    for d in (ROOT, IN, OUT, LOGS):
        d.mkdir(parents=True, exist_ok=True)
    env = out("nvidia-smi --query-gpu=name,memory.total,compute_cap --format=csv,noheader; python3 --version; "
              "free -g | head -2; df -h /content | tail -1")
    RESULTS["env"]["machine"] = env
    log(f"lab start {MODEL}\n{env}")
    clips = json.loads(get("/lab/jobs", m=MODEL))
    for c in clips:                                       # 原片经 /lab/kf 取（assets/starcore/lab_kf_enhance/<id>.mp4）
        dst = IN / f"{c['id']}.mp4"
        if not dst.exists():
            dst.write_bytes(get("/lab/kf", timeout=300, p=c["input"]))
        if c.get("sha256"):
            h = out(f"sha256sum '{dst}' | cut -d' ' -f1")
            if h != c["sha256"]:
                raise RuntimeError(f"input {c['id']} sha256 mismatch")
    log(f"inputs ok: {[(c['id'], c['frames']) for c in clips]}")

    # 磁盘：RelayVSR 必须够；Regenerate 需另外 ~163GB 且结束后仍留 >=30GB，不够就只跑 RelayVSR
    venv_need = 0 if (LXV / ".enh_ok").exists() and (ICV / ".enh_ok").exists() else VENV_GB
    need_vsr = max(0.0, VSR_GB - du_gb(VSR_DIR)); need_ic = max(0.0, IC_GB - du_gb(IC_DIR))
    do_ic = free_gb() - need_vsr - need_ic - venv_need >= RESERVE_GB
    log(f"disk free={free_gb():.0f}GB need relayvsr={need_vsr:.0f} regen={need_ic:.0f} venvs={venv_need:.0f} -> regen {'on' if do_ic else 'SKIPPED'}")
    if free_gb() - need_vsr - venv_need < RESERVE_GB / 2:
        log("磁盘不够，连 RelayVSR 也放弃"); return

    ensure_uv(LOGS / "install_uv.log")                   # 只装一次，免得两个安装线程同时 pip install uv
    errs = {}
    def guard(name, *fs):
        def run():
            try:
                for f in fs:
                    f()
            except Exception as e:
                errs[name] = e; RESULTS["errors"].append(f"{name}: {e}"[:2000]); log(f"ERROR {name}: {e}")
        return run
    vsr_dl = threading.Event()
    def dl_vsr():
        try:
            download_vsr()
        finally:
            vsr_dl.set()
    def dl_ic():
        vsr_dl.wait()                                     # 先让 11GB 的 RelayVSR 独占带宽，再开始 163GB
        download_ic()
    th = {n: threading.Thread(target=guard(n, *fs)) for n, fs in
          [("install_lightx2v", [install_lightx2v]), ("download_relayvsr", [dl_vsr])] +
          ([("install_ic", [install_ic]), ("download_ic", [dl_ic])] if do_ic else [])}
    for t in th.values():
        t.start()

    stop = threading.Event()
    def progress():                                       # 每分钟回传进度，避免看起来像卡死
        while not stop.wait(60):
            gpu = out("nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader")
            busy = [n for n, t in th.items() if t.is_alive()]
            log(f"... {time.time() - T0:.0f}s stage={STAGE['now']} bg={busy} free={free_gb():.0f}GB "
                f"relayvsr={du_gb(VSR_DIR):.1f}GB regen={du_gb(IC_DIR):.1f}GB gpu={gpu} | "
                f"{tail(STAGE['log'], 1)[-200:] if STAGE['log'] else ''}")
    threading.Thread(target=progress, daemon=True).start()

    try:
        th["install_lightx2v"].join(); th["download_relayvsr"].join()
        if "install_lightx2v" in errs or "download_relayvsr" in errs:
            log("RelayVSR 准备失败，跳过")
        else:
            run_relayvsr(clips)
        if do_ic:
            STAGE.update(now="wait regen download", log=LOGS / "download_regen_ic.log")
            th["install_ic"].join(); th["download_ic"].join()
            if "install_ic" in errs or "download_ic" in errs:
                log("Regenerate-IC 准备失败，跳过")
            else:
                run_regen(clips)
    except Exception as e:
        RESULTS["errors"].append(f"main: {e}"[:2000]); log(f"ERROR main: {e}")
    finally:
        stop.set()
        RESULTS["total_wall_s"] = round(time.time() - T0)
        upload("enhance_results.json", json.dumps(RESULTS, ensure_ascii=False, indent=1).encode())
        for f in ("install_lightx2v.log", "install_ic.log", "ffmpeg.log"):
            upload_file(LOGS / f, tail_lines=300)
        for f in ("download_relayvsr.log", "download_regen_ic.log"):
            upload_file(LOGS / f, tail_lines=100)
        log(f"lab finished {time.time() - T0:.0f}s errors={RESULTS['errors']}")


main()
