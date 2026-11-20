"""长片 H3 队列：参考模式（多参考图）+ 首尾帧模式 + 上一镜尾帧接戏。

用法（项目根目录，Windows Python；入口只放进程内存）：
  $env:DRAMAPIE_ENTRY = "<本机画布入口>"
  python -X utf8 tools/film/h3_film_queue.py films/starcore/shots.json --budget films/starcore/budget.json [--shots id ...] [--scenes S02 S03] [--limit N]

shots.json 每项：
  id          镜号（改参数必须换新 ID，如 _v2）
  mode        "reference"（默认）或 "frames"
  refs        reference 模式的参考图列表（项目相对路径，按 Picture 1..N 的顺序）
  ref / last  frames 模式的首帧 / 尾帧
  chain_from  frames 模式可用：取该镜已完成原片的最后一帧作为首帧（接戏）
  prompt, seconds, resolution
回执写 renders/<id>/job.json，与 h3_queue.py 格式兼容。云机一次只跑一个任务（共用 renders/queue.lock）。
"""
import argparse
from film_config import FilmConfig, add_film_args, film_names
import hashlib
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import imageio_ffmpeg
import requests

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(HERE))
from h3_queue import BASE, open_canvas, valid, write  # noqa: E402
from boxlock import gpu_turn  # noqa: E402

R = ROOT / "renders"
FF = imageio_ffmpeg.get_ffmpeg_exe()
SIZES = {"480p": "854x480", "720p": "1280x720", "1080p": "1920x1080"}


def last_frame(video: Path, dest: Path):
    if not dest.exists():
        subprocess.run([FF, "-v", "error", "-y", "-sseof", "-0.08", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(dest)], check=True)
    return dest


class MachineDown(RuntimeError):
    pass


def is_dispatch_failure(msg: str, since_submit: float) -> bool:
    m = msg.lower()
    return any(k in m for k in ("dispatch_failed", "handshake", "connection refused", "connection terminated", "no machine",
                                "machine offline", "status_unavailable", "unavailable", "runtime disconnected")) or (since_submit < 25 and not m)


MAX_TRANSIENT_RETRIES = 3


def mime(p: Path):
    return "image/png" if p.suffix.lower() == ".png" else "image/jpeg"


def build_files(shot):
    mode = shot.get("mode", "reference")
    files = []
    hashes = []
    if mode == "reference":
        for rel in shot["refs"]:
            p = ROOT / rel
            b = p.read_bytes()
            files.append(("image[]", (p.name, b, mime(p))))
            hashes.append(hashlib.sha256(b).hexdigest())
    else:
        if shot.get("chain_from"):
            src = R / shot["chain_from"] / "raw.mp4"
            first = last_frame(src, R / shot["id"] / "chain_first.jpg")
        else:
            first = ROOT / shot["ref"]
        b = first.read_bytes()
        files.append(("first_frame", ("first.jpg", b, mime(first))))
        hashes.append(hashlib.sha256(b).hexdigest())
        if shot.get("last"):
            lp = ROOT / shot["last"]
            lb = lp.read_bytes()
            files.append(("last_frame", ("last.jpg", lb, mime(lp))))
            hashes.append(hashlib.sha256(lb).hexdigest())
    return mode, files, hashes


def refs_present(shot):
    paths = shot.get("refs", []) if shot.get("mode", "reference") == "reference" else [p for p in (shot.get("ref"), shot.get("last")) if p]
    return all((ROOT / p).is_file() for p in paths)


