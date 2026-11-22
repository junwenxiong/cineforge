"""《星核黎明》粗剪：按片序拼接已完成的 H3 镜头，掐头去尾、遮幅 2.39:1、保留同期声。

用法（WSL，项目根目录）：
  python3 tools/film/rough_cut.py                      # 全片已完成部分
  python3 tools/film/rough_cut.py --scenes P01 S01     # 指定场次
  python3 tools/film/rough_cut.py --missing slate      # 未拍镜头用黑场占位（默认跳过）

剪点覆盖写在 films/starcore/cut.json：{"sc_s02_03": {"in": 0.4, "out": 5.2}, "sc_s05_07": {"drop": true}}。
默认 in=0.25s（去掉首帧静滞），out=min(原片长, 秒数×0.92)。逐镜片段缓存在 renders/starcore_cut/。
输出 videos/starcore/rough_<范围>.mp4 和同名 .json 时间线。
"""
import argparse
from film_config import FilmConfig, add_film_args, film_names
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHOTS = ROOT / "films/starcore/shots"
CUTS = ROOT / "films/starcore/cut.json"
CACHE = ROOT / "renders/starcore_cut"
OUT = ROOT / "videos/starcore"
ORDER = ["P01"] + [f"S{i:02d}" for i in range(1, 40)]
W, H, FPS = 1344, 768, 24
SCOPE_H = round(W / 2.39 / 2) * 2  # 562：2.39:1 画面高度


def probe_dur(p: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def video_dur(p: Path) -> float:
    """分段视频流的实际时长（按整帧取整，比 -t 请求的略长）。时间线按它累加，字幕才不会越往后越早。"""
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=duration",
                          "-of", "csv=p=0", str(p)], capture_output=True, text=True, check=True).stdout
    # 调色重编码的分段时间基是 1/1024，stream duration 会比真实整帧少 ~0.65ms；
    # 115 段累积 ~75ms（2 帧），字幕和同期声就会比画面早。按整帧取整。
    return round(float(out.strip()) * FPS) / FPS


def has_nvenc() -> bool:
    r = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=s=256x256:d=0.1", "-c:v", "h264_nvenc",
                        "-f", "null", "-"], capture_output=True)
    return r.returncode == 0


VENC = ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "20"] if has_nvenc() else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "19"]
COMMON = ["-pix_fmt", "yuv420p", "-r", str(FPS), "-video_track_timescale", "12288", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
LETTERBOX = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},crop={W}:{SCOPE_H},pad={W}:{H}:0:(oh-ih)/2:black,setsar=1"


HD_SOURCES = {}
HD = False
FILM = FilmConfig()
DRY_RUN = False
CONTINUITY_TIMING = False


def configure_hd(source_map=None):
    global W, H, SCOPE_H, CACHE, LETTERBOX, VENC, HD_SOURCES, HD
    HD = True
    W, H, SCOPE_H = 1920, 1080, 804
    CACHE = FILM.cache.with_name(FILM.cache.name + "_hd")
    LETTERBOX = f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},crop={W}:{SCOPE_H},pad={W}:{H}:0:(oh-ih)/2:black,setsar=1"
    VENC = ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "18"] if has_nvenc() else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18"]
    HD_SOURCES = json.loads(Path(source_map).read_text()) if source_map else {}


def segment(shot, cut):
    raw = ROOT / "renders" / shot["id"] / "raw.mp4"
    if HD:
        enhanced = Path(HD_SOURCES.get(shot["id"], ROOT / "renders/lab/vsr" / f"{shot['id']}.mp4"))
        if enhanced.is_file():
            raw = enhanced
    dur = probe_dur(raw)
    t_in = float(cut.get("in", 0.25))
    t_out = float(cut.get("out", min(dur, shot["seconds"] * 0.92)))
    t_out = min(t_out, dur)
    length = max(0.5, t_out - t_in)
    key = hashlib.sha256(f"{raw.stat().st_size}:{raw.stat().st_mtime_ns}:{t_in}:{t_out}:{LETTERBOX}:{COMMON}".encode()).hexdigest()[:12]
    if HD:
        key = hashlib.sha256(f"{key}:{raw.resolve()}:{VENC}".encode()).hexdigest()[:12]
    dest = CACHE / f"{shot['id']}_{key}.mp4"
    if not dest.exists() and DRY_RUN:
        raise RuntimeError(f"Dry run requires existing cache: {dest}")
    if not dest.exists():
        fade = min(0.08, length / 4)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t_in:.3f}", "-i", str(raw), "-t", f"{length:.3f}",
                        "-vf", LETTERBOX, "-af", f"afade=t=in:d={fade},afade=t=out:st={length - fade:.3f}:d={fade},aresample=48000",
                        *VENC, *COMMON, str(dest)], check=True)
    return dest, t_in, t_out, length


def slate(shot):
    length = shot["seconds"] * 0.92
    dest = CACHE / f"slate_{shot['id']}_{hashlib.sha256(str(COMMON).encode()).hexdigest()[:8]}.mp4"
    if not dest.exists() and DRY_RUN:
        raise RuntimeError(f"Dry run requires existing cache: {dest}")
    if not dest.exists():
        text = f"{shot['id']}  未拍".replace(":", r"\:")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:r={FPS}:d={length}",
                        "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo", "-t", f"{length}",
                        "-vf", f"drawtext=text='{text}':fontcolor=gray:fontsize=36:x=(w-tw)/2:y=(h-th)/2:font='Microsoft YaHei'",
                        *VENC, *COMMON, str(dest)], check=True)
    return dest, length


def done(shot_id):
    j = ROOT / "renders" / shot_id / "job.json"
    return j.exists() and json.loads(j.read_text(encoding="utf-8")).get("status") == "completed" and (ROOT / "renders" / shot_id / "raw.mp4").exists()


