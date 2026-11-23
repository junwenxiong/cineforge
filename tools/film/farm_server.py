"""《星核黎明》派片服务：把镜头分给额外的 Colab H3 机器，并收回成片。

Box 队列（h3_film_queue.py）从片头往后拍；本服务从片尾往前派，同一镜号只交给一个入口：
  - 已有 renders/<id>/job.json 的镜头（Box 已接手或已完成）不派；
  - 派出时写 renders/<id>/claim.json（租约，默认 25 分钟），Box 队列遇到有效租约会跳过。
Colab 端运行 /boot.py，由它启动 Box 自带的 vm_service.py（与 Box 云机同一套 H3 配置）。

用法（WSL，项目根目录）：
  python3 tools/film/farm_server.py --port 8765
令牌每次启动随机生成，写入 renders/farm/token（仅本机），所有请求须带 ?t=<令牌>。
"""
import argparse
import os
from film_config import FilmConfig, add_film_args, film_names
import hashlib
import json
import secrets
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SHOTS = ROOT / "films/starcore/shots"
R = ROOT / "renders"
FARM = R / "farm"
VM = Path(os.environ["CINEFORGE_BOX_VM_DIR"]) if os.environ.get("CINEFORGE_BOX_VM_DIR") else None
FILMS = [FilmConfig("starcore")]
LEASE = 25 * 60
LOCK = threading.Lock()
TOKEN = ""
WORKERS = {}
SECRETS = {}


def log(*a):
    line = time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a)
    print(line, flush=True)
    with (FARM / "farm.log").open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_env(path):
    """Minimal .env reader (KEY=VALUE, # comments). Real environment variables win."""
    import os
    vals = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip().strip("'\"")
    return {k: os.environ.get(k) or v for k, v in vals.items()}


def _studio_h3_shots():
    qfile = FARM / "studio_h3_queue.json"
    if not qfile.is_file():
        return []
    try:
        data = json.loads(qfile.read_text(encoding="utf-8"))
        return [s for s in data if isinstance(s, dict) and s.get("id")] if isinstance(data, list) else []
    except Exception:
        return []


def all_shots():
    items = []
    for film in FILMS:
        items += film.load_shots()
    ids = [s["id"] for s in items]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate shot IDs across films")
    seen = set(ids)
    for s in _studio_h3_shots():
        if s["id"] not in seen:
            seen.add(s["id"])
            items.append(s)
    return items


def claim_state(sid):
    c = R / sid / "claim.json"
    if not c.exists():
        return None
    try:
        return json.loads(c.read_text(encoding="utf-8"))
    except Exception:
        return None


def claimable(shot):
    if shot.get("engine") == "ltx":
        return False
    sid = shot["id"]
    if (R / sid / "job.json").exists():
        return False
    c = claim_state(sid)
    if c and c.get("status") == "done":
        return False
    if c and c.get("lease_until", 0) > time.time():
        return False
    if c and c.get("attempts", 0) >= 3:
        return False
    return all((ROOT / r).is_file() for r in shot.get("refs", []))


def drained(worker):
    f = FARM / "drain"
    return f.exists() and worker in f.read_text().split()


def claim(worker, selected=None):
    if drained(worker):
        return None
    with LOCK:
        all_shots()  # Validate shared namespace before writing any lease.
        studio_candidates = _studio_h3_shots() if (selected is None or "studio" in selected) else []
        film_candidates = [s for film in FILMS if selected is None or film.name in selected
                           for s in reversed(film.load_shots())]
        candidates = studio_candidates + film_candidates
        for shot in candidates:
            if not claimable(shot):
                continue
            sid = shot["id"]
            d = R / sid
            d.mkdir(exist_ok=True)
            prev = claim_state(sid) or {}
            st = {"worker": worker, "at": time.time(), "lease_until": time.time() + LEASE, "status": "claimed",
                  "attempts": prev.get("attempts", 0) + 1, "history": prev.get("history", [])}
            (d / "claim.json").write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
            if (d / "job.json").exists():   # Box 恰好同时接手：让给 Box
                (d / "claim.json").unlink()
                continue
            refs = [{"name": f"{sid}_{k}{Path(r).suffix}", "url": "/ref/" + urllib.parse.quote(r)} for k, r in enumerate(shot["refs"])]
            log("claim", sid, "->", worker)
            return {"id": sid, "prompt": shot["prompt"], "seconds": shot["seconds"], "refs": refs}
    return None


