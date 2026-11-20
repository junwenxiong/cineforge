"""测镜头内推拉：首帧到后续帧的相似变换缩放量（ORB + RANSAC）。

scale > 1 表示画面被放大（推镜），< 1 表示拉远。用法：
  python zoom_check.py a.mp4 b.mp4 ...            # 每个文件一行
  python zoom_check.py --json out.json a.mp4 ...
"""
import argparse, json, subprocess, sys
import numpy as np
import cv2


def frames(path, step=1.0, w=672, h=384):
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                               capture_output=True, text=True).stdout.strip() or 0)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", f"fps=1/{step},scale={w}:{h}",
                          "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True).stdout
    n = len(raw) // (w * h)
    return dur, [np.frombuffer(raw[i * w * h:(i + 1) * w * h], np.uint8).reshape(h, w) for i in range(n)]


def scale_between(a, b, orb=cv2.ORB_create(1500), bf=cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)):
    ka, da = orb.detectAndCompute(a, None)
    kb, db = orb.detectAndCompute(b, None)
    if da is None or db is None or len(ka) < 20 or len(kb) < 20:
        return None
    m = sorted(bf.match(da, db), key=lambda x: x.distance)[:400]
    if len(m) < 20:
        return None
    pa = np.float32([ka[x.queryIdx].pt for x in m])
    pb = np.float32([kb[x.trainIdx].pt for x in m])
    M, inl = cv2.estimateAffinePartial2D(pa, pb, method=cv2.RANSAC, ransacReprojThreshold=3)
    if M is None or inl is None or inl.sum() < 15:
        return None
    return float(np.hypot(M[0, 0], M[1, 0]))


FACE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")


def face_h(img):
    """最大人脸框高度占画面高度的比例；找不到返回 None。"""
    f = FACE.detectMultiScale(img, 1.1, 5, minSize=(24, 24))
    return float(max(h for _, _, _, h in f)) / img.shape[0] if len(f) else None


def scene_jump(path):
    """镜头内最大帧间突变分数（ffmpeg scdet）；干净镜头约 0.1-0.2，镜内硬切 >1。"""
    o = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", "scale=320:-2,scdet=threshold=10,metadata=print:file=-",
                        "-an", "-f", "null", "-"], capture_output=True, text=True).stdout
    v = [float(x.split("=")[1]) for x in o.split() if x.startswith("lavfi.scd.score=")]
    return round(max(v), 3) if v else None


def measure(path):
    dur, fs = frames(path)
    if len(fs) < 2:
        return {"file": path, "error": "too few frames"}
    s = [scale_between(fs[0], f) for f in fs[1:]]
    valid = [x for x in s if x]
    faces = [face_h(f) for f in fs]
    fv = [(i, x) for i, x in enumerate(faces) if x]
    # 主体变大：最后一张能测到的人脸 / 第一张；>1.25 就是"脸怼上来了"
    grow = round(fv[-1][1] / fv[0][1], 2) if len(fv) >= 2 else None
    return {"file": path, "duration": round(dur, 2),
            "scales": [round(x, 3) if x else None for x in s],
            "end": round(valid[-1], 3) if valid else None,
            "max": round(max(valid), 3) if valid else None,
            "min": round(min(valid), 3) if valid else None,
            "faces": [round(x, 3) if x else None for x in faces], "face_grow": grow,
            "scd_max": scene_jump(path)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--json")
    a = ap.parse_args()
    res = [measure(f) for f in a.files]
    for r in res:
        print(f"{r['file']}: cam_end={r.get('end')} cam_min={r.get('min')} cam_max={r.get('max')} "
              f"face_grow={r.get('face_grow')} scd={r.get('scd_max')} faces={r.get('faces')}", file=sys.stdout)
    if a.json:
        json.dump(res, open(a.json, "w"), indent=1)