def main():
    ap = argparse.ArgumentParser()
    add_film_args(ap)
    ap.add_argument("--dry-run", action="store_true", help="Read caches only; write timeline/cache keys to --report")
    ap.add_argument("--report", type=Path, help="Dry-run JSON destination (outside final outputs)")
    ap.add_argument("--compare", type=Path, help="Compare dry-run timeline with an existing JSON")
    ap.add_argument("--scenes", nargs="*")
    ap.add_argument("--missing", choices=["skip", "slate"], default="skip")
    ap.add_argument("--name")
    ap.add_argument("--hd", action="store_true")
    ap.add_argument("--hd-source-map", help="JSON id→path overrides for HD validation")
    ap.add_argument("--shot-ids", nargs="+", help="Restrict selected scenes to these shot IDs")
    ap.add_argument('--continuity', action='store_true', help='Enable normalisation, audio crossfades, mild colour match and safe push-in trim')
    for flag in ('normalize','audio-crossfade','color-match','trim-push-in','scene-dissolve'):
        ap.add_argument('--'+flag, action='store_true')
    ap.add_argument('--production-lufs', type=float, default=-18)
    ap.add_argument('--jl-cut', choices=['j','l'])
    args = ap.parse_args()
    flags=('normalize','audio_crossfade','color_match','trim_push_in','scene_dissolve')
    if args.continuity or args.jl_cut or any(getattr(args,f) for f in flags):
        if args.dry_run or args.hd or args.scenes or args.shot_ids or args.missing!='skip':
            ap.error('Continuity currently requires a complete standard-resolution edit')
        import continuity
        opts=['--film',FilmConfig(args.film).name,'--name',args.name or 'final_v2','--lufs',str(args.production_lufs)]
        opts += ['--'+f.replace('_','-') for f in flags if getattr(args,f) or (args.continuity and f!='scene_dissolve')]
        if args.jl_cut: opts += ['--jl-cut',args.jl_cut]
        return continuity.main(opts)
    global SHOTS, CUTS, CACHE, OUT, ORDER, FILM, DRY_RUN
    FILM = FilmConfig(args.film)
    SHOTS, CUTS, CACHE, OUT, ORDER = FILM.shots, FILM.cuts, FILM.cache, FILM.videos, FILM.order
    DRY_RUN = args.dry_run
    if (args.compare or args.report) and not args.dry_run:
        ap.error("--compare and --report require --dry-run")
    if args.hd_source_map and not args.hd:
        ap.error("--hd-source-map requires --hd")
    if args.hd:
        configure_hd(args.hd_source_map)
    cuts = json.loads(CUTS.read_text(encoding="utf-8")) if CUTS.exists() else {}
    scenes = args.scenes or [s for s in ORDER if (SHOTS / f"{s}.json").exists()]
    if not args.dry_run:
        CACHE.mkdir(parents=True, exist_ok=True)
        OUT.mkdir(parents=True, exist_ok=True)
    parts, timeline, t, missing = [], [], 0.0, []
    for sc in scenes:
        for shot in json.loads((SHOTS / f"{sc}.json").read_text(encoding="utf-8")):
            if args.shot_ids and shot["id"] not in args.shot_ids:
                continue
            cut = cuts.get(shot["id"], {})
            if cut.get("drop"):
                continue
            if done(shot["id"]):
                seg, t_in, t_out, length = segment(shot, cut)
                timeline.append({"id": shot["id"], "scene": sc, "start": round(t, 3), "length": round(length, 3),
                                 "in": t_in, "out": round(t_out, 3), "summary_zh": shot["summary_zh"], "dialogue": shot["dialogue"]})
            else:
                missing.append(shot["id"])
                if args.missing == "skip":
                    continue
                seg, length = slate(shot)
                timeline.append({"id": shot["id"], "scene": sc, "start": round(t, 3), "length": round(length, 3), "missing": True})
            parts.append(seg)
            real = video_dur(seg)
            timeline[-1]["length"] = round(real, 3)
            t += real
    if not parts:
        raise SystemExit("所选场次还没有完成的镜头")
    name = args.name or ("rough_" + ("full" if not args.scenes else "_".join(args.scenes)))
    if args.hd and not name.endswith("_hd"):
        name += "_hd"
    if args.dry_run:
        report = {"duration": round(t, 2), "shots": timeline, "missing": missing}
        if args.compare and report != json.loads(args.compare.read_text(encoding="utf-8")):
            raise SystemExit("Timeline comparison FAILED")
        report["cache_keys"] = [p.name for p in parts]
        if args.report:
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"Dry run: {len(timeline)} shots, {t:.6f}s; comparison passed" if args.compare else f"Dry run: {len(timeline)} shots")
        return
    lst = CACHE / f"{name}.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    if args.hd or CONTINUITY_TIMING:
        # AAC packet padding must not extend each video segment in the concat demuxer.
        lst.write_text("".join(f"file '{p.as_posix()}'\nduration {video_dur(p):.6f}\n" for p in parts), encoding="utf-8")
    out = OUT / f"{name}.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), *VENC, *COMMON,
                    "-movflags", "+faststart", *(["-frames:v", str(round(t * FPS))] if args.hd or CONTINUITY_TIMING else []), str(out)], check=True)
    (OUT / f"{name}.json").write_text(json.dumps({"duration": round(t, 2), "shots": timeline, "missing": missing},
                                                 ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{out.relative_to(ROOT)}  {t / 60:.1f} min  {len(timeline) - (len(missing) if args.missing == 'slate' else 0)} shots used, {len(missing)} missing")


if __name__ == "__main__":
    main()
