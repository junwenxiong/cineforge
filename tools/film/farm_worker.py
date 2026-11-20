# 《星核黎明》Colab H3 工作机：由 Colab 单元下载执行（exec），需事先定义 B（派片地址）、T（令牌）、W（机器名）。
# 启动 Box 自带的 vm_service.py（同一套 H3：ref 引擎 + ref4 LoRA 4 步 + sol-attn/ck 加速），循环领镜头、生成、回传成片。
import json, os, random, subprocess, threading, time, urllib.parse, urllib.request
from pathlib import Path

# exec in notebooks must not parse ipykernel arguments. Direct CLI accepts film filters.
import argparse
if not globals().get("B"):
    _ap = argparse.ArgumentParser()
    _g = _ap.add_mutually_exclusive_group()
    _g.add_argument("--film")
    _g.add_argument("--films")
    _args = _ap.parse_args()
    FILMS = _args.films or _args.film or os.environ.get("FILM", "")
else:
    FILMS = globals().get("FILMS", os.environ.get("FILM", ""))

B = globals().get("B") or os.environ["FARM_B"]
T = globals().get("T") or os.environ["FARM_T"]
W = globals().get("W") or os.environ.get("FARM_W", "colab")
C = Path("/content"); JOBS = C / "h3_jobs"; INPUT = C / "h3_input"; OUT = C / "h3_out"; STATUS = C / "h3_status.json"
BATCH = FILMS.split(",")[0] if FILMS else "starcore"  # Stable VM namespace; shot IDs are globally unique.
STATE = {"state": "boot", "done": 0, "failed": 0, "current": [], "gpu": ""}


def url(path, **q):
    q["t"] = T; q["w"] = W
    return f"{B}{path}?{urllib.parse.urlencode(q)}"


def req(path, data=None, timeout=60, **q):
    r = urllib.request.Request(url(path, **q), data=data, method="POST" if data is not None else "GET",
                               headers={"Content-Type": "application/octet-stream", "User-Agent": "starcore-farm"})
    with urllib.request.urlopen(r, timeout=timeout) as f:
        return f.status, f.read()


def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)


def service_alive():
    pid = C / ".h3_service.pid"
    return pid.exists() and sh(f"kill -0 $(cat {pid}) 2>/dev/null && echo y").stdout.strip() == "y"


def start_service():
    if service_alive():
        return
    for d in (JOBS, INPUT, OUT):
        d.mkdir(parents=True, exist_ok=True)
    sh("cd /content && nohup python3 /content/vm_service.py --idle 7200 --prewarm ref > /content/h3_service.log 2>&1 & echo $! > /content/.h3_service.pid")


def heartbeat_loop():
    while True:
        try:
            st = read_status()
            tail = sh("tail -n 2 /content/h3_service.log").stdout.strip()[-300:]
            info = dict(STATE, service=st.get("state"), service_alive=service_alive(), log=tail)
            req("/heartbeat", json.dumps(info).encode(), timeout=20)
        except Exception as e:
            print("heartbeat error", e, flush=True)
        time.sleep(30)


def submit(job):
    sid = job["id"]; names = []
    for r in job["refs"]:
        dest = INPUT / r["name"]
        cache = C / "ref_cache" / r["url"].replace("/", "_")   # 全片只有几十张参考图：每台机器只经隧道下载一次
        cache.parent.mkdir(exist_ok=True)
        for attempt in range(6):          # 隧道偶发断流（IncompleteRead / 502），重试
            try:
                if not cache.exists():
                    with urllib.request.urlopen(url(r["url"]), timeout=120) as f:
                        data = f.read()
                    tmp = cache.with_suffix(".part"); tmp.write_bytes(data); tmp.rename(cache)
                dest.write_bytes(cache.read_bytes())
                break
            except Exception as e:
                if attempt == 5:
                    raise
                print("ref retry", r["name"], e, flush=True); time.sleep(5 * (attempt + 1))
        names.append(r["name"])
    spec = {"batch": BATCH, "id": sid, "mode": "ref", "engine": "ref", "lora": "ref4", "steps": 4,
            "sampler": "res_multistep", "scheduler": "simple", "images": names, "prompt": job["prompt"],
            "w": 1344, "h": 768, "frames": int(job["seconds"]) * 24 + 1, "seed": random.randint(1, 2**31 - 1),
            "sparse": {"tau": 1.3, "start": 0.2}, "attn": "ck"}
    tmp = JOBS / f"{sid}.tmp"
    tmp.write_text(json.dumps(spec, ensure_ascii=False))
    tmp.rename(JOBS / f"{sid}.json")
    STATE["current"].append(sid)
    print("queued", sid, flush=True)


