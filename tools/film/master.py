"""《星核黎明》成片母版：中文对白字幕 + 片名 + 片尾字幕（含配乐署名）。

读取 videos/starcore/<name>.json（rough_cut 时间线）和 <name>_scored.mp4（score_mix 输出），
生成 <name>.ass，烧录字幕后接上片尾，输出 videos/starcore/<name>_master.mp4。
用法（WSL，项目根目录）：python3 tools/film/master.py --name rough_latest
"""
import argparse
from film_config import FilmConfig, add_film_args, film_names
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from rough_cut import COMMON, FPS, VENC  # noqa: E402

VID = ROOT / "videos/starcore"
MUSIC = ROOT / "assets/starcore/music"
W, H = 1344, 768
BAR = (768 - 562) // 2          # 2.39:1 遮幅黑边高度，字幕放在下黑边里
CREDITS_SEC = 62
SCALE_X = SCALE_Y = 1.0
FILM = FilmConfig()

MUSIC_CREDIT = ("Music by Scott Buckley (www.scottbuckley.com.au)\\N"
                "released under CC-BY 4.0\\N"
                "Chronicle · Tomorrow · Beyond These Walls · Emergent · Juggernaut\\N"
                "Simulacra · Pursuit · Catalyst · Into The Unknown · The Long Dark\\N"
                "Uprising · The Fury · Starfire · Legacy")

CREDITS = [
    ("星核黎明", "Title"), ("STARCORE DAWN", "TitleEn"), ("", "Body"),
    ("原创故事 · 分镜 · 导演", "Head"), ("AI 导演工作流（Claude Code）", "Body"), ("", "Body"),
    ("视频生成", "Head"), ("MiniMax H3 · DramaPie Box · Google Colab", "Body"), ("", "Body"),
    ("角色与场景设定", "Head"), ("gpt-image-2", "Body"), ("", "Body"),
    ("配乐", "Head"), (MUSIC_CREDIT, "Body"), ("", "Body"),
    ("本片角色、机体与故事均为原创", "Body"), ("", "Body"), ("", "Body"),
    ("— 完 —", "Head"),
]


def ts(t):
    t = max(0.0, t)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


