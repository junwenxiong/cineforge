"""把质检不合格的 H3 镜头改好提示词后重新派给农场（只走 farm_server 一个入口）。

用法（WSL，项目根目录）：
  python3 tools/film/retake.py --film catfilm --flags renders/qa/anatomy_flags.json [--only id ...] [--dry-run]
每镜：①按 check_backview.repair() 改提示词（背影不露脸、每人只出现一次），尾巴/分身缺陷再加针对性约束；
      ②原成片和回执移到 renders/<id>/take<N>/；③claim.json 写成 status=retake、attempts=0，农场会重新派片。
正在派片中（租约有效）的镜头跳过。
"""
import argparse, json, shutil, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from check_backview import repair, append_detail, UNIQUE  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
R = ROOT / "renders"
HUMAN = "partially_preserved - only hair, back of head, shoulders and clothing are visible; the face is NOT visible in this shot"
ANIMAL = "partially_preserved - seen from behind: the same fur colours, back patches, ears and tail stay identical; the face is NOT visible in this shot"


def shots_of(film):
    for f in sorted((ROOT / "films" / film / "shots").glob("S*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        yield f, d, (d if isinstance(d, list) else d["shots"])


def fix_prompt(shot, defect):
    shot["prompt"] = repair(shot)[0]["prompt"]
    p = shot["prompt"]
    lines = p.split("\n")
    for i, l in enumerate(lines):   # 动物用动物的保留写法
        subj = l.split(" (")[0]          # "<Subject N>"
        sdef = next((x for x in lines if x.startswith(subj + " is")), "").lower()
        if HUMAN in l and any(w in sdef for w in (" cat", " fur", " dog", " tail")):
            lines[i] = l.replace(HUMAN, ANIMAL)
    p = "\n".join(lines)
    if "尾" in defect:
        p = append_detail(p, "Every cat has exactly one tail; no extra or split tails.")
    if any(k in defect for k in ("复制", "重复", "两个", "多出", "四名", "两台")):
        p = append_detail(p, "Exactly the characters listed in subject_definitions appear, each exactly once; no twins, no look-alike extras, no second copy of any robot or animal.")
    if UNIQUE not in p:
        p = append_detail(p, UNIQUE)
    shot["prompt"] = p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--film", required=True)
    ap.add_argument("--flags", required=True)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    flags = {x["id"]: x["defect"] for x in json.loads((ROOT / a.flags).read_text(encoding="utf-8"))}
    if a.only:
        flags = {k: v for k, v in flags.items() if k in a.only}
    done = []
    for f, d, shots in shots_of(a.film):
        hit = [s for s in shots if s["id"] in flags]
        if not hit:
            continue
        todo = []
        for s in hit:
            c = R / s["id"] / "claim.json"
            st = json.loads(c.read_text(encoding="utf-8")) if c.exists() else {}
            if st.get("status") == "claimed" and st.get("lease_until", 0) > time.time():
                print("skip (in flight)", s["id"]); continue
            fix_prompt(s, flags[s["id"]])
            todo.append(s["id"])
        if a.dry_run:
            print("would retake", todo); continue
        bak = f.with_name(f.name + ".bak_retake")
        if not bak.exists():
            shutil.copy2(f, bak)
        f.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")   # 先写好新提示词，再放开派片
        for sid in todo:
            d_ = R / sid
            n = 1
            while (d_ / f"take{n}").exists():
                n += 1
            take = d_ / f"take{n}"; take.mkdir()
            for name in ("job.json", "raw.mp4", "claim.json"):
                if (d_ / name).exists():
                    shutil.move(str(d_ / name), str(take / name))
            (d_ / "claim.json").write_text(json.dumps({"status": "retake", "attempts": 0, "lease_until": 0,
                                                       "history": [f"take{n}: {flags[sid]}"]}, ensure_ascii=False, indent=1), encoding="utf-8")
            done.append(sid)
    print(json.dumps({"retake": done}, ensure_ascii=False))


if __name__ == "__main__":
    main()
