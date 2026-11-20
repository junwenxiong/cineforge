"""用 Box 的 qwen-image-2.1 逐张生成参考图（文生图或参考图编辑）。

用法（项目根目录，Windows Python）：
  $env:DRAMAPIE_ENTRY = "<本机画布入口，仅放内存>"
  python -X utf8 tools/film/gen_refs.py films/starcore/refs.json [--only id1 id2] [--redo id]

refs.json 每项：{"id", "prompt", "size"?: "1280x720", "refs"?: ["assets/..png"], "out_dir"?: "assets/starcore/refs"}
已存在的输出跳过；回执写 <id>.json（提示词、参考哈希、耗时、实际像素），不含任何凭据。
"""
import argparse
from film_config import FilmConfig, add_film_args, film_names
import base64
import hashlib
import io
import json
import sys
import time
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(HERE))
from h3_queue import BASE, open_canvas  # noqa: E402
from boxlock import gpu_turn  # noqa: E402


def generate(session, item, out_dir: Path):
    out = out_dir / f"{item['id']}.png"
    fields = {
        "model": "qwen-image-2.1",
        "prompt": item["prompt"],
        "n": 1,
        "response_format": "b64_json",
        "output_format": "png",
        "size": item.get("size", "1280x720"),
    }
    refs = [ROOT / r for r in item.get("refs", [])]
    start = time.time()
    with gpu_turn(item["id"]):
        if refs:
            files = [("image[]" if len(refs) > 1 else "image", (p.name, p.read_bytes(), "image/png" if p.suffix == ".png" else "image/jpeg")) for p in refs]
            resp = session.post(BASE + "/v1/images/edits", data=fields, files=files, timeout=(10, 900))
        else:
            resp = session.post(BASE + "/v1/images/generations", json=fields, timeout=(10, 900))
    resp.raise_for_status()
    data = resp.json()
    entry = (data.get("data") or data.get("images") or data.get("results"))[0]
    if entry.get("b64_json"):
        raw = base64.b64decode(entry["b64_json"], validate=True)
    else:
        import requests
        raw = requests.get(entry["url"], timeout=120).content
    with Image.open(io.BytesIO(raw)) as pic:
        pic.load()
        size = pic.size
    tmp = out.with_suffix(".tmp")
    tmp.write_bytes(raw)
    tmp.replace(out)
    receipt = {
        "model": "qwen-image-2.1",
        "prompt": item["prompt"],
        "requested_size": fields["size"],
        "actual_size": list(size),
        "references": [{"path": str(p.relative_to(ROOT)).replace("\\", "/"), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in refs],
        "sha256": hashlib.sha256(raw).hexdigest(),
        "elapsed": round(time.time() - start, 1),
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    out.with_suffix(".json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {out.name} {size} in {receipt['elapsed']}s", flush=True)


def main():
    ap = argparse.ArgumentParser()
    add_film_args(ap)
    ap.add_argument("spec", nargs="?")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--redo", nargs="*", default=[])
    args = ap.parse_args()
    film = FilmConfig(args.film)
    args.spec = args.spec or str(film.workflow / "refs.json")
    items = json.loads((ROOT / args.spec).read_text(encoding="utf-8"))
    if args.only:
        items = [i for i in items if i["id"] in args.only]
    session = open_canvas()
    for item in items:
        out_dir = ROOT / item.get("out_dir", str(film.refs))
        out_dir.mkdir(parents=True, exist_ok=True)
        if (out_dir / f"{item['id']}.png").exists() and item["id"] not in args.redo:
            continue
        for attempt in range(3):
            try:
                generate(session, item, out_dir)
                break
            except Exception as exc:  # 网络或后端偶发错误：记录后重试，第三次放弃该张
                print(f"[warn] {item['id']} attempt {attempt + 1}: {type(exc).__name__}: {str(exc)[:200]}", flush=True)
                time.sleep(15)


if __name__ == "__main__":
    main()
