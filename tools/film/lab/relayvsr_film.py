"""Full-film RelayVSR worker; exec in Colab with B, T, W (vsr0of2).
One persistent venv process owns the runner. A first-clip resident failure exits
that process before retrying with the reference CLI, releasing all CUDA state.
Rebuild the staging manifest only when all shards are stopped.
"""
import json, os, re, shutil, subprocess, threading, time, urllib.parse, urllib.request
from pathlib import Path

B = globals().get("B") or os.environ["FARM_B"]
T = globals().get("T") or os.environ["FARM_T"]
W = globals().get("W") or os.environ.get("FARM_W", "lab")
MODEL = "vsr"
ROOT = Path("/content/vsr"); IN = ROOT / "in"; OUT = ROOT / "out"; LOGS = ROOT / "logs"
HF_HOME = "/content/hf"
LX, LXV = ROOT / "LightX2V", ROOT / "venv_lx"           # RelayVSR 推理框架
VSR_DIR = ROOT / "models/RelayVSR_X2"

LX_GIT, LX_REV = "https://github.com/ModelTC/LightX2V", "f2a56171bfe6555bd66a15d86e5c45c0d169add4"     # 2026-11-20 main
VSR_REPO, VSR_REV = "lightx2v/RelayVSR_X2", "bdaba6f33b6ec0b7f8a7d0c32c871e2539d1193b"
VSR_FILES = ["wan_x2.safetensors", "flash_x2.safetensors"]                              # 10.13 + 0.13 GB
VSR_GB = 10.3
LX_SKIP = {"sgl-kernel", "alibabacloud_dypnsapi20170525", "redis", "tos", "pymongo", "asyncpg", "aioboto3", "aio-pika",
           "modelscope", "swanlab", "decord", "qtorch"}      # 解析失败时的精简安装：去掉服务端/其它模型用的包
ENV = dict(os.environ, HF_HOME=HF_HOME, HF_XET_HIGH_PERFORMANCE="1", HF_XET_CHUNK_CACHE_SIZE_BYTES="0",
           PYTHONUNBUFFERED="1", MPLBACKEND="Agg")

import concurrent.futures, hashlib
RESULTS = {"env": {}, "downloads": {}}
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

def download_vsr():
    hf_download("relayvsr", f"from huggingface_hub import snapshot_download as s\n"
                f"s({VSR_REPO!r}, revision={VSR_REV!r}, local_dir={str(VSR_DIR)!r}, allow_patterns={VSR_FILES!r}, max_workers=8)\n",
                VSR_GB, VSR_DIR)

def lx_env():
    return dict(ENV, PYTHONPATH=str(LX), MOONCAKE_CONFIG_PATH=f"{LX}/configs/mooncake/mooncake_config.json",
                TOKENIZERS_PARALLELISM="false", PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True",
                PYTORCH_ALLOC_CONF="expandable_segments:True", DTYPE="BF16", SENSITIVE_LAYER_DTYPE="None",
                PROFILING_DEBUG_LEVEL="2", CUDA_VISIBLE_DEVICES="0")

def log(msg):
    # Never print request exceptions: they may include the authenticated URL.
    print(msg, flush=True)
    try:
        post('/lab/log', f'[{MODEL}] {msg}'.encode())
    except Exception:
        print('progress upload failed', flush=True)


def transfer(path, data=None, **query):
    for attempt in range(8):
        try:
            return get(path, timeout=600, **query) if data is None else post(path, data, timeout=600)
        except Exception:
            if attempt == 7:
                raise RuntimeError('farm transfer failed: ' + path) from None
            time.sleep(5 * (attempt + 1))


def hf_download(name, code, est_gb, d):
    # Public weights: no secret endpoint or token files are needed.
    script = ROOT / f'dl_{name}.py'
    script.write_text(code)
    for attempt in range(8):
        rc = sh(f"uv run --no-project --with 'huggingface-hub[hf_xet]==1.30.0' python {script}",
                LOGS / f'download_{name}.log')
        if not rc:
            return
        time.sleep(30)
    raise RuntimeError('weight download failed; inspect runtime download log')


def digest(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def inspect_video(p):
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-i', str(p), '-f', 'null', '-'],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-count_frames',
        '-show_streams', '-of', 'json', str(p)]))['streams']


