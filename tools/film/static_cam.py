"""LTX 定机位提示词：去掉诱导推镜的句子，把机位约束放到最前面。

LTX-2.5 蒸馏版不吃负面提示词，提示词里出现"结尾停在她眼睛上""皮肤毛孔清晰"之类
写法时，模型会自己推成特写。这里做两件事：
1. 删除/改写诱导推镜的句子；
2. 开头写明锁定机位和景别，结尾再重复一次。
配合 ltx25.py 的 job["anchors"]（同一关键帧做后段引导帧）使用。
"""
import re

SIZE_WORDS = {
    "EWS": "extreme wide shot", "WS": "wide shot", "MWS": "medium wide shot", "FS": "full shot",
    "MS": "medium shot, waist up", "MCU": "medium close-up, chest up", "CU": "close-up",
    "ECU": "extreme close-up", "INSERT": "insert shot", "OTS": "over-the-shoulder shot",
}

PUSH = re.compile(
    r"(shot ends|ends (on|with|holding)|frame hold|holding on|hold on (her|his|the)|push(es|ing)?[- ]?in|"
    r"pushes|dolly|zoom|closer|fills the frame|filling the frame|toward the (camera|lens)|into (the )?lens|"
    r"camera (slowly )?(moves|drifts|creeps|glides|tracks)|tighten|lingers on)", re.I)
DETAIL = re.compile(r"crisp skin pores,?\s*(individual hair strands,?\s*)?(and )?", re.I)
OLD_CAMERA = re.compile(r"\.?\s*Camera:.*$", re.I | re.S)


SIZE_PHRASE = re.compile(r"\b(extreme close-up|medium close-up|close-up|medium wide shot|medium shot|wide shot|full shot)\b",
                         re.I)
# 2026-11-20 实测：LTX 镜头内"推镜"多半不是摄影机动，而是人物自己走近/前倾，
# 尤其当提示词写的景别比关键帧更紧时（关键帧中景、文字写近景 → 人物走到近景）。
STAY = ("Every person stays at the same distance from the camera for the whole shot: nobody walks, steps "
        "or leans toward the camera, and their head stays the same size in frame. ")


def static_prompt(prompt, size=None):
    body = OLD_CAMERA.sub("", prompt).strip()
    body = DETAIL.sub("crisp ", body)
    sentences = re.split(r"(?<=[.!?\"”])\s+(?=[A-Z])", body)
    kept = [s for s in sentences if not PUSH.search(s)]
    size_word = SIZE_WORDS.get((size or "").upper(), "")
    if size_word and (size or "").upper() not in ("INSERT", "OTS"):
        # 正文里的景别词统一成关键帧的实际景别，避免文字比画面紧
        kept = [SIZE_PHRASE.sub(size_word.split(",")[0], s) for s in kept]
    head = ("Locked-off tripod shot: the camera never moves, no zoom, no push-in, no dolly; "
            + (f"the framing stays a {size_word} " if size_word else "the framing stays the same ")
            + "from the first frame to the last. " + STAY)
    tail = (" The framing at the end is identical to the first frame"
            + (f": still a {size_word}." if size_word else "."))
    return head + " ".join(kept).strip() + tail