def farm_owned(shot):
    """派片服务（farm_server.py）已派给 Colab 工作机、租约有效或已完成的镜头，Box 不再接手。"""
    c = R / shot["id"] / "claim.json"
    if not c.exists() or (R / shot["id"] / "job.json").exists():
        return False
    try:
        st = json.loads(c.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return True
    return st.get("status") == "done" or (st.get("status") == "claimed" and st.get("lease_until", 0) > time.time())


def ready(shot):
    if shot.get("engine") == "ltx" or not refs_present(shot) or farm_owned(shot):
        return False
    dep = shot.get("chain_from")
    if not dep:
        return True
    st = R / dep / "job.json"
    return st.exists() and json.loads(st.read_text(encoding="utf-8")).get("status") == "completed" and valid(R / dep / "raw.mp4")


def run(s, shot, deadline):
    slug = shot["id"]
    folder = R / slug
    folder.mkdir(exist_ok=True)
    path, out = folder / "job.json", folder / "raw.mp4"
    state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if state.get("shot") and state["shot"] != shot:
        raise ValueError(f"{slug}: 镜头参数变更请使用新版本 ID")
    if state.get("status") == "completed" and valid(out):
        return "completed"
    if state.get("status") == "failed":
        return "failed"
    if time.time() + 150 > deadline:
        raise TimeoutError("剩余预算时间不足，结束队列")
    with gpu_turn(slug):
        if not state.get("remote_id"):
            mode, files, hashes = build_files(shot)
            state = {"shot": shot, "model": "minimax-h3", "request": state.get("request") or str(uuid.uuid4()),
                     "start": time.time(), "status": "prepared", "reference_sha256": hashes,
                     "dispatch_failures": state.get("dispatch_failures", [])}
            write(path, state)
            res = shot.get("resolution", "720p")
            data = dict(model="minimax-h3", prompt=shot["prompt"], seconds=str(shot.get("seconds", 6)), size=SIZES[res],
                        ratio="16:9", resolution_name=res, generate_audio="true", watermark="false", mode=mode)
            resp = s.post(BASE + "/v1/videos", data=data, files=files, headers={"x-request-id": state["request"]}, timeout=120)
            if resp.status_code == 409:
                taskid = resp.json().get("error", {}).get("task_id")
                if not taskid:
                    resp.raise_for_status()
            else:
                if resp.status_code >= 400:
                    print(f"{slug} submit http {resp.status_code}: {resp.text[:300]}", flush=True)
                resp.raise_for_status()
                obj = resp.json()
                taskid = obj.get("data", obj)["id"]
            state.update(remote_id=taskid, status="submitted", submitted=time.time())
            write(path, state)
            print(f"submitted {slug} {mode} {shot.get('seconds', 6)}s -> {taskid}", flush=True)
        url = BASE + "/v1/videos/" + state["remote_id"]
        while time.time() < deadline:
            r = s.get(url, timeout=30)
            r.raise_for_status()
            d = r.json()
            d = d.get("data", d)
            if d.get("status") in ("failed", "cancelled"):
                err = d.get("error") or {}
                msg = str(err.get("message") or "")[:300]
                elapsed = round(time.time() - state["start"], 1)
                if is_dispatch_failure(msg, time.time() - state.get("submitted", state["start"])) and \
                        len(state.get("dispatch_failures", [])) < MAX_TRANSIENT_RETRIES:
                    # 任务根本没到 GPU：保留历史，清掉任务号，同一镜号稍后重新提交
                    hist = state.get("dispatch_failures", []) + [{"remote_id": state["remote_id"], "message": msg, "at": time.time()}]
                    state.update(status="prepared", remote_id=None, request=str(uuid.uuid4()), dispatch_failures=hist)
                    write(path, state)
                    print(f"{slug} dispatch failed (云机未连通): {msg}", flush=True)
                    raise MachineDown(msg)
                state.update(status="failed", error=str(err.get("code") or "backend_error"), error_message=msg, elapsed=elapsed)
                write(path, state)
                print(f"{slug} failed {state['error']} {msg}", flush=True)
                return "failed"
            if d.get("status") == "completed" or d.get("video_url"):
                r = s.get(url + "/content", timeout=180, allow_redirects=False)
                if r.is_redirect:
                    loc = r.headers["Location"]
                    if urlsplit(loc).scheme != "https":
                        raise ValueError("不支持的下载重定向")
                    r = requests.get(loc, timeout=180)
                r.raise_for_status()
                tmp = folder / "download.mp4"
                tmp.write_bytes(r.content)
                if not valid(tmp):
                    raise ValueError(f"{slug} 成片解码失败")
                tmp.replace(out)
                state.update(status="completed", elapsed=round(time.time() - state["start"], 1), bytes=out.stat().st_size,
                             sha256=hashlib.sha256(out.read_bytes()).hexdigest())
                write(path, state)
                print(f"saved {slug} {state['elapsed']}s", flush=True)
                return "completed"
            time.sleep(3)
    raise TimeoutError("到了本轮预算截止时间，保留任务编号")


SCENE_ORDER = ["PILOT", "P01"] + [f"S{n:02d}" for n in range(1, 40)]


def load_queue(spec, order=None):
    """spec 可为单个 json 文件或目录（读取其中 *.json 的镜头数组），按片序排序。"""
    p = ROOT / spec
    files = sorted(p.glob("*.json")) if p.is_dir() else [p]
    items = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue  # 正在写入的文件，下一轮再读
        if isinstance(data, list):
            items += [x for x in data if isinstance(x, dict) and x.get("id") and x.get("prompt") and x.get("engine") != "ltx"]
    order = order if order is not None else SCENE_ORDER
    def key(x):
        sc = x.get("scene", "")
        return (order.index(sc) if sc in order else 999, x["id"])
    return sorted(items, key=key)


def main():
    ap = argparse.ArgumentParser()
    add_film_args(ap, multiple=True)
    ap.add_argument("queue", nargs="*", help="镜头文件或目录，可多个；按给出顺序优先")
    ap.add_argument("--budget", required=True)
    ap.add_argument("--shots", nargs="*")
    ap.add_argument("--scenes", nargs="*")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--watch", action="store_true", help="持续扫描新镜头和新参考图，直到预算截止或闲置超时")
    ap.add_argument("--idle-minutes", type=float, default=45)
    args = ap.parse_args()
    films = [FilmConfig(n) for n in film_names(args)]
    if len({f.prefix for f in films}) != len(films):
        ap.error("Films must have distinct render_prefix values")
    if not args.queue:
        ids = [s["id"] for f in films for s in f.load_shots()]
        if len(ids) != len(set(ids)):
            ap.error("Duplicate shot IDs across films")
    args.queue = args.queue or [str(f.shots) for f in films]
    orders = {f.shots.resolve(): ["PILOT"] + f.order for f in films}
    budget = json.loads((ROOT / args.budget).read_text(encoding="utf-8"))
    if budget["deadline_epoch"] <= time.time():
        sys.exit("本轮预算过期；重新核对余额和计费速率")
    session = open_canvas()
    finished = set()
    done = 0
    down_streak = 0
    last_progress = time.time()
    while True:
        items = []
        for spec in args.queue:
            items += load_queue(spec, orders.get((ROOT / spec).resolve(), ["PILOT"] + films[0].order))
        if args.shots:
            items = [i for i in items if i["id"] in args.shots]
        if args.scenes:
            items = [i for i in items if i.get("scene") in args.scenes]
        pending = [i for i in items if i["id"] not in finished]
        progressed = False
        for shot in pending:
            if not ready(shot):
                continue
            status = None
            for attempt in range(3):
                try:
                    status = run(session, shot, budget["deadline_epoch"])
                    break
                except (requests.ConnectionError, requests.Timeout):
                    if attempt == 2:
                        raise
                    time.sleep(8)
                except requests.HTTPError as exc:
                    code = exc.response.status_code if exc.response is not None else 0
                    if code == 401:
                        session = open_canvas()
                        continue
                    if code in (400, 413, 422):
                        print(f"[skip] {shot['id']} 请求被拒 http {code}", flush=True)
                        status = "rejected"
                        break
                    raise
                except ValueError as exc:
                    print(f"[skip] {shot['id']}: {exc}", flush=True)
                    status = "skipped"
                    break
                except MachineDown:
                    status = "machine_down"
                    break
            if status == "machine_down":
                down_streak += 1
                wait = min(60 * 2 ** (down_streak - 1), 900)
                print(f"[pause] 云机连接失败（连续 {down_streak} 次），{wait}s 后重试；请在 Box 面板确认视频机在线", flush=True)
                time.sleep(wait)
                last_progress = time.time()
                break
            down_streak = 0
            finished.add(shot["id"])
            progressed = True
            last_progress = time.time()
            if status == "completed":
                done += 1
            if args.limit and done >= args.limit:
                return
            break  # 每完成一镜重新读取镜头表，吸收新写好的场次与修订
        if progressed:
            continue
        if not args.watch:
            waiting = [p["id"] for p in pending]
            if waiting:
                print("以下镜头的参考图或上一镜未就绪：", waiting[:20], flush=True)
            return
        if time.time() - last_progress > args.idle_minutes * 60:
            print("闲置超时，结束队列", flush=True)
            return
        time.sleep(30)


if __name__ == "__main__":
    main()
