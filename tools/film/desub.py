"""Find and remove model-invented subtitles from generated clips.

LTX sometimes paints garbled captions at the bottom of the frame when the soundtrack has
speech (more often with "TV drama" in the prompt). There is no negative prompt in the
distilled pipeline, so this cleans the finished clip: in the subtitle band (bottom 20 %,
centre 60 %) it looks for a row of small bright glyph blobs, masks them with their outline,
merges the mask over +-HOLD frames so it does not flicker, and inpaints.

  python desub.py clip.mp4 --check            # report frames with text, change nothing
  python desub.py clip.mp4 --out clean.mp4    # write a cleaned copy (audio copied)
"""
import argparse, subprocess
import numpy as np
import cv2

HOLD = 4


def read(path):
    p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,r_frame_rate",
                        "-of", "csv=p=0", path], capture_output=True, text=True).stdout.strip().split(",")
    w, h = int(p[0]), int(p[1]); num, den = p[2].split("/")
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3), float(num) / float(den)


def text_mask(rgb):
    h, w = rgb.shape[:2]
    y0, y1, x0, x1 = int(h * 0.80), int(h * 0.97), int(w * 0.2), int(w * 0.8)
    g = cv2.cvtColor(rgb[y0:y1, x0:x1], cv2.COLOR_RGB2GRAY)
    n, _, st, cen = cv2.connectedComponentsWithStats((g > 200).astype(np.uint8), 8)
    s = h / 384
    keep = [i for i in range(1, n) if 3 * s <= st[i, 3] <= 22 * s and 2 * s <= st[i, 2] <= 30 * s and st[i, 4] >= 6 * s * s]
    if len(keep) < 4:
        return None
    ys = np.array([cen[i][1] for i in keep]); med = np.median(ys)
    row = [i for i in keep if abs(cen[i][1] - med) <= 6 * s]     # glyphs sit on one baseline
    if len(row) < 4:
        return None
    m = np.zeros((h, w), np.uint8)
    pad = int(3 * s)
    for i in row:
        x, y, bw, bh = st[i, :4]
        m[y0 + y - pad:y0 + y + bh + pad, x0 + x - pad:x0 + x + bw + pad] = 255
    return m


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("clip")
    ap.add_argument("--out")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    fr, fps = read(a.clip)
    masks = [text_mask(f) for f in fr]
    hits = [i for i, m in enumerate(masks) if m is not None]
    print(f"{a.clip}: {len(fr)} frames, text in {len(hits)}" + (f" ({hits[0] / fps:.2f}-{hits[-1] / fps:.2f}s)" if hits else ""))
    if a.check or not a.out:
        return
    h, w = fr.shape[1:3]
    out = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", f"{fps}",
                            "-i", "-", "-i", a.clip, "-map", "0:v", "-map", "1:a?", "-c:v", "libx264", "-crf", "14",
                            "-pix_fmt", "yuv420p", "-c:a", "copy", a.out], stdin=subprocess.PIPE)
    for i, f in enumerate(fr):
        near = [masks[j] for j in range(max(0, i - HOLD), min(len(fr), i + HOLD + 1)) if masks[j] is not None]
        if near:
            m = cv2.dilate(np.maximum.reduce(near), np.ones((5, 5), np.uint8))
            f = cv2.inpaint(np.ascontiguousarray(f), m, 7, cv2.INPAINT_TELEA)
        out.stdin.write(np.ascontiguousarray(f).tobytes())
    out.stdin.close(); out.wait()


if __name__ == "__main__":
    main()
