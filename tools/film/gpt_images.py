"""用局域网 Codex 中转（OpenAI 兼容接口）的 gpt-image 并行出参考图，不占 Colab GPU。

用法（WSL，项目根目录）：
  python3 tools/film/gpt_images.py films/starcore/refs.json --out assets/starcore/refs -j 4 [--only id ...] [--redo id ...]
spec 每项：{"id", "prompt", "refs"?: [项目相对路径]}。有 refs 走 /v1/images/edits，否则走 /v1/images/generations。
Endpoint: CINEFORGE_IMAGE_BASE_URL; key: OPENAI_API_KEY (process environment only).
依赖其他新图的条目，等被依赖的图落盘后再提交。
"""
import argparse
from film_config import FilmConfig, add_film_args, film_names
import base64
import concurrent.futures as cf
import hashlib
import json
import re
import subprocess
import time
import uuid
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CODEX = Path.home() / ".codex"
PORTRAIT = {"lin", "zhou", "qin", "mk1", "mk2", "panshi", "liefeng", "queling"}


def relay():
    import os
    base = os.environ.get("CINEFORGE_IMAGE_BASE_URL", "https://api.openai.com").rstrip("/")
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("Set OPENAI_API_KEY in the process environment")
    return base, key


def size_for(item):
    if item.get("gpt_size"):
        return item["gpt_size"]
    return "1024x1536" if item["id"] in PORTRAIT else "1536x1024"


def multipart(fields, files):
    boundary = uuid.uuid4().hex
    out = bytearray()
    for k, v in fields.items():
        out += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    for name, path in files:
        mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        out += f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{path.name}"\r\nContent-Type: {mime}\r\n\r\n'.encode()
        out += path.read_bytes() + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


def call(base, key, item, model, quality, timeout):
    refs = [ROOT / r for r in item.get("refs", [])]
    fields = {"model": model, "prompt": item["prompt"], "n": 1, "size": size_for(item), "quality": quality}
    if refs:
        body, ctype = multipart(fields, [("image[]", p) for p in refs])
        url = base + "/v1/images/edits"
    else:
        body, ctype = json.dumps(fields).encode(), "application/json"
        url = base + "/v1/images/generations"
    req = urllib.request.Request(url, data=body, headers={"Authorization": "Bearer " + key, "Content-Type": ctype})
    with urllib.request.urlopen(req, timeout=timeout) as f:
        data = json.loads(f.read())
    it = data["data"][0]
    raw = base64.b64decode(it["b64_json"]) if it.get("b64_json") else urllib.request.urlopen(it["url"], timeout=120).read()
    return raw, refs


def run_one(item, out_dir, model, quality, timeout):
    base, key = relay()
    dest = out_dir / f"{item['id']}.png"
    last = ""
    for attempt in range(4):
        start = time.time()
        try:
            raw, refs = call(base, key, item, model, quality, timeout)
            tmp = dest.with_suffix(".tmp.png")
            tmp.write_bytes(raw)
            if raw[:8] != b"\x89PNG\r\n\x1a\n":
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(tmp), str(dest)], check=True)
                tmp.unlink()
            else:
                tmp.replace(dest)
            probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                                    "-of", "csv=p=0", str(dest)], capture_output=True, text=True, check=True)
            size = [int(x) for x in probe.stdout.strip().split(",")[:2]]
            receipt = {
                "generator": f"{model} via Codex LAN relay", "quality": quality, "requested_size": size_for(item),
                "actual_size": size, "prompt": item["prompt"],
                "references": [{"path": str(p.relative_to(ROOT)).replace("\\", "/"), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in refs],
                "sha256": hashlib.sha256(dest.read_bytes()).hexdigest(), "elapsed": round(time.time() - start, 1),
                "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            dest.with_suffix(".json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
            return item["id"], f"ok {size[0]}x{size[1]} {receipt['elapsed']}s"
        except urllib.error.HTTPError as e:
            last = f"http {e.code} {e.read()[:200]!r}"
            if e.code in (400, 401, 403):
                break
        except Exception as e:  # 网络或中转偶发错误，退避重试
            last = f"{type(e).__name__}: {str(e)[:200]}"
        time.sleep(15 * (attempt + 1))
    return item["id"], "FAILED " + last


def main():
    ap = argparse.ArgumentParser()
    add_film_args(ap)
    ap.add_argument("spec", nargs="?")
    ap.add_argument("--out")
    ap.add_argument("-j", type=int, default=4)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--redo", nargs="*", default=[])
    ap.add_argument("--model", default="gpt-image-2")
    ap.add_argument("--quality", default="high")
    ap.add_argument("--timeout", type=int, default=420)
    args = ap.parse_args()
    film = FilmConfig(args.film)
    args.spec = args.spec or str(film.workflow / "refs.json")
    items = json.loads((ROOT / args.spec).read_text(encoding="utf-8"))
    if args.only:
        items = [i for i in items if i["id"] in args.only]
    out_dir = ROOT / args.out if args.out else film.refs
    out_dir.mkdir(parents=True, exist_ok=True)
    pending = [i for i in items if i["id"] in args.redo or not (out_dir / f"{i['id']}.png").exists()]
    print(f"{len(pending)} images, {args.j} workers, {args.model}/{args.quality}", flush=True)
    running = {}
    with cf.ThreadPoolExecutor(args.j) as pool:
        while pending or running:
            for item in list(pending):
                if len(running) >= args.j:
                    break
                if all((ROOT / r).is_file() for r in item.get("refs", [])):
                    pending.remove(item)
                    running[pool.submit(run_one, item, out_dir, args.model, args.quality, args.timeout)] = item
            if not running:
                print("依赖缺失，无法继续：", [i["id"] for i in pending], flush=True)
                return
            done, _ = cf.wait(list(running), return_when=cf.FIRST_COMPLETED)
            for fut in done:
                running.pop(fut)
                print(*fut.result(), flush=True)


if __name__ == "__main__":
    main()
