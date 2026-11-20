"""把 Colab 分块回传的 VSR 成片拼回来：renders/lab/vsr/<id>.mp4.partNNN + <id>.json(parts, size, output_sha256) → <id>.mp4。
用法：python3 tools/film/vsr_assemble.py [--watch]。只在全部分块到齐且 sha256 一致时写出，然后删掉分块。"""
import hashlib, json, sys, time
from pathlib import Path

D = Path(__file__).resolve().parents[2] / "renders/lab/vsr"


def once():
    n = 0
    for js in sorted(D.glob("*.json")):
        try:
            meta = json.loads(js.read_text())
        except Exception:
            continue
        k = meta.get("parts")
        if not k:
            continue
        parts = [D / f"{js.stem}.mp4.part{i:03d}" for i in range(k)]
        if not all(p.exists() for p in parts):
            continue
        data = b"".join(p.read_bytes() for p in parts)
        if len(data) != meta["size"] or hashlib.sha256(data).hexdigest() != meta["output_sha256"]:
            print("checksum mismatch, waiting for re-upload:", js.stem, flush=True)
            continue
        tmp = D / f"{js.stem}.mp4.tmp"
        tmp.write_bytes(data)
        tmp.replace(D / f"{js.stem}.mp4")
        for p in parts:
            p.unlink()
        n += 1
        print("assembled", js.stem, len(data), flush=True)
    return n


if __name__ == "__main__":
    once()
    while "--watch" in sys.argv:
        time.sleep(20)
        once()
