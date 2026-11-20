"""用 Antigravity CLI（agy，Gemini 内置生图）并行出参考图 / 关键帧，不占 Colab GPU。

用法（WSL）：
  python3 tools/film/gemini_images.py films/starcore/refs.json --out assets/starcore/refs -j 4 [--only id ...] [--redo id ...]
spec 每项：{"id", "prompt", "refs"?: [相对项目根的参考图路径]}。
每张图一次独立 agy 调用，在临时空目录里生成，校验后移入输出目录并写回执。
"""
import argparse
from film_config import FilmConfig, add_film_args, film_names
import concurrent.futures as cf
import hashlib
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def build_prompt(item, refs):
    lines = [
        "Use your built-in image generation tool to create exactly ONE 16:9 landscape image and save it in the current directory as out.png.",
        "Do not create or modify any other files. Do not run unrelated commands.",
    ]
    if refs:
        lines.append("Use these reference images (view them first) to keep identity, design, colors and materials exactly consistent:")
        for i, p in enumerate(refs, 1):
            lines.append(f"  Reference {i}: {p}")
    lines.append("Image description: " + item["prompt"])
    lines.append("When done, reply with the word DONE only.")
    return "\n".join(lines)


def run_one(item, out_dir: Path, timeout: int):
    for attempt in range(4):
        ident, status = _run_one(item, out_dir, timeout)
        if status.startswith("ok"):
            return ident, status
        time.sleep(20 * (attempt + 1))
    return ident, status


def _run_one(item, out_dir: Path, timeout: int):
    dest = out_dir / f"{item['id']}.png"
    refs = [str(ROOT / r) for r in item.get("refs", [])]
    work = Path(tempfile.mkdtemp(prefix=f"agy_{item['id']}_"))
    start = time.time()
    cmd = ["agy", "--dangerously-skip-permissions", "--print-timeout", f"{timeout}s"]
    for r in refs:
        cmd += ["--add-dir", str(Path(r).parent)]
    cmd += ["-p", build_prompt(item, refs)]
    try:
        proc = subprocess.run(cmd, cwd=work, capture_output=True, text=True, timeout=timeout + 60)
        png = work / "out.png"
        if not png.exists():
            cands = sorted(work.glob("*.png")) + sorted(work.glob("*.jpg"))
            png = cands[0] if cands else None
        if not png:
            return item["id"], f"FAILED no image ({proc.stdout[-200:].strip()} {proc.stderr[-200:].strip()})"
        if png.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
            conv = png.with_suffix(".conv.png")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(png), str(conv)], check=True)
            png = conv
        probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(png)], capture_output=True, text=True, check=True)
        size = tuple(int(x) for x in probe.stdout.strip().split(",")[:2])
        shutil.move(str(png), dest)
        receipt = {
            "generator": "agy (Gemini built-in image generation)",
            "prompt": item["prompt"],
            "references": [{"path": str(Path(r).relative_to(ROOT)).replace("\\", "/"), "sha256": hashlib.sha256(Path(r).read_bytes()).hexdigest()} for r in refs],
            "actual_size": list(size),
            "sha256": hashlib.sha256(dest.read_bytes()).hexdigest(),
            "elapsed": round(time.time() - start, 1),
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        dest.with_suffix(".json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
        return item["id"], f"ok {size} {receipt['elapsed']}s"
    except subprocess.TimeoutExpired:
        return item["id"], "FAILED timeout"
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    add_film_args(ap)
    ap.add_argument("spec", nargs="?")
    ap.add_argument("--out")
    ap.add_argument("-j", type=int, default=4)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--redo", nargs="*", default=[])
    ap.add_argument("--timeout", type=int, default=420)
    args = ap.parse_args()
    film = FilmConfig(args.film)
    args.spec = args.spec or str(film.workflow / "refs.json")
    items = json.loads((ROOT / args.spec).read_text(encoding="utf-8"))
    if args.only:
        items = [i for i in items if i["id"] in args.only]
    out_dir = ROOT / args.out if args.out else film.refs
    out_dir.mkdir(parents=True, exist_ok=True)
    todo = [i for i in items if i["id"] in args.redo or not (out_dir / f"{i['id']}.png").exists()]
    print(f"{len(todo)} images to generate with {args.j} workers", flush=True)
    # 依赖感知：参考图齐了的先跑；依赖其他新图的等前者落盘后再提交
    pending = list(todo)
    running = {}
    with cf.ThreadPoolExecutor(args.j) as pool:
        while pending or running:
            for item in list(pending):
                if len(running) >= args.j:
                    break
                if all((ROOT / r).is_file() for r in item.get("refs", [])):
                    pending.remove(item)
                    running[pool.submit(run_one, item, out_dir, args.timeout)] = item
            if not running:
                print("依赖缺失，无法继续：", [i["id"] for i in pending], flush=True)
                return
            done, _ = cf.wait(list(running), return_when=cf.FIRST_COMPLETED)
            for fut in done:
                running.pop(fut)
                ident, status = fut.result()
                print(ident, status, flush=True)

if __name__ == "__main__":
    main()
