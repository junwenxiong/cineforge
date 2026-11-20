"""Stage final-film sources for /lab/kf. Run only while VSR shards are stopped."""
import argparse
from film_config import FilmConfig, add_film_args, film_names
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def sha256(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def decoded(path):
    if not path.is_file():
        return False
    probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                            '-show_entries', 'stream=width,height', '-of', 'json', str(path)],
                           capture_output=True, text=True)
    if probe.returncode or not json.loads(probe.stdout).get('streams'):
        return False
    return subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-i', str(path),
                           '-f', 'null', '-'], capture_output=True).returncode == 0


def main():
    ap = argparse.ArgumentParser()
    add_film_args(ap, multiple=True)
    ap.add_argument('--name', default='final')
    args = ap.parse_args()
    films = [FilmConfig(n) for n in film_names(args)]
    shots = [dict(s, _film=film.name) for film in films for s in json.loads((film.videos / f'{args.name}.json').read_text())['shots']]
    # Compatibility transport spool: existing /lab/kf and VSR worker stay unchanged.
    # IDs retain each film prefix; canonical assets/outputs remain per-film.
    stage = ROOT / 'assets/starcore/lab_kf_vsr'
    stage.mkdir(parents=True, exist_ok=True)
    jobs, seen, skipped = [], set(), 0
    for index, shot in enumerate(shots):
        sid = shot['id']
        if sid in seen:
            continue
        seen.add(sid)
        if decoded(ROOT / f'renders/lab/vsr/{sid}.mp4'):
            skipped += 1
            continue
        src, dst = ROOT / f'renders/{sid}/raw.mp4', stage / f'{sid}.mp4'
        digest = sha256(src)
        canonical = FilmConfig(shot['_film']).assets / 'lab_kf_vsr' / f'{sid}.mp4'
        canonical.parent.mkdir(parents=True, exist_ok=True)
        if canonical != dst and (not canonical.exists() or sha256(canonical) != digest):
            shutil.copy2(src, canonical)
        if not dst.exists() or sha256(dst) != digest:
            shutil.copy2(src, dst)
        if sha256(dst) != digest:
            raise RuntimeError(f'{sid}: staged checksum mismatch')
        jobs.append(dict(id=sid, index=index, input=dst.relative_to(ROOT).as_posix(), sha256=digest))
    target = ROOT / 'renders/farm/lab_jobs_vsr.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(jobs, indent=1) + '\n')
    temporary.replace(target)
    print(f'{len(seen)} unique shots; {len(jobs)} staged; {skipped} finished/decodable omitted; {target}')


if __name__ == '__main__':
    main()