HEADER = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Dlg,Microsoft YaHei,34,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,1,0,1,2,0,2,60,60,{BAR // 2 - 17},1
Style: VO,Microsoft YaHei,34,&H00D8E6F0,&H00FFFFFF,&H00000000,&H80000000,0,1,0,0,100,100,1,0,1,2,0,2,60,60,{BAR // 2 - 17},1
Style: Title,Microsoft YaHei,96,&H00FFFFFF,&H00FFFFFF,&H00402000,&H00000000,1,0,0,0,100,100,12,0,1,3,0,5,0,0,0,1
Style: TitleEn,Microsoft YaHei,34,&H00F0C890,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,14,0,1,1,0,5,0,0,0,1
Style: Head,Microsoft YaHei,30,&H0090C8F0,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,2,0,1,1,0,5,0,0,0,1
Style: Body,Microsoft YaHei,28,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,1,0,1,1,0,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def dialogue_events(tl):
    ev = []
    for s in tl["shots"]:
        lines = [d for d in s.get("dialogue") or [] if d.get("text")]
        if not lines:
            continue
        span = s["length"] - 0.4
        weights = [max(len(d["text"]), 4) for d in lines]
        t = s["start"] + 0.2
        for d, w in zip(lines, weights):
            dur = max(1.4, span * w / sum(weights))
            style = "VO" if "(VO)" in d["who"] or "OS" in d["who"] else "Dlg"
            ev.append(f"Dialogue: 0,{ts(t)},{ts(min(t + dur, s['start'] + s['length'] - 0.05))},{style},,0,0,0,,{d['text']}")
            t += dur
    return ev


def title_events(tl):
    """片名放在序幕（P01）结束处，压在第一场的开场镜头上。"""
    p01 = [s for s in tl["shots"] if s["scene"] == "P01"]
    t0 = (p01[-1]["start"] + p01[-1]["length"]) if p01 else 3.0
    fx = r"{\fad(900,900)\blur1}"
    return [f"Dialogue: 1,{ts(t0 + 0.5)},{ts(t0 + 5.5)},Title,,0,0,0,,{fx}{FILM.title}",
            f"Dialogue: 1,{ts(t0 + 1.0)},{ts(t0 + 5.5)},TitleEn,,0,0,0,,{fx}{{\\pos({W // 2},{H // 2 + round(78 * SCALE_Y)})}}{FILM.title_en}"]


def credits_ass(path):
    """片尾滚动字幕：整块文本从画面底部匀速升到顶部之外。"""
    y, rows = 0, []
    gap = {"Title": 120, "TitleEn": 70, "Head": 50, "Body": 42}
    for text, style in CREDITS:
        rows.append((y, text, style))
        y += gap[style] * (text.count("\\N") + 1) if text else 40
    rows = [(round(off * SCALE_Y), text, style) for off, text, style in rows]
    total = round(y * SCALE_Y)
    ev = []
    for off, text, style in rows:
        if not text:
            continue
        y0, y1 = H + round(60 * SCALE_Y) + off, -total - round(60 * SCALE_Y) + off
        ev.append(f"Dialogue: 0,{ts(0)},{ts(CREDITS_SEC)},{style},,0,0,0,,{{\\an8\\move({W // 2},{y0},{W // 2},{y1})}}{text}")
    path.write_text(HEADER + "\n".join(ev) + "\n", encoding="utf-8")


def ff(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True, cwd=VID)


def configure_hd():
    global W, H, BAR, HEADER, VENC, SCALE_X, SCALE_Y
    from rough_cut import configure_hd as cut_hd
    import rough_cut
    cut_hd()
    VENC = rough_cut.VENC
    SCALE_X, SCALE_Y = 1920 / 1344, 1080 / 768
    W, H, BAR = 1920, 1080, 138
    lines = []
    for line in HEADER.splitlines():
        if line.startswith("PlayResX:"):
            line = f"PlayResX: {W}"
        elif line.startswith("PlayResY:"):
            line = f"PlayResY: {H}"
        elif line.startswith("Style:"):
            fields = line.split(",")
            for index in (2, 13, 16, 17, 21):
                fields[index] = str(round(float(fields[index]) * SCALE_Y, 2))
            for index in (19, 20):
                fields[index] = str(round(float(fields[index]) * SCALE_X))
            if fields[0] in ("Style: Dlg", "Style: VO"):
                fields[21] = str(round((BAR - float(fields[2])) / 2))
            line = ",".join(fields)
        lines.append(line)
    HEADER = "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    add_film_args(ap)
    ap.add_argument("--name", default="rough_latest")
    ap.add_argument("--hd", action="store_true")
    args = ap.parse_args()
    global MUSIC, VID, CREDITS, CREDITS_SEC, FILM
    FILM = FilmConfig(args.film)
    MUSIC, VID = FILM.music, FILM.videos
    CREDITS = FILM.credits if FILM.credits is not None else CREDITS
    if FILM.credits is None and FILM.metadata:
        CREDITS = [(FILM.title, "Title"), (FILM.title_en, "TitleEn")] + CREDITS[2:]
    CREDITS_SEC = FILM.credits_seconds
    if args.hd:
        configure_hd()
        if not args.name.endswith("_hd"):
            args.name += "_hd"
    tl = json.loads((VID / f"{args.name}.json").read_text(encoding="utf-8"))
    src = VID / f"{args.name}_scored.mp4"
    ass = VID / f"{args.name}.ass"
    ass.write_text(HEADER + "\n".join(title_events(tl) + dialogue_events(tl)) + "\n", encoding="utf-8")
    body = VID / f"_{args.name}_subbed.mp4"
    ff("-i", str(src.resolve()), "-vf", f"ass={ass.name}", *VENC, *COMMON, "-c:a", "copy", str(body.resolve()))
    cass = VID / ("_credits_hd.ass" if args.hd else "_credits.ass")
    credits_ass(cass)
    cred = VID / ("_credits_hd.mp4" if args.hd else "_credits.mp4")
    ff("-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:r={FPS}:d={CREDITS_SEC}",
       "-i", str(MUSIC / FILM.credits_music),
       "-filter_complex", f"[0:v]ass={cass.name}[v];[1:a]atrim=duration={CREDITS_SEC},afade=t=in:d=2,"
                          f"afade=t=out:st={CREDITS_SEC - 5}:d=5,volume=-14dB,aresample=48000,aformat=channel_layouts=stereo[a]",
       "-map", "[v]", "-map", "[a]", *VENC, *COMMON, str(cred.resolve()))
    lst = VID / ("_master_list_hd.txt" if args.hd else "_master_list.txt")
    lst.write_text(f"file '{body.resolve()}'\nfile '{cred.resolve()}'\n", encoding="utf-8")
    if args.hd:
        from rough_cut import video_dur
        lst.write_text(f"file '{body.resolve()}'\nduration {round(video_dur(body) * FPS) / FPS:.6f}\n"
                       f"file '{cred.resolve()}'\nduration {round(video_dur(cred) * FPS) / FPS:.6f}\n", encoding="utf-8")
    out = VID / f"{args.name}_master.mp4"
    ff("-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", "-movflags", "+faststart", str(out))
    print(f"{out.relative_to(ROOT)}  subs={ass.name}  {(tl['duration'] + CREDITS_SEC) / 60:.1f} min")


if __name__ == "__main__":
    main()
