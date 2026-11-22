"""把 H3 Ref2VA 结构化提示词（subject_definitions / <Picture N> / [Shot N]）改写成 LTX 能读懂的自然描述。

LTX 是图生视频，人物长相已经在关键帧里；它看不懂 <Subject 1>、<Picture 2> 这种占位符。
"""
import re

SECTION = re.compile(r"^(subject_definitions|summary|retention_analysis|detailed_description|overall_soundscape|"
                     r"non_diegetic_music|shot_breakdown):[ \t]*", re.M)
SUBJ = re.compile(r"<Subject (\d+)> is (?:the |an? )?(.+?) in <Picture \d+>(?: and <Picture \d+>)?,?\s*(.*)$")


def sections(prompt):
    parts, last, name = {}, 0, None
    for m in SECTION.finditer(prompt):
        if name:
            parts[name] = prompt[last:m.start()].strip()
        name, last = m.group(1), m.end()
    if name:
        parts[name] = prompt[last:].strip()
    return parts


def h3_to_ltx(prompt):
    if "subject_definitions" not in prompt:
        return prompt
    p = sections(prompt)
    subjects = {}
    for line in p.get("subject_definitions", "").splitlines():
        m = SUBJ.match(line.strip())
        if m:
            subjects[m.group(1)] = (f"the {m.group(2)}", m.group(3).lstrip(":, ").rstrip(". "))
    text = p.get("detailed_description", "")
    text = re.sub(r"\.?\s*Camera:.*$", "", text, flags=re.S)
    seen = set()

    def sub(m):
        k = m.group(1)
        name, desc = subjects.get(k, ("the person", ""))
        poss = m.group(2) or ""
        if k not in seen and desc and not poss:
            seen.add(k)
            return f"{name} ({desc})"
        seen.add(k)
        return name + poss
    text = re.sub(r"<d>\[Chinese\]\s*(.*?)</d>", r'in Mandarin Chinese, "\1"', text)
    text = re.sub(r"\s*\(S\d+\)", "", text)
    text = re.sub(r"<Subject (\d+)>('s)?", sub, text)
    text = re.sub(r"<Picture \d+>", "the location", text)
    text = re.sub(r"\[Shot \d+\]\s*", "", text)
    text = re.sub(r"\n+", " ", text).strip()
    audio = re.sub(r"<Subject (\d+)>", lambda m: subjects.get(m.group(1), ("the person",))[0],
                   p.get("overall_soundscape", "")).strip()
    music = p.get("non_diegetic_music", "")
    music = re.sub(r"\.?\s*Camera:.*$", "", music, flags=re.S).strip()
    out = text + (f" Audio: {audio}" if audio else "")
    if music and music.upper() not in ("N/A", "NONE"):
        out += f" Music: {music}"
    return out + " No on-screen text."
