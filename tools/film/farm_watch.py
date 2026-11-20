"""实时盯每台出片机器：Colab 工作机超过 LIMIT 秒没交片、心跳中断，或 Box 队列没动静，就打印一行告警（供 Monitor 读取）。
另外每 5 分钟打印一行总进度。用法：python3 -u tools/film/farm_watch.py
"""
import argparse
from film_config import FilmConfig, add_film_args
import json
import re
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FARM = ROOT / "renders/farm"
FILM = FilmConfig()
LIMIT = 300
warned = set()
last_report = 0


def today_ts(hms):
    t = time.localtime()
    h, m, s = map(int, hms.split(":"))
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, h, m, s, 0, 0, -1))


def remaining():
    left = 0
    for f in FILM.shots.glob("*.json"):
        try:
            for s in json.loads(f.read_text(encoding="utf-8")):
                j = ROOT / "renders" / s["id"] / "job.json"
                try:
                    ok = json.loads(j.read_text()).get("status") in ("completed", "failed")
                except Exception:
                    ok = False
                left += not ok
        except Exception:
            pass
    return left


def alert(key, msg):
    if key not in warned:
        warned.add(key)
        print(time.strftime("%H:%M ") + msg, flush=True)


def queue_tail(path):
    return (path.read_text(encoding='utf-8', errors='replace').splitlines() or ['no queue log'])[-1] if path.exists() else 'no queue log'


def main():
    global FILM, last_report
    ap = argparse.ArgumentParser()
    add_film_args(ap)
    args = ap.parse_args()
    FILM = FilmConfig(args.film)
    while True:
        now = time.time()
        try:
            tok = (FARM / "token").read_text().strip()
            st = json.loads(urllib.request.urlopen(f"http://127.0.0.1:8765/status?t={tok}", timeout=10).read())
        except Exception as e:
            st = {}
            alert("server", f"派片服务无响应: {e}")
        drain = set((FARM / "drain").read_text().split()) if (FARM / "drain").exists() else set()
        log = (FARM / "farm.log").read_text(encoding="utf-8", errors="replace").splitlines()
        active = []
        for w, v in st.items():
            if w in drain or v.get("state") == "finished" or now - v.get("seen", 0) > 3600:
                continue
            if now - v.get("seen", 0) > 150:
                alert(f"hb:{w}", f"掉线: {w} 已 {int((now - v['seen']) / 60)} 分钟没有心跳")
                continue
            active.append(w)
            times = [l[:8] for l in log if re.search(rf"(saved .* from {re.escape(w)} |claim .* -> {re.escape(w)}$|worker {re.escape(w)} state)", l)]
            saves = [l[:8] for l in log if re.search(rf"saved .* from {re.escape(w)} ", l)]
            ref = saves[-1] if saves else (times[0] if times else None)
            if ref is None:
                continue
            age = now - today_ts(ref)
            if age > LIMIT:
                alert(f"idle:{w}", f"闲置/卡住: {w} 已 {int(age / 60)} 分钟没交片（状态 {v.get('state')}/{v.get('service')}，手上 {v.get('current')}）")
            else:
                warned.discard(f"idle:{w}")
            warned.discard(f"hb:{w}")
        qlog = ROOT / f"renders/{FILM.name}_queue.log"
        age = now - qlog.stat().st_mtime if qlog.exists() else 0
        if age > 360:
            alert("box", f"Box 队列 {int(age / 60)} 分钟没动静: {queue_tail(qlog)[:70]}")
        else:
            warned.discard("box")
        if now - last_report > 300:
            last_report = now
            r = remaining()
            print(time.strftime("%H:%M ") + f"剩余 {r} 镜 | 在拍 Colab: {' '.join(active)} | Box: {queue_tail(qlog)[:45]}", flush=True)
            if r == 0:
                print("全部拍完", flush=True)
                break
        time.sleep(60)

if __name__ == '__main__':
    main()
