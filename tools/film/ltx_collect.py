"""Validate LTX uploads and register completed raw clips for rough_cut."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time
import fcntl

from film_config import FilmConfig, ROOT, add_film_args, safe_name
from ltx_stage import load_ltx


def validate(path):
    probe = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(path)],
                           capture_output=True, text=True, check=True)
    streams = json.loads(probe.stdout)['streams']
    videos = [s for s in streams if s['codec_type'] == 'video']
    if not videos or (videos[0]['width'], videos[0]['height']) != (1344, 768):
        raise ValueError('expected 1344x768 video')
    if not any(s['codec_type'] == 'audio' for s in streams):
        raise ValueError('missing audio')
    subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(path), '-map', '0:v:0',
                    '-map', '0:a:0', '-f', 'null', '-'], capture_output=True, check=True)


def collect(film, model=None, shots_dir=None):
    model = safe_name(model or f'ltx_{film.name}')
    renders = film.root / 'renders'
    farm = renders / 'farm'
    farm.mkdir(parents=True, exist_ok=True)
    completed = []
    # Serialize collectors; receipts are published only after the validated raw file.
    with (farm / f'ltx_collect_{film.name}.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for shot in load_ltx(film, shots_dir):
            sid = shot['id']
            folder = renders / sid
            receipt = folder / 'job.json'
            source = renders / 'lab' / model / f'{sid}_distilled.mp4'
            if receipt.exists() or not source.is_file():
                continue
            try:
                # Snapshot first: uploads can still be in progress. Validate exactly what we publish.
                folder.mkdir(parents=True, exist_ok=True)
                temp = folder / 'ltx_download.mp4'
                shutil.copyfile(source, temp)
                validate(temp)
                digest = hashlib.sha256(temp.read_bytes()).hexdigest()
                if receipt.exists():
                    continue
                temp.replace(folder / 'raw.mp4')
                with receipt.open('x', encoding='utf-8') as f:
                    json.dump(dict(status='completed', via=f'ltx:{model}', sha256=digest), f, indent=2)
                completed.append(sid)
                print(f'saved {sid} via ltx:{model}', flush=True)
            except (ValueError, OSError, subprocess.CalledProcessError) as exc:
                print(f'pending {sid}: {exc}', flush=True)
    return completed


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    add_film_args(ap)
    ap.add_argument('--model')
    ap.add_argument('--shots-dir', type=Path)
    ap.add_argument('--root', type=Path, default=ROOT)
    ap.add_argument('--watch', action='store_true')
    args = ap.parse_args()
    film = FilmConfig(args.film, args.root)
    while True:
        collect(film, args.model, args.shots_dir)
        if not args.watch:
            break
        time.sleep(60)


if __name__ == '__main__':
    main()
