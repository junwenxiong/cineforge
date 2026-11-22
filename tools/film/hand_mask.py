"""Locate the actors' hands in a source clip, frame by frame, for animal recasts.

Why: in video-to-video recasting (people -> cats), the depth/edge control video carries
the exact outline of human fingers, and the model faithfully paints human hands.
ltx_v2v.py uses these boxes to (1) melt the control signal inside each hand into a
smooth "mitten" blob, so the model is free to draw a paw, and (2) lower control
attention there via --conditioning-attention-mask.

  python hand_mask.py source.mp4 --start 2578.74 --dur 20.0 [--fps 24] [--crop w:h:x:y] [--out hands.json]

Output: {"fps": 24, "frames": N, "boxes": {"<frame>": [[x0,y0,x1,y1], ...]}} in 0..1 units.
Boxes are padded, held for +-HOLD frames and bridged across gaps up to BRIDGE frames,
so detector dropouts (clasped hands, blur) don't leave human fingers unmasked.
Black-and-white footage works well: MediaPipe found hands in 57-80 of 62-80 sampled
frames of 《马路天使》 (1937).
"""
import argparse, json, os, subprocess
from pathlib import Path
import numpy as np

MODEL = Path(os.environ.get("HAND_MODEL", Path.home() / ".cache/mp/hand_landmarker.task"))
W, H = 640, 480
PAD = 0.45      # box padding relative to hand size (covers wrist and motion blur)
HOLD = 6        # frames a detection is held forwards and backwards
BRIDGE = 24     # gaps up to this many frames between two detections are filled (clasped hands, blur)


def _box(pts):
    xs = [p.x for p in pts]; ys = [p.y for p in pts]
    s = max(max(xs) - min(xs), max(ys) - min(ys), 0.03)
    return [round(max(0, min(xs) - PAD * s), 4), round(max(0, min(ys) - PAD * s), 4),
            round(min(1, max(xs) + PAD * s), 4), round(min(1, max(ys) + PAD * s), 4)]


def detect(path, start, dur, fps, crop=""):
    """Two passes, merged: VIDEO-mode tracking (steady) and a low-confidence per-frame IMAGE pass
    (catches hands the tracker drops: clasped hands, fast motion, old film grain)."""
    import mediapipe as mp
    from mediapipe.tasks.python import vision, BaseOptions
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{start:.3f}", "-i", str(path), "-t", f"{dur:.3f}",
                          "-vf", (f"crop={crop}," if crop else "") + f"fps={fps},scale={W}:{H}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    n = len(raw) // (W * H * 3)
    found = {}
    for mode, conf in ((vision.RunningMode.VIDEO, 0.35), (vision.RunningMode.IMAGE, 0.2)):
        extra = {"min_tracking_confidence": conf} if mode == vision.RunningMode.VIDEO else {}
        opts = vision.HandLandmarkerOptions(base_options=BaseOptions(model_asset_path=str(MODEL)), num_hands=4, running_mode=mode,
                                            min_hand_detection_confidence=conf, min_hand_presence_confidence=conf, **extra)
        with vision.HandLandmarker.create_from_options(opts) as lm:
            for i in range(n):
                f = np.frombuffer(raw[i * W * H * 3:(i + 1) * W * H * 3], np.uint8).reshape(H, W, 3)
                img = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(f))
                res = lm.detect_for_video(img, int(i * 1000 / fps)) if mode == vision.RunningMode.VIDEO else lm.detect(img)
                for pts in res.hand_landmarks:
                    found.setdefault(i, []).append(_box(pts))
    held = {}
    for i, boxes in found.items():
        for j in range(max(0, i - HOLD), min(n, i + HOLD + 1)):
            held.setdefault(j, []).extend(boxes)
    keys = sorted(found)
    for a, b in zip(keys, keys[1:]):          # bridge short gaps with the union of the boxes on both sides
        if HOLD * 2 < b - a <= BRIDGE:
            fill = found[a] + found[b]
            for j in range(a + 1, b):
                held.setdefault(j, []).extend(fill)
    return n, held, len(found)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--dur", type=float, required=True)
    ap.add_argument("--fps", type=float, default=24)
    ap.add_argument("--crop", default="", help="w:h:x:y in source pixels, same as the v2v job (removes pillarbox)")
    ap.add_argument("--out")
    a = ap.parse_args()
    n, boxes, hit = detect(a.source, a.start, a.dur, a.fps, a.crop)
    out = dict(fps=a.fps, frames=n, detected_frames=hit, boxes={str(k): v for k, v in sorted(boxes.items())})
    text = json.dumps(out)
    if a.out:
        Path(a.out).write_text(text)
    print(f"{n} frames, hands detected in {hit}, masked in {len(boxes)}")


if __name__ == "__main__":
    main()
