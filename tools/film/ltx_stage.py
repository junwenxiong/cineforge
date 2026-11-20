"""Prepare LTX keyframes and per-film lab jobs; --dry-run never writes or draws."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

from film_config import FilmConfig, ROOT, add_film_args, safe_name


def load_ltx(film, shots_dir=None):
    if shots_dir:
        source = film.root / shots_dir
        paths = sorted(source.glob('*.json')) if source.is_dir() else [source]
        shots = [s for p in paths for s in json.loads(p.read_text(encoding='utf-8'))]
    else:
        shots = film.load_shots()
    result = [s for s in shots if s.get('engine') == 'ltx']
    keyframes = {}
    for path in sorted((film.workflow / 'keyframes').glob('*.json')):
        for item in json.loads(path.read_text(encoding='utf-8')):
            if item['id'] in keyframes:
                raise ValueError(f"Duplicate keyframe ID: {item['id']}")
            keyframes[item['id']] = item
    seen = set()
    for shot in result:
        sid = safe_name(shot['id'])
        if not sid.startswith(film.prefix + '_') or sid in seen:
            raise ValueError(f'Invalid or duplicate shot ID: {sid}')
        seen.add(sid)
        if sid in keyframes and not shot.get('keyframe_prompt'):
            shot['keyframe_prompt'] = keyframes[sid]['prompt']
            shot['refs'] = keyframes[sid].get('refs', shot.get('refs', []))
        if film.name == 'echo' and not shot.get('keyframe_prompt'):
            raise ValueError(f'{sid}: missing keyframes prompt')
    return result


def crop_keyframe(source, dest):
    """Keep relay originals and receipts; create a decoded 1344x768 center crop."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = dest.with_suffix('.crop.png')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(source),
                    '-vf', 'scale=1344:768:force_original_aspect_ratio=increase:flags=lanczos,crop=1344:768,setsar=1',
                    '-frames:v', '1', str(temp)], check=True)
    temp.replace(dest)
    receipt_path = source.with_suffix('.json')
    receipt = json.loads(receipt_path.read_text(encoding='utf-8')) if receipt_path.exists() else {}
    receipt.update(picked_from=str(source), final_size=[1344, 768],
                   final_sha256=hashlib.sha256(dest.read_bytes()).hexdigest())
    dest.with_suffix('.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')


def keyframe_path(film, shot):
    path = (film.root / shot['keyframe']).resolve()
    if film.assets.resolve() not in path.parents or path.suffix.lower() != '.png':
        raise ValueError(f"{shot['id']}: keyframe must be a PNG under assets/{film.name}")
    safe_name(path.stem)
    return path


STATIC_CAMERA = 'locked-off static camera, no zoom, no push-in, framing stays the same for the whole shot'


def static_prompt(prompt):
    # Remove contradictory legacy wording before adding a single camera instruction.
    prompt = re.sub(r'locked-off camera with a (?:very )?slow push-in', STATIC_CAMERA, prompt, flags=re.I)
    prompt = re.sub(r'(?<!no )\b(?:slow(?:ly)? |gentle |gradual )?(?:push(?:es)?[ -]in|zoom(?:s)?[ -]in)\b', 'static framing', prompt, flags=re.I)
    if STATIC_CAMERA not in prompt:
        prompt += '. Camera: ' + STATIC_CAMERA + '.'
    return prompt


def framing_prompt(shot):
    if shot.get('shot_size') in ('CU', 'ECU'):
        return ' Respect the scripted ' + shot['shot_size'] + ' framing.'
    return ' Use MS or MCU framing with shoulders, headroom and clearly visible environment; never a face-filling close-up.'


def stage(film, shots_dir=None, model=None, dry_run=False, draw=False):
    model = safe_name(model or f'ltx_{film.name}')
    farm = film.root / 'renders/farm'
    shots = load_ltx(film, shots_dir)
    groups = {}
    pending = []
    blocked = []
    missing_refs = {}
    for shot in shots:
        sid = shot['id']
        # Any receipt is owned; never re-submit failed/in-flight work implicitly.
        if (film.root / 'renders' / sid / 'job.json').exists():
            blocked.append(sid)
            continue
        prompt = shot.get('ltx_prompt') or shot.get('prompt')
        if not prompt:
            raise ValueError(f'{sid}: missing ltx_prompt / prompt')
        prompt = static_prompt(prompt)
        path = keyframe_path(film, shot)
        refs = shot.get('refs', [])
        missing = [r for r in refs if not (film.root / r).is_file()]
        if missing:
            missing_refs[sid] = missing
            print(f'{sid}: skipped missing refs: {missing}', file=sys.stderr)
            continue
        pending.append((shot, path, prompt))
        if not path.is_file():
            item = dict(id=path.stem, prompt=shot.get('keyframe_prompt') or
                        ('Draw a single opening keyframe for this scene. Preserve the identities in the reference images. '
                         '16:9, no text or subtitles. Depict the initial pose, not a montage.\n' + prompt), refs=refs)
            item['prompt'] += framing_prompt(shot)
            group = groups.setdefault(path.parent, {})
            if path.stem in group and group[path.stem] != item:
                raise ValueError(f'Conflicting keyframe specs: {path}')
            group[path.stem] = item
    specs = []
    for i, (directory, items) in enumerate(sorted(groups.items())):
        spec = farm / f'ltx_keyframes_{model}_{i}.json'
        command = [sys.executable, str(ROOT / 'tools/film/gpt_images.py'), '--film', film.name,
                   str(spec), '--out', str(directory / 'source'), '-j', '4']
        specs.append(dict(path=str(spec), items=list(items.values()), command=shlex.join(command)))
        if not dry_run:
            farm.mkdir(parents=True, exist_ok=True)
            spec.write_text(json.dumps(list(items.values()), ensure_ascii=False, indent=2), encoding='utf-8')
            print(shlex.join(command), file=sys.stderr)
            if draw:
                subprocess.run(command, cwd=film.root, check=True)
            for item in items.values():
                source = directory / 'source' / (item['id'] + '.png')
                if source.is_file() and source.with_suffix('.json').is_file():
                    crop_keyframe(source, directory / (item['id'] + '.png'))
    jobs = []
    for shot, path, prompt in pending:
        if not path.is_file():
            continue
        dest = film.assets / 'lab_kf_ltx' / f"{shot['id']}.png"
        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, dest)
        jobs.append(dict(id=shot['id'], seconds=shot.get('seconds', 6),
                         keyframe=dest.relative_to(film.root).as_posix(), prompt=prompt))
    target = farm / f'lab_jobs_{model}.json'
    if not dry_run:
        farm.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix('.json.tmp')
        temp.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(target)
    return dict(film=film.name, model=model, ltx_shots=len(shots), skipped_receipts=blocked,
                missing_refs=missing_refs,
                jobs_path=str(target), jobs=jobs, keyframe_specs=specs,
                missing_keyframes=[s['id'] for s, p, _ in pending if not p.is_file()])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    add_film_args(ap)
    ap.add_argument('--shots-dir', type=Path, help='Directory or single scene JSON')
    ap.add_argument('--model')
    ap.add_argument('--root', type=Path, default=ROOT, help='Isolated project root for local checks')
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--draw', action='store_true')
    args = ap.parse_args()
    if args.draw and args.root.resolve() != ROOT.resolve():
        ap.error('--draw requires the real project root')
    print(json.dumps(stage(FilmConfig(args.film, args.root), args.shots_dir, args.model,
                           args.dry_run, args.draw), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
