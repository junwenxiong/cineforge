"""Shared per-film paths. Names and shot IDs are portable path components."""
import argparse
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def safe_name(name):
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_-]*', name):
        raise ValueError(f'Invalid film/scene/shot name: {name!r}')
    return name


def add_film_args(parser, multiple=False):
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--film', default=None)
    if multiple:
        group.add_argument('--films', help='Comma-separated films in priority order')


def film_names(args):
    value = getattr(args, 'films', None) or args.film or os.environ.get('FILM', 'starcore')
    names = [safe_name(n.strip()) for n in value.split(',')]
    if len(names) != len(set(names)):
        raise ValueError('Duplicate film names')
    return names


class FilmConfig:
    def __init__(self, name=None, root=ROOT):
        self.name = safe_name(name or os.environ.get('FILM', 'starcore'))
        self.root = Path(root).resolve()
        self.workflow = self.root / 'films' / self.name
        self.assets = self.root / 'assets' / self.name
        self.videos = self.root / 'videos' / self.name
        self.shots = self.workflow / 'shots'
        self.refs = self.assets / 'refs'
        self.music = self.assets / 'music'
        self.cuts = self.workflow / 'cut.json'
        self.cache = self.root / 'renders' / f'{self.name}_cut'
        p = self.workflow / 'film.json'
        self.metadata = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
        self.prefix = safe_name(self.metadata.get('render_prefix', 'sc' if self.name == 'starcore' else self.name))
        p = self.workflow / 'scenes.json'
        if p.exists():
            scenes = json.loads(p.read_text(encoding='utf-8'))
            if isinstance(scenes, dict):
                scenes = scenes['scenes']
            self.order = [safe_name(s if isinstance(s, str) else s['id']) for s in scenes]
        else:
            self.order = (['P01'] + [f'S{i:02d}' for i in range(1, 40)] if self.name == 'starcore'
                          else sorted(p.stem for p in self.shots.glob('*.json')))
        if len(self.order) != len(set(self.order)):
            raise ValueError('Duplicate scenes')
        self.title = self.metadata.get('title', '星核黎明')
        self.title_en = self.metadata.get('title_en', 'STARCORE  DAWN')
        self.credits = self.metadata.get('credits')
        self.credits_seconds = self.metadata.get('credits_seconds', 62)
        self.credits_music = self.metadata.get('credits_music', 'cue8_credits_scottbuckley_legacy.mp3')

    def load_shots(self):
        items = []
        for scene in self.order:
            p = self.shots / f'{scene}.json'
            if p.exists():
                items.extend(json.loads(p.read_text(encoding='utf-8')))
        for shot in items:
            safe_name(shot['id'])
            if not shot['id'].startswith(self.prefix + '_'):
                raise ValueError(f"{self.name}: shot {shot['id']} must start with {self.prefix}_")
        return items


def main():
    ap = argparse.ArgumentParser()
    add_film_args(ap)
    ap.add_argument('--field', choices=['name', 'prefix'], default='name')
    args = ap.parse_args()
    print(getattr(FilmConfig(args.film), args.field))


if __name__ == '__main__':
    main()
