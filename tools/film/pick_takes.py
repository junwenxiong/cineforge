"""在多个候选版本（take1=v1 原景别、raw=v2、实验室 __v3）里给重构镜头挑一条。

规则（越小越好）：镜头内人脸放大量 + 与前后镜头接缝处的人脸大小差（对数）。
v1 原版是按旧景别拍的，罚 1.0（它就是跳切的来源），只在 v2/v3 都坏时兜底。
用法：python pick_takes.py --film echo --ids renders/farm/lab_jobs_ltx_echov2.json [--apply]
--apply 会把选中的 v3 存成 renders/<id>/raw.mp4 + job.json（旧 raw 先归档到 takeN/）。
"""
import argparse, hashlib, json, math, shutil, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from zoom_check import measure
from ltx_collect import validate

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "renders/qa/pick_takes_cache.json"


def order(film):
    shots = []
    for p in sorted((ROOT / f"films/{film}/shots").glob("*.json")):
        shots += json.loads(p.read_text(encoding="utf-8"))
    return shots


def candidates(sid):
    c = {}
    t1 = ROOT / f"renders/{sid}/take1/raw.mp4"
    if t1.exists():
        c["v1"] = t1
    raw = ROOT / f"renders/{sid}/raw.mp4"
    if raw.exists():
        c["v2"] = raw
    for lab in sorted((ROOT / "renders/lab").glob("ltx_*")):   # 任意 LTX 机器的产出目录
        for tag in ("v3", "v4", "c"):   # __c = 只清洗提示词的试验版
            f = lab / f"{sid}__{tag}_distilled.mp4"
            if f.exists():
                c[tag] = f
    return c


def ends(m):
    f = [x for x in m.get("faces", []) if x]
    return (f[0], f[-1]) if f else (None, None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--film", default="echo")
    ap.add_argument("--ids", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    ids = [j["id"] for j in json.load(open(a.ids))]
    shots = order(a.film)
    pos = {s["id"]: i for i, s in enumerate(shots)}
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}

    def meas(path):
        key = f"{path}:{path.stat().st_size}:{int(path.stat().st_mtime)}:scd"
        if key not in cache:
            cache[key] = measure(str(path))
        return cache[key]

    picks, rows = {}, []
    for sid in ids:
        i = pos[sid]
        prev = shots[i - 1] if i > 0 and shots[i - 1]["scene"] == shots[i]["scene"] else None
        nxt = shots[i + 1] if i + 1 < len(shots) and shots[i + 1]["scene"] == shots[i]["scene"] else None

        def neighbour(s, want_end):
            if not s:
                return None
            p = ROOT / f"renders/{s['id']}/raw.mp4"
            if s["id"] in ids:   # 邻居也在重拍：优先用它的 v3
                p = candidates(s["id"]).get("v3", p)
            if not p.exists():
                return None
            st, en = ends(meas(p))
            return en if want_end else st
        pe, ns = neighbour(prev, True), neighbour(nxt, False)
        best = None
        for name, path in candidates(sid).items():
            m = meas(path)
            st, en = ends(m)
            grow = abs(math.log(m["face_grow"])) if m.get("face_grow") else 0.0
            cam = abs(math.log(m["end"])) if m.get("end") else 0.0
            seam = sum(abs(math.log(x / y)) for x, y in ((pe, st), (en, ns)) if x and y)
            scd = m.get("scd_max") or 0
            jump = 2.0 if scd > 1.0 else 0.5 if scd > 0.35 else 0.0   # 镜内硬切/突变
            score = grow + cam + jump + 0.5 * seam + (1.0 if name == "v1" else 0) + (0.05 if name == "v2" else 0)
            rows.append(dict(id=sid, take=name, face_grow=m.get("face_grow"), cam=m.get("end"), scd=scd,
                             start=st, end=en, prev_end=pe, next_start=ns, score=round(score, 3)))
            if best is None or score < best[0]:
                best = (score, name, path)
        picks[sid] = (best[1], str(best[2]), round(best[0], 3))
    CACHE.write_text(json.dumps(cache))
    out = ROOT / f"renders/qa/{a.film}_pick_takes.json"
    out.write_text(json.dumps({"picks": picks, "rows": rows}, ensure_ascii=False, indent=1))
    for sid, (name, path, s) in picks.items():
        print(sid, name, s, " | ".join(f"{r['take']}:{r['face_grow']}/{r['score']}" for r in rows if r["id"] == sid))
    if a.apply:
        for sid, (name, path, _) in picks.items():
            d = ROOT / f"renders/{sid}"
            if name == "v1" and not (d / "raw.mp4").exists():   # 新版都不如旧版、且没有 v2：把 take1 放回去
                for f in ("raw.mp4", "job.json"):
                    if (d / "take1" / f).exists():
                        shutil.copy2(d / "take1" / f, d / f)
                continue
            if name not in ("v3", "v4", "c"):
                continue   # v2 已在位
            n = 1
            while (d / f"take{n}").exists():
                n += 1
            (d / f"take{n}").mkdir()
            for f in ("raw.mp4", "job.json"):
                if (d / f).exists():
                    shutil.move(str(d / f), str(d / f"take{n}" / f))
            tmp = d / "ltx_download.mp4"
            shutil.copyfile(path, tmp)
            validate(tmp)
            digest = hashlib.sha256(tmp.read_bytes()).hexdigest()
            tmp.replace(d / "raw.mp4")
            model = Path(path).parent.name
            (d / "job.json").write_text(json.dumps(dict(status="completed", via=f"ltx:{model}", sha256=digest,
                                                        take=name, source=Path(path).name), indent=2))
        print("applied")


if __name__ == "__main__":
    main()