UPLOADED = C / "farm_uploaded.txt"


def read_status():
    try:
        return json.loads(STATUS.read_text()) if STATUS.exists() else {}
    except Exception:
        return {}


def final(rec):
    # 领到任务时 vm_service 先登记 {"ok": False, "phase": "preparing"}，生成结束才有 ok=True 或 error
    return bool(rec) and (rec.get("ok") is True or "error" in rec)


def mark_uploaded(sid):
    with UPLOADED.open("a") as f:
        f.write(sid + "\n")


def resume():
    """单元重跑时接回上一轮已提交、未回传的镜头。"""
    done = set(UPLOADED.read_text().split()) if UPLOADED.exists() else set()
    ids = {p.stem for p in JOBS.glob("*.json")} if JOBS.exists() else set()
    for name, rec in read_status().get("jobs", {}).items():
        if name.startswith(BATCH + "/") and rec.get("id") not in done:
            ids.add(rec["id"])
    STATE["current"] = sorted(ids - done)
    if STATE["current"]:
        print("resume", STATE["current"], flush=True)


def collect(sid):
    st = read_status()
    rec = st.get("jobs", {}).get(f"{BATCH}/{sid}")
    if not final(rec) or st.get("current") == f"{BATCH}/{sid}":
        return False
    if rec.get("ok"):
        mp4 = OUT / BATCH / f"{sid}.mp4"
        meta = {k: rec.get(k) for k in ("wall_sec", "sample_sec", "seed", "size", "frames", "lora", "steps", "engine", "comfy")}
        for attempt in range(4):
            try:
                req(f"/result/{sid}", mp4.read_bytes(), timeout=300, meta=json.dumps(meta))
                break
            except Exception as e:
                print("upload retry", sid, e, flush=True); time.sleep(10 * (attempt + 1))
        mark_uploaded(sid)
        STATE["done"] += 1
        print("done", sid, rec.get("wall_sec"), flush=True)
    else:
        STATE["failed"] += 1
        try:
            req(f"/fail/{sid}", str(rec.get("error", "unknown")).encode(), timeout=30)
        except Exception as e:
            print("fail report error", e, flush=True)
        mark_uploaded(sid)
        print("FAILED", sid, rec.get("error"), flush=True)
    STATE["current"].remove(sid)      # 回传完才移除，排空判断才准
    return True


def main():
    STATE["gpu"] = sh("nvidia-smi --query-gpu=name,memory.total --format=csv,noheader").stdout.strip()
    print("GPU:", STATE["gpu"], flush=True)
    for f in ("vm_service.py", "prompting.py", "h3kf_node.py"):
        with urllib.request.urlopen(url(f"/vm/{f}"), timeout=60) as r:
            (C / f).write_bytes(r.read())
    if sh("which uv").returncode != 0:
        sh("pip install -q uv")
    resume()
    if not globals().get("_HB_STARTED"):
        globals()["_HB_STARTED"] = True
        threading.Thread(target=heartbeat_loop, daemon=True).start()
    start_service()
    STATE["state"] = "running"
    empty_since = None
    while True:
        for sid in list(STATE["current"]):
            try:
                collect(sid)
            except Exception as e:
                print("collect error", sid, e, flush=True)
        if not service_alive():
            print("service died; tail:", sh("tail -n 20 /content/h3_service.log").stdout, flush=True)
            STATE["state"] = "service_restart"
            start_service(); time.sleep(20)
            STATE["state"] = "running"
        if len(STATE["current"]) < 2:      # 正在生成 1 个 + 预排 1 个，GPU 不空等
            try:
                code, body = req("/claim", b"", timeout=60, **({"films": FILMS} if FILMS else {}))
            except Exception as e:
                print("claim error", e, flush=True); time.sleep(15); continue
            if code == 200 and body:
                job = json.loads(body)
                try:
                    submit(job); empty_since = None
                except Exception as e:   # 领到了但交不出去：退回派片服务，主循环不退出
                    print("submit failed", job["id"], e, flush=True)
                    try:
                        req(f"/fail/{job['id']}", f"worker submit failed: {e}".encode(), timeout=30)
                    except Exception:
                        pass
                    time.sleep(10)
                continue
            if not STATE["current"]:
                empty_since = empty_since or time.time()
                STATE["state"] = "idle"
                if time.time() - empty_since > 900:
                    print("no more shots; exiting", flush=True)
                    STATE["state"] = "finished"
                    req("/heartbeat", json.dumps(STATE).encode(), timeout=20)
                    return
        time.sleep(5)


main()
