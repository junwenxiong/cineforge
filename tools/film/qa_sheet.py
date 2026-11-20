"""Build contact sheets using scene shot manifests, independent of ID spelling."""
import argparse
import json
import subprocess
from pathlib import Path
from film_config import FilmConfig, add_film_args


def main():
    ap = argparse.ArgumentParser()
    add_film_args(ap)
    ap.add_argument('scenes', nargs='+')
    args = ap.parse_args()
    film = FilmConfig(args.film)
    dest = film.root / 'renders/qa'
    if film.name != 'starcore':
        dest /= film.name
    dest.mkdir(parents=True, exist_ok=True)
    for scene in args.scenes:
        scene = next((s for s in film.order if s.lower() == scene.lower()), scene)
        shots = json.loads((film.shots / f'{scene}.json').read_text(encoding='utf-8'))
        images = []
        for shot in shots:
            sid = shot['id']
            raw = film.root / 'renders' / sid / 'raw.mp4'
            if not raw.is_file():
                continue
            image = dest / f'_{sid}.jpg'
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(raw), '-vf',
                            "select='eq(n\\,12)+eq(n\\,72)+eq(n\\,130)',scale=224:-1,tile=3x1,"
                            f"drawtext=text={sid.removeprefix(film.prefix + '_')}:x=4:y=4:fontsize=18:fontcolor=yellow",
                            '-vsync', '0', '-frames:v', '1', str(image)], check=True)
            images.append(image)
        if not images:
            print(f'{scene}: no shots')
            continue
        listing = dest / f'_{scene.lower()}.txt'
        listing.write_text(''.join(f"file '{p.as_posix()}'\n" for p in images))
        out = dest / f'{scene.lower()}.jpg'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', str(listing),
                        '-vf', f'tile=2x{(len(images)+1)//2}', '-frames:v', '1', str(out)], check=True)
        print(f'{out}  {len(images)} shots')


if __name__ == '__main__':
    main()
