"""Conservative dialogue out-points using ffmpeg only (no speech models).

Sound above -40 dBFS is retained, including foley: this is an energy-based
speech-end estimate, not semantic VAD. No terminal silence means keep the tail.
Dry-run performs analysis and prints JSON without changing any files.
"""
import argparse
import json
import re
import subprocess
from film_config import FilmConfig, add_film_args

NOISE_DB = -40
MIN_SILENCE = 0.15


def analyze(path):
    probe = json.loads(subprocess.run([
        'ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)
    ], capture_output=True, text=True, check=True).stdout)
    video = next(s for s in probe['streams'] if s['codec_type'] == 'video')
    audio = next(s for s in probe['streams'] if s['codec_type'] == 'audio')
    duration = min(float(video.get('duration', probe['format']['duration'])),
                   float(audio.get('duration', probe['format']['duration'])))
    result = subprocess.run([
        'ffmpeg', '-hide_banner', '-nostats', '-i', str(path), '-vn', '-af',
        f'silencedetect=n={NOISE_DB}dB:d={MIN_SILENCE}', '-f', 'null', '-'
    ], capture_output=True, text=True, check=True)
    events = [(kind, float(value)) for kind, value in re.findall(
        r'silence_(start|end):\s*([\d.]+)', result.stderr)]
    # ffmpeg emits silence_end at EOF too. Only a silence interval reaching
    # the audio endpoint can establish that the last sound has finished.
    end = duration
    start = None
    for kind, value in events:
        if kind == 'start':
            start = value
        elif start is not None:
            if value >= duration - 0.03:
                end = min(start, duration)
            start = None
    if start is not None:
        end = min(start, duration)
    return duration, end


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    add_film_args(ap)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    film = FilmConfig(args.film)
    shots = film.load_shots()
    cuts = json.loads(film.cuts.read_text(encoding='utf-8')) if film.cuts.exists() else {}
    rows = []
    for shot in shots:
        if not any(d.get('text') for d in shot.get('dialogue', [])):
            continue
        duration, end = analyze(film.root / 'renders' / shot['id'] / 'raw.mp4')
        default = min(duration, shot['seconds'] * 0.92)
        # Preserve the default floor, except the mandatory 50ms EOF margin
        # when the source itself is shorter than the nominal default.
        out = min(duration - 0.05, max(default, end + 0.25))
        cuts.setdefault(shot['id'], {})['out'] = round(out, 6)
        rows.append(dict(id=shot['id'], duration=duration, default_out=default,
                         speech_end=round(end, 6), out=round(out, 6),
                         default_clips_energy=end > default,
                         ambiguous_tail=end >= duration - 0.03))
    report = dict(film=film.name, shots=len(shots), dialogue_shots=len(rows),
                  threshold_dbfs=NOISE_DB, minimum_silence=MIN_SILENCE,
                  method='Conservative final audible activity; foley may extend speech estimate',
                  default_clipped=sum(r['default_clips_energy'] for r in rows), shots_analyzed=rows)
    if args.dry_run:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        film.cuts.write_text(json.dumps(cuts, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        (film.workflow / 'speech_cut_report.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"{len(rows)} dialogue shots; {report['default_clipped']} would have audible tails clipped by default"
          ' (energy proxy includes foley).')


if __name__ == '__main__':
    main()
