"""每 30 秒把已出片（renders/<id>/raw.mp4 存在）的镜头从 LTX 任务单里删掉，配合 ltx25.py 每镜开拍前重读任务单，避免两台机器重复拍。
用法：python3 tools/film/ltx_prune.py ltx_catfilm ltx_echo
"""
import json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
while True:
    for m in sys.argv[1:]:
        f = ROOT / f"renders/farm/lab_jobs_{m}.json"
        jobs = json.loads(f.read_text(encoding="utf-8"))
        keep = [j for j in jobs if not (ROOT / "renders" / j["id"] / "raw.mp4").exists()]
        if len(keep) != len(jobs):
            tmp = f.with_suffix(".tmp"); tmp.write_text(json.dumps(keep, ensure_ascii=False, indent=1), encoding="utf-8"); tmp.replace(f)
            print(time.strftime("%H:%M:%S"), m, len(jobs), "->", len(keep), flush=True)
    time.sleep(30)
