"""Validate a film's shot structure without network or GPU work."""
import argparse
import json
from pathlib import Path
import re
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent / 'film'))
from film_config import FilmConfig, ROOT


def validate(film, require_media=False):
    errors, missing = [], []
    shots = film.load_shots()
    seen = set()
    for shot in shots:
        sid = shot['id']
        if sid in seen: errors.append(f'{sid}: duplicate ID')
        seen.add(sid)
        if not isinstance(shot.get('seconds'), (int, float)) or shot['seconds'] <= 0:
            errors.append(f'{sid}: seconds must be positive')
        prompt = (shot.get('ltx_prompt') or shot.get('prompt')) if shot.get('engine') == 'ltx' else shot.get('prompt')
        if not isinstance(prompt, str) or not prompt.strip():
            errors.append(f'{sid}: missing prompt')
        refs = shot.get('refs', [])
        if not isinstance(refs, list) or len(refs) > 5:
            errors.append(f'{sid}: refs must be a list of at most five paths'); continue
        for picture in re.findall(r'<Picture\s+(\d+)>', shot.get('prompt', '')):
            if not 1 <= int(picture) <= len(refs):
                errors.append(f'{sid}: Picture {picture} has no reference')
        media = refs + ([shot['keyframe']] if shot.get('keyframe') else [])
        for rel in media:
            if not isinstance(rel, str):
                errors.append(f'{sid}: media path must be text'); continue
            path = (film.root / rel).resolve()
            if film.root not in path.parents or Path(rel).is_absolute():
                errors.append(f'{sid}: media path escapes project'); continue
            if not path.is_file(): missing.append(rel)
        for line in shot.get('dialogue', []):
            if not isinstance(line, dict) or not all(isinstance(line.get(k), str) for k in ['who','text']):
                errors.append(f'{sid}: invalid dialogue')
    if require_media and missing: errors.append(f'{len(set(missing))} missing media files')
    return {'film':film.name,'shots':len(shots),'planned_seconds':sum(s.get('seconds',0) for s in shots),
            'missing_media':len(set(missing)), 'errors':errors}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--film',default='starcore'); ap.add_argument('--require-media',action='store_true')
    a=ap.parse_args()
    film=FilmConfig(a.film)
    if not (film.workflow / 'film.json').exists(): ap.error('Create the working film first with tools/new_film.py')
    result=validate(film,a.require_media)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(bool(result['errors']))


if __name__=='__main__': main()
