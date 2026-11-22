"""Find human-looking hands in a cat (or other animal) recast.

MediaPipe's hand landmarker is trained on human hands. On a real cat paw it rarely
fires; on a hairless five-finger "human hand" it fires confidently. Every detection
is cropped and scored for how much it looks like bare skin, and the crops go on a
contact sheet for a human (or vision model) to confirm. The score is a triage tool,
not a final verdict.

  python hand_check.py clip.mp4 [more.mp4 ...] [--fps 4] [--sheet out.jpg] [--json out.json]

Per clip: frames sampled, frames with a confident hand, worst skin-like crop.
Model file: ~/.cache/mp/hand_landmarker.task (MediaPipe hand_landmarker, float16).
"""
import argparse, json, os, subprocess, sys
from pathlib import Path
import numpy as np
import cv2

MODEL = Path(os.environ.get("HAND_MODEL", Path.home() / ".cache/mp/hand_landmarker.task"))
W, H = 768, 576


def frames(path, fps):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"fps={fps},scale={W}:{H}",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    n = len(raw) // (W * H * 3)
    return [np.frombuffer(raw[i * W * H * 3:(i + 1) * W * H * 3], np.uint8).reshape(H, W, 3) for i in range(n)]


def skin_score(crop):
    """Bare-skin likeness of a hand crop: smooth, low-saturation skin tones score high; textured or
    strongly coloured fur scores low. 0..1."""
    if crop.size == 0:
        return 0.0
    ycc = cv2.cvtColor(crop, cv2.COLOR_RGB2YCrCb)
    skin = cv2.inRange(ycc, (40, 135, 85), (240, 172, 125)) > 0
    hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
    mild = hsv[..., 1] < 140                        # orange/ginger fur is more saturated than skin
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY).astype(np.float32)
    detail = np.abs(gray - cv2.GaussianBlur(gray, (0, 0), 1.2))
    smooth = detail < 4.0                           # fur has fine strand texture; skin is smooth
    return float((skin & mild & smooth).mean())


def check(path, fps, landmarker):
    import mediapipe as mp
    hits = []
    fs = frames(path, fps)
    for i, f in enumerate(fs):
        res = landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(f)))
        for lm, hd in zip(res.hand_landmarks, res.handedness):
            conf = hd[0].score
            xs = [p.x * W for p in lm]; ys = [p.y * H for p in lm]
            pad = 0.25 * max(max(xs) - min(xs), max(ys) - min(ys), 20)
            x0, y0 = int(max(0, min(xs) - pad)), int(max(0, min(ys) - pad))
            x1, y1 = int(min(W, max(xs) + pad)), int(min(H, max(ys) + pad))
            crop = f[y0:y1, x0:x1]
            hits.append(dict(t=round(i / fps, 2), conf=round(conf, 3), skin=round(skin_score(crop), 3),
                             box=[x0, y0, x1, y1], crop=crop))
    strong = [h for h in hits if h["conf"] >= 0.6]
    return dict(file=str(path), frames=len(fs), hand_frames=len({h["t"] for h in strong}),
                human_like=len({h["t"] for h in strong if h["skin"] >= 0.25}),
                worst=max((h["skin"] for h in strong), default=0.0), hits=strong)


def sheet(results, out, per=8, size=128):
    rows = [r for r in results if r["hits"]]
    if not rows:
        return
    img = np.zeros(((size + 18) * len(rows), size * per, 3), np.uint8)
    for r, res in enumerate(rows):
        top = sorted(res["hits"], key=lambda h: -h["skin"])[:per]
        cv2.putText(img, Path(res["file"]).name[:60], (4, r * (size + 18) + 13), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
        for c, h in enumerate(top):
            tile = cv2.resize(h["crop"], (size, size))
            cv2.putText(tile, f"{h['t']}s s{h['skin']:.2f}", (2, size - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 255, 0), 1)
            img[r * (size + 18) + 18:r * (size + 18) + 18 + size, c * size:(c + 1) * size] = tile
    cv2.imwrite(str(out), cv2.cvtColor(img, cv2.COLOR_RGB2BGR))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--fps", type=float, default=4)
    ap.add_argument("--sheet")
    ap.add_argument("--json")
    a = ap.parse_args()
    from mediapipe.tasks.python import vision, BaseOptions
    opts = vision.HandLandmarkerOptions(base_options=BaseOptions(model_asset_path=str(MODEL)), num_hands=4,
                                        min_hand_detection_confidence=0.4, min_hand_presence_confidence=0.4)
    with vision.HandLandmarker.create_from_options(opts) as lm:
        results = [check(f, a.fps, lm) for f in a.files]
    for r in results:
        print(f"{Path(r['file']).name}: frames={r['frames']} hand_frames={r['hand_frames']} "
              f"human_like={r['human_like']} worst_skin={r['worst']:.2f}")
    if a.sheet:
        sheet(results, a.sheet)
    if a.json:
        json.dump([{k: v for k, v in r.items() if k != "hits"} | {"hits": [{k: v for k, v in h.items() if k != "crop"}
                   for h in r["hits"]]} for r in results], open(a.json, "w"), indent=1)


if __name__ == "__main__":
    main()