def cli(inp, dst):
    return ['--model_cls', 'relayvsr_x2', '--task', 'sr', '--model_path', str(VSR_DIR),
            '--config_json', str(ROOT / 'relayvsr_x2_lab.json'), '--video_path', str(inp),
            '--sr_ratio', '2', '--save_result_path', str(dst), '--seed', '42']


def marker(job):
    return OUT / (job['id'] + '_' + job['sha256'] + '.uploaded.json')


def _upload(job, sid, final, meta):              # 后台上传：GPU 不等隧道
    try:
        data = final.read_bytes(); CH = 2 << 20      # 隧道会截断大请求：切 2MB 分块传，本机 vsr_assemble.py 按 sha256 拼回
        parts = [data[i:i + CH] for i in range(0, len(data), CH)]
        for k, part in enumerate(parts):
            transfer(f'/lab/upload/{MODEL}/{sid}.mp4.part{k:03d}', part)
        meta = dict(meta, parts=len(parts), size=len(data))
        transfer(f'/lab/upload/{MODEL}/{sid}.json', json.dumps(meta).encode())
        marker(job).write_text(json.dumps(meta))
        log(f'{sid} uploaded; inference={meta["inference_s"]:.1f}s wall={meta["wall_s"]:.1f}s')
    except Exception as e:
        log(f'{sid} upload FAIL (will retry on rerun): {e}')


def process_jobs(jobs, fallback=False):
    import concurrent.futures as _cf
    runner = None
    first = True
    pool = _cf.ThreadPoolExecutor(2)
    try:
        for job in jobs:
          if marker(job).exists():
                continue
          try:
            sid = job['id']; start = time.monotonic()
            inp, tmp, final = IN / f'{sid}.mp4', OUT / f'{sid}_2x.mp4', OUT / f'{sid}.mp4'
            if not inp.exists() or digest(inp) != job['sha256']:
                inp.write_bytes(transfer('/lab/kf', p=job['input']))
            if digest(inp) != job['sha256']:
                raise RuntimeError(f'{sid}: input checksum mismatch')
            source = inspect_video(inp)
            sv = next(s for s in source if s['codec_type'] == 'video')
            if (sv['width'], sv['height']) != (1344, 768):
                raise RuntimeError(f'{sid}: unexpected input dimensions')
            inference = time.monotonic()
            if fallback:
                with (LOGS / f'{sid}.log').open('a') as lf:
                    subprocess.run([str(LXV / 'bin/python'), '-m', 'lightx2v.infer', *cli(inp, tmp)],
                                   cwd=LX, env=lx_env(), stdout=lf, stderr=lf, check=True)
            else:
                try:
                    from lightx2v.utils.cli import parse_cli_inputs
                    from lightx2v.models.runners.runner_factory import build_runner
                    from lightx2v.models.runners.registry import get_model_spec
                    from lightx2v.utils.parallel import configure_nccl_graph
                    from lightx2v.utils.utils import validate_config_paths
                    args, config, request = parse_cli_inputs(cli(inp, tmp))
                    if runner is None:
                        configure_nccl_graph(config)
                        validate_config_paths(config)
                        runner = build_runner(config)
                        get_model_spec(config['model_cls']).prepare_runner(runner, args)
                    runner.run_request(runner.prepare_request(request))
                except Exception:
                    if first:
                        log('resident first clip failed; releasing process before CLI fallback')
                        return 75
                    raise
            inference_s = time.monotonic() - inference
            try:
                up = next(s for s in inspect_video(tmp) if s['codec_type'] == 'video')
            except Exception:
                if first and not fallback:
                    return 75
                raise
            if (up['width'], up['height']) != (2688, 1536) or up['nb_read_frames'] != sv['nb_read_frames']:
                if first and not fallback:
                    return 75
                raise RuntimeError(f'{sid}: 2x dimensions/frame count mismatch')
            first = False
            encode = time.monotonic()
            subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', str(tmp), '-i', str(inp),
                '-map', '0:v:0', '-map', '1:a:0', '-vf', 'scale=1920:1096:flags=lanczos',
                '-c:v', 'libx264', '-crf', '20', '-preset', 'slow', '-pix_fmt', 'yuv420p',
                '-c:a', 'copy', '-movflags', '+faststart', str(final)], check=True)
            streams = inspect_video(final)
            v = next(s for s in streams if s['codec_type'] == 'video')
            a = next(s for s in streams if s['codec_type'] == 'audio')
            sa = next(s for s in source if s['codec_type'] == 'audio')
            if (v['width'], v['height']) != (1920, 1096) or v['nb_read_frames'] != sv['nb_read_frames'] or a['codec_name'] != sa['codec_name']:
                raise RuntimeError(f'{sid}: output validation failed')
            meta = dict(id=sid, input_sha256=job['sha256'], output_sha256=digest(final),
                        mode='cli' if fallback else 'resident', inference_s=round(inference_s, 3),
                        encode_verify_s=round(time.monotonic()-encode, 3),
                        wall_s=round(time.monotonic()-start, 3), frames=int(v['nb_read_frames']),
                        revisions={'LightX2V': LX_REV, VSR_REPO: VSR_REV})
            while pool._work_queue.qsize() > 4:      # 上传积压时稍等，避免内存里堆太多
                time.sleep(2)
            pool.submit(_upload, job, sid, final, meta)
          except Exception as e:
            if first:
                raise
            log(f"{job['id']} FAIL, skipped: {type(e).__name__}: {str(e)[:200]}")
        pool.shutdown(wait=True)
        return 0
    finally:
        if runner is not None:
            runner.close()


