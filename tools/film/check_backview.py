"""Audit H3 rear views. Never edit submitted, leased, completed or unreadable claims."""
import argparse
import copy
import json
from pathlib import Path
import re
import shutil
import time

ROOT = Path(__file__).resolve().parents[2]
HIT = re.compile(r'back[- ]view|rear[- ]view|over[- ]the[- ]shoulder|from (?:low |just )?behind|back of (?:the |his |her )?head|背影|身后|背对|过肩|后脑|肩头|肩后|后背', re.I)
SUB = r'<Subject (\d+)>'
UNIQUE = 'Each subject appears exactly once; no duplicated people or animals.'
RETENTION = 'partially_preserved - only hair, back of head, shoulders and clothing are visible; the face is NOT visible in this shot'
STRICT = '<Subject {n}> is seen strictly from behind: the back of the head and hair only, no face, no eyes, no glasses visible on the back of the head; exactly one <Subject {n}> in the frame.'


def protected(sid, root=ROOT):
    """Same fail-closed claim semantics as h3_film_queue.farm_owned()."""
    d = root / 'renders' / sid
    if (d / 'raw.mp4').exists() or (d / 'job.json').exists():
        return True
    c = d / 'claim.json'
    if not c.exists():
        return False
    try:
        st = json.loads(c.read_text(encoding='utf-8'))
        return st.get('status') == 'done' or (st.get('status') == 'claimed' and st.get('lease_until', 0) > time.time())
    except (OSError, ValueError, TypeError, AttributeError):
        return True


def section(prompt, name):
    return prompt.split(name + ':', 1)[1].split('\n\n', 1)[0] if name + ':' in prompt else ''


def rear_subjects(shot):
    p = shot['prompt']
    detail = p.split('detailed_description:', 1)[-1].split('overall_soundscape:', 1)[0]
    ids = set()
    for pattern in [r'from (?:just |low )?behind (?:and above |the head of |the crouching )?' + SUB,
                    r'over the back of ' + SUB,
                    SUB + r", seen from behind",
                    SUB + r"'s [^.;\n]{0,100}shoulder[^.;\n]{0,130}foreground"]:
        ids.update(re.findall(pattern, detail, re.I))
    # Reviewed exceptional staging: side views/reflections are not strict rear views.
    overrides = {'cf_s03_11': {'1'}, 'cf_s07_03': set(), 'cf_s13_04': set(),
                 'cf_s11_11': {'1', '2'}, 'ec_s10_17': set(), 'ec_s15_16': set(),
                 'ec_s06_25': {'1'}}
    return overrides.get(shot['id'], ids)


def append_detail(p, sentence):
    if sentence in p:
        return p
    return p.replace('\n\noverall_soundscape:', '\n' + sentence + '\n\noverall_soundscape:', 1)


def replace_retention(p, n, text):
    start = p.index('retention_analysis:')
    end = p.index('detailed_description:', start)
    block, count = re.subn(r'(<Subject ' + n + r'>[^\n]*?: )[^\n]+', lambda m: m[1] + text, p[start:end])
    if count != 1:
        raise ValueError(f'Expected exactly one retention entry for Subject {n}')
    return p[:start] + block + p[end:]


def repair(shot):
    s = copy.deepcopy(shot)
    p = s['prompt']
    subjects = set(re.findall(SUB, section(p, 'subject_definitions')))
    hit = bool(HIT.search(p + s.get('summary_zh', '')))
    rear = rear_subjects(s) if hit else set()
    # This single-person exit has no need for an absolutely rear-on composition.
    if s['id'] == 'ec_s06_25':
        p = p.replace('Full shot, eye level, static.', 'Full shot from a 3/4 rear profile, eye level, static.')
        p = p.replace('walks away from the camera', 'walks diagonally away from the camera')
        p = replace_retention(p, '1', 'partially_preserved - hair, shoulders and clothing; the face is partially visible only from the side in a 3/4 rear profile')
        p = append_detail(p, '<Subject 1> is seen in 3/4 rear profile, with part of the face visible only at the side; no face, eyes or glasses on the back of the head; exactly one <Subject 1> in the frame.')
        rear = set()
    for n in sorted(rear):
        p = replace_retention(p, n, RETENTION)
        p = append_detail(p, STRICT.format(n=n))
    if s['id'] == 'ec_s15_16':
        for n in ('1', '2', '3'):
            p = replace_retention(p, n, 'partially_preserved - hair and clothing remain consistent; facial features appear only in the physically visible side profile, never on the back of the head')
        p = append_detail(p, 'Keep the three-quarter rear composition; faces are visible only at the side when a head naturally turns, never on the back of a head.')
    if s['id'] == 'ec_s10_17':
        p = replace_retention(p, '1', 'partially_preserved - the direct rear view preserves hair and clothing only; facial identity is preserved only in the physically correct mirror reflection')
        p = append_detail(p, 'The direct view of <Subject 1> shows only the back of his head, never facial features; his face is visible only in the mirror. Reflections belong to the same two people, not additional people.')
    if len(subjects) >= 2:
        p = append_detail(p, UNIQUE)
    s['prompt'] = p
    assert s.get('dialogue') == shot.get('dialogue')
    assert re.findall(r'<d>.*?</d>', p, re.S) == re.findall(r'<d>.*?</d>', shot['prompt'], re.S)
    assert set(re.findall(r'<Picture \d+>', p)) == set(re.findall(r'<Picture \d+>', shot['prompt']))
    assert len(s.get('refs', [])) <= 5
    return s, hit, sorted(rear)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--film', required=True, choices=['catfilm', 'echo'])
    parser.add_argument('--fix', action='store_true')
    parser.add_argument('--dry-run', action='store_true', help='Preview fixes without any writes; overrides --fix')
    args = parser.parse_args()
    counts = dict(hits=0, rewritten=0, skipped_as_rendered=0, backview_rewritten=0)
    for path in sorted((ROOT / 'films' / args.film / 'shots').glob('*.json')):
        old = json.loads(path.read_text(encoding='utf-8'))
        new = copy.deepcopy(old)
        changes = []
        for i, shot in enumerate(old):
            if shot.get('engine') != 'h3':
                continue
            hit = bool(HIT.search(shot['prompt'] + shot.get('summary_zh', '')))
            busy = protected(shot['id'])
            if hit:
                counts['hits'] += 1
                counts['skipped_as_rendered'] += int(busy)
                print(f"{shot['id']} rendered={str(busy).lower()}")
            if busy:
                continue
            revised, _, rear = repair(shot)
            if revised != shot:
                new[i] = revised
                changes.append(i)
                counts['rewritten'] += 1
                counts['backview_rewritten'] += int(hit)
                print(f"  {'fix' if args.fix and not args.dry_run else 'would-fix'} {shot['id']} rear={','.join(rear) or 'none/profile'}")
        if changes and args.fix and not args.dry_run:
            # Recheck immediately before saving; preserve any concurrent writer's edits.
            if json.loads(path.read_text(encoding='utf-8')) != old:
                raise RuntimeError(f'Concurrent change: {path}')
            if any(protected(old[i]['id']) for i in changes):
                raise RuntimeError(f'New render/lease appeared: {path}; rerun audit')
            backup = path.with_name(path.name + '.bak_backview')
            if not backup.exists():
                shutil.copy2(path, backup)
            temp = path.with_suffix('.json.tmp_backview')
            temp.write_text(json.dumps(new, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
            temp.replace(path)
    print(json.dumps(dict(film=args.film, applied=args.fix and not args.dry_run, **counts)))


if __name__ == '__main__':
    main()