def finish(sid, worker, data, meta):
    d = R / sid
    with LOCK:
        if (d / "job.json").exists() and json.loads((d / "job.json").read_text(encoding="utf-8")).get("status") == "completed":
            log("dup result ignored", sid)
            return
        tmp = d / "farm_download.mp4"
        tmp.write_bytes(data)
        if subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-i", str(tmp), "-f", "null", "-"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
            tmp.unlink()            # 传输截断或损坏：拒收，工作机会重传；不写 job.json，免得 Box 判定无效再重拍
            log("bad upload rejected", sid, "from", worker, f"{len(data) / 1e6:.1f}MB")
            raise ValueError("corrupt upload")
        shot = next(s for s in all_shots() if s["id"] == sid)
        c = claim_state(sid) or {}
        tmp.replace(d / "raw.mp4")
        job = {"shot": shot, "model": "minimax-h3", "via": f"colab-farm:{worker}", "status": "completed",
               "start": c.get("at"), "elapsed": round(time.time() - c.get("at", time.time()), 1),
               "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "vm": meta}
        (d / "job.json").write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        c.update(status="done", done_at=time.time())
        (d / "claim.json").write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
    log("saved", sid, "from", worker, f"{len(data) / 1e6:.1f}MB", "vm_wall", meta.get("wall_sec"))


def fail(sid, worker, err):
    with LOCK:
        c = claim_state(sid) or {}
        c["history"] = c.get("history", []) + [{"worker": worker, "error": err[:400], "at": time.time()}]
        c.update(status="failed", lease_until=0)
        (R / sid / "claim.json").write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
    log("fail", sid, worker, err[:200])


class H(BaseHTTPRequestHandler):
    def _ok(self, body=b"", ctype="application/json", code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _auth(self):
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        if q.get("t", [""])[0] != TOKEN:
            self._ok(b"forbidden", "text/plain", 403)
            return None
        return q

    def do_GET(self):
        q = self._auth()
        if q is None:
            return
        path = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
        if path == "/boot.py":
            return self._ok((HERE / "farm_worker.py").read_bytes(), "text/x-python")
        if path.startswith("/vm/") and path[4:] in ("vm_service.py", "prompting.py", "h3kf_node.py"):
            if VM is None or not (VM / path[4:]).is_file():
                return self._ok(b"Set CINEFORGE_BOX_VM_DIR to your licensed Box VM directory", "text/plain", 503)
            return self._ok((VM / path[4:]).read_bytes(), "text/x-python")
        if path.startswith("/ref/"):
            p = (ROOT / path[5:]).resolve()
            if (ROOT / "assets").resolve() not in p.parents or not p.is_file():
                return self._ok(b"not found", "text/plain", 404)
            return self._ok(p.read_bytes(), "image/png")
        if path == "/lab/jobs":      # 模型测试任务单 renders/farm/lab_jobs[_<m>].json，与正片队列无关
            m = q.get("m", [""])[0]
            f = FARM / (f"lab_jobs_{m}.json" if re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_-]*", m) else "lab_jobs.json")
            return self._ok(f.read_bytes())
        if path == "/lab/kf" :       # Legacy lab assets, configured films' LTX staging dirs, and Studio user jobs
            f = (ROOT / q.get("p", [""])[0]).resolve()
            legacy = f.parent.name.startswith("lab_kf_") and (ROOT / "assets/starcore").resolve() in f.parents
            staged = any(f.parent == (film.assets / "lab_kf_ltx").resolve()
                         and film.assets.resolve() in f.parents for film in FILMS)
            studio_staged = (
                (ROOT / "assets").resolve() in f.parents
                and f.parent.name in ("lab_kf_ltx", "refs")
                and f.parent.parent.name.startswith("studio_")
                and f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
            )
            if not f.is_file() or not (legacy or staged or studio_staged):
                return self._ok(b"not found", "text/plain", 404)
            ctype = "image/jpeg" if f.suffix.lower() in (".jpg", ".jpeg") else "image/png"
            return self._ok(f.read_bytes(), ctype)
        if path == "/lab/secret":    # 只在内存里的 HF 令牌，供 Colab 下载授权模型
            return self._ok(SECRETS.get("hf", "").encode(), "text/plain")
        if path == "/lab/src":       # 本机下好的原片或访客上传视频，云机直连拿不到时经此取
            f = (ROOT / q.get("p", [""])[0]).resolve()
            sources_ok = (ROOT / "sources").resolve() in f.parents and f.is_file()
            uploads_ok = (ROOT / "studio" / "data" / "uploads").resolve() in f.parents and f.is_file() and f.suffix.lower() == ".mp4"
            if not (sources_ok or uploads_ok):
                return self._ok(b"not found", "text/plain", 404)
            return self._ok(f.read_bytes(), "video/mp4")
        if path.startswith("/lab/file/"):
            f = (HERE / "lab" / path[len("/lab/file/"):]).resolve()
            if HERE / "lab" not in f.parents or not f.is_file():
                return self._ok(b"not found", "text/plain", 404)
            return self._ok(f.read_bytes(), "text/plain")
        if path == "/status":
            return self._ok(json.dumps(WORKERS, ensure_ascii=False).encode())
        self._ok(b"not found", "text/plain", 404)

    def do_POST(self):
        q = self._auth()
        if q is None:
            return
        path = urllib.parse.urlsplit(self.path).path
        worker = q.get("w", ["?"])[0][:40]
        n = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(n) if n else b""
        if path == "/claim":
            WORKERS.setdefault(worker, {})["last_claim"] = time.time()
            job = claim(worker, q["films"][0].split(",") if q.get("films") else None)
            return self._ok(json.dumps(job).encode()) if job else self._ok(b"", code=204)
        if path == "/heartbeat":
            info = json.loads(body or b"{}")
            prev = WORKERS.get(worker, {}).get("state")
            WORKERS[worker] = dict(WORKERS.get(worker, {}), **info, seen=time.time())
            if info.get("state") != prev:
                log("worker", worker, "state", info.get("state"), info.get("gpu", ""))
            return self._ok(b"{}")
        if path.startswith("/result/"):
            sid = path.split("/")[2]
            meta = json.loads(urllib.parse.unquote(q.get("meta", ["{}"])[0]))
            try:
                finish(sid, worker, body, meta)
            except ValueError:
                return self._ok(b"corrupt", "text/plain", 500)
            return self._ok(b"{}")
        if path.startswith("/lab/upload/"):   # 测试成片和日志：renders/lab/<模型>/<文件名>
            parts = [x for x in path[len("/lab/upload/"):].split("/") if x and x not in (".", "..")]
            d = R / "lab" / parts[0]
            d.mkdir(parents=True, exist_ok=True)
            (d / parts[-1]).write_bytes(body)
            log("lab upload", "/".join(parts), f"{len(body) / 1e6:.2f}MB", "from", worker)
            return self._ok(b"{}")
        if path == "/lab/setsecret":   # 仅本机直连可设置（经隧道的请求带 Cf-Ray 头，拒绝）
            if self.headers.get("Cf-Ray") or self.client_address[0] != "127.0.0.1":
                return self._ok(b"forbidden", "text/plain", 403)
            SECRETS["hf"] = body.decode().strip()
            log("lab secret set (memory only)")
            return self._ok(b"{}")
        if path == "/lab/log":
            with (FARM / "lab.log").open("a", encoding="utf-8") as f:
                f.write(time.strftime("%H:%M:%S ") + f"[{worker}] " + body.decode("utf-8", "replace") + "\n")
            return self._ok(b"{}")
        if path.startswith("/fail/"):
            fail(path.split("/")[2], worker, body.decode("utf-8", "replace"))
            return self._ok(b"{}")
        self._ok(b"not found", "text/plain", 404)

    def log_message(self, *a):
        pass


def main():
    global TOKEN, ROOT, R, FARM, FILMS
    ap = argparse.ArgumentParser()
    add_film_args(ap, multiple=True)
    ap.add_argument("--root", type=Path, default=ROOT, help="Isolated project root for local tests")
    ap.add_argument("--farm-dir", type=Path, help="Alternate farm state directory")
    ap.add_argument("--token-env", help="Read token from environment; never write it to disk")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--reuse-token", action="store_true", help="沿用 renders/farm/token（重启时不打断已在跑的工作机）")
    args = ap.parse_args()
    ROOT = args.root.resolve()
    R = ROOT / "renders"
    FARM = args.farm_dir or R / "farm"
    FILMS = [FilmConfig(n, ROOT) for n in film_names(args)]
    if len({f.prefix for f in FILMS}) != len(FILMS):
        ap.error("Films must have distinct render_prefix values")
    all_shots()
    R.mkdir(parents=True, exist_ok=True)
    FARM.mkdir(parents=True, exist_ok=True)
    tf = FARM / "token"
    if args.token_env:
        import os
        TOKEN = os.environ[args.token_env]
        if not TOKEN: ap.error("Farm token must not be empty")
    else:
        TOKEN = tf.read_text().strip() if args.reuse_token and tf.exists() else secrets.token_urlsafe(24)
        tf.write_text(TOKEN)
    hf = load_env(ROOT / ".env").get("HF_TOKEN", "")
    if hf:
        SECRETS["hf"] = hf
        log("lab secret loaded from .env (memory only)")
    log("farm server on", args.port)
    ThreadingHTTPServer(("127.0.0.1", args.port), H).serve_forever()


if __name__ == "__main__":
    main()