def main():
    for d in (ROOT, IN, OUT, LOGS):
        d.mkdir(parents=True, exist_ok=True)
    match = re.fullmatch(r'vsr(\d+)of(\d+)', W)
    if not match or not 0 <= int(match[1]) < int(match[2]):
        raise ValueError('W must be vsr<index>of<count>, zero based')
    jobs = json.loads(transfer('/lab/jobs', m=MODEL))
    jobs = [j for i, j in enumerate(jobs) if j.get('index', i) % int(match[2]) == int(match[1])]
    if os.environ.get('VSR_CHILD'):
        return process_jobs(jobs, fallback=os.environ['VSR_CHILD'] == 'cli')
    start = time.monotonic(); stop = threading.Event()
    initial = sum(marker(j).exists() for j in jobs)
    def progress():
        while not stop.wait(60):
            done = sum(marker(j).exists() for j in jobs)
            log(f'done={done}/{len(jobs)} rate={(done-initial)*60/max(1,time.monotonic()-start):.2f} clips/min')
    threading.Thread(target=progress, daemon=True).start()
    try:
        if all(marker(j).exists() for j in jobs):
            log(f'done={len(jobs)}/{len(jobs)} (runtime receipts)'); return 0
        if free_gb() < 45:
            raise RuntimeError('need at least 45 GB free for environment, weights and outputs')
        ensure_uv(LOGS / 'install_uv.log')
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(install_lightx2v), pool.submit(download_vsr)]
            for future in futures:
                future.result()
        if out(f'git -C {LX} rev-parse HEAD') != LX_REV:
            raise RuntimeError('LightX2V checkout revision mismatch')
        cfg = json.loads((LX / 'configs/relayvsr/relayvsr_x2.json').read_text())
        cfg.update(video_codec='libx264', video_crf=16, ffmpeg_preset='veryfast')
        (ROOT / 'relayvsr_x2_lab.json').write_text(json.dumps(cfg))
        script = ROOT / 'relayvsr_film.py'
        script.write_bytes(transfer('/lab/file/relayvsr_film.py'))
        env = dict(lx_env(), FARM_B=B, FARM_T=T, FARM_W=W, VSR_CHILD='resident')
        # Credentials are passed only in process memory, never in source/arguments/logs.
        rc = subprocess.run([str(LXV / 'bin/python'), str(script)], cwd=LX, env=env).returncode
        if rc == 75:
            env['VSR_CHILD'] = 'cli'
            rc = subprocess.run([str(LXV / 'bin/python'), str(script)], cwd=LX, env=env).returncode
        log(f'finished rc={rc} done={sum(marker(j).exists() for j in jobs)}/{len(jobs)}')
        return rc
    finally:
        stop.set()


if __name__ == '__main__' or 'B' in globals():
    rc = main()
    if rc:
        raise SystemExit(rc)
