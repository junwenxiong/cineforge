"""Incrementally extract 25%, 50%, 85% anatomy QA strips; never alter videos."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'renders/qa/anatomy'


def extract(video):
    dest = OUT / (video.parent.name + '.jpg')
    if dest.exists():
        return 'skipped'
    meta = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_format', '-of', 'json', str(video)]))
    duration = float(meta['format']['duration'])
    command = ['ffmpeg', '-v', 'error', '-y']
    for fraction in (.25, .5, .85):
        command += ['-threads', '1', '-ss', str(duration * fraction), '-i', str(video)]
    filters = ';'.join(f'[{i}:v]scale=448:-2[v{i}]' for i in range(3))
    filters += ';[v0][v1][v2]hstack=inputs=3[out]'
    temporary = dest.with_suffix('.tmp.jpg')
    command += ['-filter_complex_threads', '1', '-filter_complex', filters, '-map', '[out]', '-frames:v', '1', '-threads', '1', '-q:v', '2', str(temporary)]
    subprocess.run(command, check=True, capture_output=True)
    temporary.replace(dest)
    return 'created'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    videos = sorted(ROOT.glob('renders/*/raw.mp4'))
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(extract, videos))
    print(json.dumps({'total': len(videos), 'created': outcomes.count('created'), 'skipped': outcomes.count('skipped')}))


if __name__ == '__main__':
    main()
