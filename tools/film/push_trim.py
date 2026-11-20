"""剪辑兜底：镜头里人脸开始明显放大（人物走近/推镜）之前就切走，但绝不切掉对白。

在 speech_cut.py 之后运行（它先写好对白出点），只会把 cut.json 的 out 往前提，不会往后延。
  python push_trim.py --film echo [--thr 1.4] [--min-len 3.0] [--dry-run]
判定：入点后前 0.75 秒的人脸高度中位数为基准，之后连续 3 个采样点（0.75 秒）都 >= 基准×thr，
第一个点就是"开始怼脸"的时刻。对白镜头的出点不早于语音能量结束 + 0.25 秒。
"""
import argparse, json, statistics, subprocess, sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from film_config import FilmConfig, ROOT
from zoom_check import face_h
from speech_cut import analyze

STEP = 0.25
TRIM_SIZES = {"ECU", "CU", "MCU", "MS", "OTS"}
W, H = 672, 384


def faces(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"fps={1 / STEP},scale={W}:{H}",
                          "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True).stdout
    n = len(raw) // (W * H)
    return [face_h(np.frombuffer(raw[i * W * H:(i + 1) * W * H], np.uint8).reshape(H, W)) for i in range(n)]


def push_time(fs, t_in, thr):
    i0 = int(round(t_in / STEP))
    base = [x for x in fs[i0:i0 + 3] if x]
    if len(base) < 2:
        return None, None
    b = statistics.median(base)
    for i in range(i0 + 3, len(fs) - 2):
        if all(x and x >= b * thr for x in fs[i:i + 3]):
            return i * STEP, b
    return None, b


def job(args):
    shot, raw, cut, thr, min_len = args
    fs = faces(raw)
    duration, speech_end = analyze(raw)
    t_in = float(cut.get("in", 0.25))
    cur = float(cut.get("out", min(duration, shot["seconds"] * 0.92)))
    t, base = push_time(fs, t_in, thr)
    talk = any(d.get("text") for d in shot.get("dialogue", []))
    floor = t_in + min_len
    if talk:
        floor = max(floor, speech_end + 0.25)
    row = dict(id=shot["id"], engine=shot.get("engine"), size=shot.get("shot_size"), dialogue=talk,
               base_face=base and round(base, 3), push_at=t, speech_end=round(speech_end, 3) if talk else None,
               old_out=round(cur, 3), new_out=None)
    # 只管人像镜头；远景里的人脸检测常是误报，人物从远处走近也是正常调度
    if t is not None and (shot.get("shot_size") or "").upper() in TRIM_SIZES:
        new = max(floor, t)
        if new < cur - 0.2:
            row["new_out"] = round(new, 3)
    return row


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--film", default="echo")
    ap.add_argument("--thr", type=float, default=1.4)
    ap.add_argument("--min-len", type=float, default=3.0)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    film = FilmConfig(a.film)
    cuts = json.loads(film.cuts.read_text(encoding="utf-8")) if film.cuts.exists() else {}
    work = [(s, ROOT / "renders" / s["id"] / "raw.mp4", cuts.get(s["id"], {}), a.thr, a.min_len)
            for s in film.load_shots() if (ROOT / "renders" / s["id"] / "raw.mp4").exists()
            and not cuts.get(s["id"], {}).get("drop")]
    with ProcessPoolExecutor(6) as ex:
        rows = list(ex.map(job, work))
    trimmed = [r for r in rows if r["new_out"] is not None]
    removed = sum(r["old_out"] - r["new_out"] for r in trimmed)
    report = dict(film=a.film, thr=a.thr, min_len=a.min_len, shots=len(rows), trimmed=len(trimmed),
                  seconds_removed=round(removed, 2), rows=rows)
    out = ROOT / f"renders/qa/{a.film}_push_trim.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    if not a.dry_run:
        for r in trimmed:
            c = cuts.setdefault(r["id"], {})
            c["out"] = r["new_out"]
            c["trim"] = "push"
        film.cuts.write_text(json.dumps(cuts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(rows)} shots; trim {len(trimmed)} ({removed:.1f}s removed); dialogue-protected pushes: "
          f"{sum(1 for r in rows if r['push_at'] is not None and r['new_out'] is None)} -> {out}")


if __name__ == "__main__":
    main()
