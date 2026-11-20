"""给粗剪铺配乐：按 music_cues.json 把曲目放到对应场次，同期声（对白、拟音）出现时自动压低配乐，最后统一响度。

用法（WSL，项目根目录）：
  python3 tools/film/score_mix.py --name rough_latest
读取 videos/starcore/<name>.mp4 与 <name>.json，输出 videos/starcore/<name>_scored.mp4。画面直接复制，不重新编码。
"""
import argparse
from film_config import FilmConfig, add_film_args, film_names
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MUSIC = ROOT / "assets/starcore/music"
CUES = ROOT / "films/starcore/music_cues.json"
VID = ROOT / "videos/starcore"
OVERLAP = 2.5   # 相邻曲目交叠秒数
FADE_IN, FADE_OUT = 1.5, 3.0


def dur(p: Path) -> float:
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                                capture_output=True, text=True, check=True).stdout.strip())


def main():
    ap = argparse.ArgumentParser()
    add_film_args(ap)
    ap.add_argument("--name", default="rough_latest")
    ap.add_argument("--lufs", type=float, default=-16.0)
    ap.add_argument("--hd", action="store_true")
    ap.add_argument('--continuity', action='store_true', help='Require continuity production audio and preserve exact video duration')
    args = ap.parse_args()
    if args.continuity:
        config=FilmConfig(args.film)
        if args.name in ('final','draft'): ap.error('Continuity requires a distinct output name')
        if not (config.videos/f'{args.name}_continuity.json').exists(): ap.error('Run rough_cut --continuity first')
    global MUSIC, CUES, VID
    film = FilmConfig(args.film)
    MUSIC, CUES, VID = film.music, film.workflow / "music_cues.json", film.videos
    if args.hd and not args.name.endswith("_hd"):
        args.name += "_hd"
    video = VID / f"{args.name}.mp4"
    tl = json.loads((VID / f"{args.name}.json").read_text(encoding="utf-8"))
    total = tl["duration"]
    spans = {}
    for s in tl["shots"]:
        a = spans.setdefault(s["scene"], [s["start"], s["start"] + s["length"]])
        a[1] = s["start"] + s["length"]
    cues = json.loads(CUES.read_text(encoding="utf-8"))
    placed = []
    for c in cues:
        present = [spans[x] for x in c["scenes"] if x in spans]
        if not present:
            continue
        start = min(p[0] for p in present)
        end = min(total, max(p[1] for p in present) + OVERLAP)
        f = MUSIC / c["file"]
        avail = dur(f) - c.get("offset", 0)
        length = min(end - start, avail)
        if length < 3:
            continue
        placed.append((f, c.get("offset", 0), start, length, c.get("gain_db", -14)))
    if not placed:
        raise SystemExit("没有可放置的配乐")
    inputs = ["-i", str(video)]
    parts = []
    for i, (f, off, start, length, gain) in enumerate(placed, start=1):
        inputs += ["-i", str(f)]
        ms = int(start * 1000)
        parts.append(f"[{i}:a]atrim=start={off}:duration={length:.3f},asetpts=PTS-STARTPTS,aresample=48000,"
                     f"aformat=channel_layouts=stereo,afade=t=in:d={FADE_IN},afade=t=out:st={max(0, length - FADE_OUT):.3f}:d={FADE_OUT},"
                     f"volume={gain}dB,adelay={ms}|{ms}[m{i}]")
    n = len(placed)
    parts.append("".join(f"[m{i}]" for i in range(1, n + 1)) + f"amix=inputs={n}:normalize=0:duration=longest,apad,atrim=duration={total:.3f}[bed]")
    parts.append("[0:a]aresample=48000,asplit=2[dlg][key]")
    parts.append("[bed][key]sidechaincompress=threshold=0.035:ratio=5:attack=15:release=400:makeup=1[duck]")
    parts.append(f"[dlg][duck]amix=inputs=2:normalize=0:duration=first,loudnorm=I={args.lufs}:TP=-1.5:LRA=11,aresample=48000,alimiter=limit=0.79:attack=1:release=50:level=disabled[mix]")
    hd_limit = []
    if args.hd or args.continuity:
        from rough_cut import video_dur
        hd_limit = ["-t", f"{video_dur(video):.6f}"]
    out = VID / f"{args.name}_scored.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(parts), "-map", "0:v", "-map", "[mix]",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", *hd_limit, str(out)], check=True)
    print(f"{out.relative_to(ROOT)}  {n} cues  {total / 60:.1f} min")


if __name__ == "__main__":
    main()
