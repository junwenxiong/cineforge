"""Create a local editable film from a bundled text example; never overwrite."""
import argparse
import json
from pathlib import Path
import shutil
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent / 'film'))
from film_config import ROOT, FilmConfig, safe_name


def create(name, example='_template', root=ROOT):
    name, example = safe_name(name), safe_name(example)
    source = root / 'examples' / example
    dest = root / 'films' / name
    if not source.is_dir():
        raise ValueError('Unknown example')
    if dest.exists():
        raise ValueError('Film already exists; refusing to overwrite')
    meta = json.loads((source / 'film.json').read_text())
    old_prefix = meta.get('render_prefix', example)
    prefix = old_prefix if name == example else name
    for other in (root / 'films').glob('*/film.json'):
        if json.loads(other.read_text()).get('render_prefix') == prefix:
            raise ValueError('Render prefix already used by another film')
    shutil.copytree(source, dest)
    for p in dest.rglob('*'):
        if p.is_file():
            text = p.read_text().replace(f'assets/{example}/', f'assets/{name}/').replace(f'films/{example}/', f'films/{name}/')
            if name != example and p.suffix == '.json':
                text = text.replace(old_prefix + '_', prefix + '_')
            p.write_text(text)
    meta['render_prefix'] = prefix
    (dest / 'film.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n')
    for folder in ['refs', 'music']:
        (root / 'assets' / name / folder).mkdir(parents=True, exist_ok=True)
    (dest / 'shots').mkdir(exist_ok=True)
    return dest


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('name'); ap.add_argument('--example', default='_template')
    args = ap.parse_args()
    try:
        print(create(args.name, args.example).relative_to(ROOT))
    except ValueError as exc:
        ap.error(str(exc))


if __name__ == '__main__': main()
