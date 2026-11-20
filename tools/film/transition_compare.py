"""Build an honest, deterministic cut comparison from existing masters (FFmpeg only).

python3 tools/film/transition_compare.py --film echo --a final --b final_v2
--dry-run validates sources/time mapping and prints the plan without writing outputs.
Shot sizes are editorial metadata, not measurements of faces. Metrics are measured
on scored/subtitled masters, so they are not directly comparable to raw-source QA.
"""
import argparse
import json
import math
import re
import shlex
import statistics
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

from film_config import FilmConfig, ROOT, safe_name


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def run(args):
    return subprocess.check_output(args)


def ff(*args):
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                    '-threads', '2', '-filter_complex_threads', '1', '-filter_threads', '1',
                    *map(str, args)], check=True)


def probe(path):
    return json.loads(run(['ffprobe', '-v', 'error', '-show_streams', '-show_format',
                           '-of', 'json', str(path)]))


def video_info(path):
    p = probe(path)
    v = next(s for s in p['streams'] if s['codec_type'] == 'video')
    return float(v.get('duration', p['format']['duration'])), float(Fraction(v['r_frame_rate']))


def packets(path, intervals):
    p = json.loads(run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                       '-read_intervals', intervals, '-show_packets', '-show_data_hash', 'sha256',
                       '-show_entries', 'packet=pts_time,data_hash', '-of', 'json', str(path)]))
    return {x['data_hash']: float(x['pts_time']) for x in p['packets']}


def edit(film, name):
    master = film.videos / f'{name}_master.mp4'
    if not master.exists():
        raise ValueError(f'Master not ready: {master}. Finish the master build before comparing.')
    tl = read(film.videos / f'{name}.json')
    body = film.videos / f'_{name}_subbed.mp4'
    if not body.exists():
        raise ValueError(f'Cannot verify master time mapping: missing {body}')
    bd, fps = video_info(body)
    md, mfps = video_info(master)
    end = max(s['start'] + s['length'] for s in tl['shots'])
    if abs(bd - end) > .15 or abs(fps - mfps) > .001:
        raise ValueError(f'{name}: timeline/body duration or frame rate mismatch: {end}, {bd}')
    # master.py overlays titles on the body, then appends credits. Verify that
    # exact encoded body packets survive at beginning, middle AND end of master.
    offsets, counts = [], []
    for t in (0, bd / 2, max(0, bd - 4)):
        interval = f'{t:.6f}%+2'
        a, b = packets(body, interval), packets(master, interval)
        shared = a.keys() & b.keys()
        if len(shared) < 8:
            raise ValueError(f'{name}: cannot verify unchanged body packets at {t:.3f}s')
        offsets.extend(b[k] - a[k] for k in shared)
        counts.append(len(shared))
    offset = statistics.median(offsets)
    if max(abs(x - offset) for x in offsets) > .002:
        raise ValueError(f'{name}: nonconstant master offset')
    # Verify appended duration against the actual credits file, not a guessed title offset.
    lists = [film.videos / f'_{name}_master_list.txt', film.videos / '_master_list.txt']
    credits = None
    for p in lists:
        if p.exists():
            files = [Path(shlex.split(x)[1]) for x in p.read_text().splitlines() if x.startswith('file ')]
            if len(files) == 2 and files[0].resolve() == body.resolve():
                credits = files[1]
                break
    if credits is None or not credits.exists():
        raise ValueError(f'{name}: missing matching master concat manifest/credits')
    cd, _ = video_info(credits)
    if abs(md - bd - cd) > .2:
        raise ValueError(f'{name}: master/body/credits durations do not agree: {md}, {bd}, {cd}')
    return dict(name=name, master=str(master), shots=tl['shots'], fps=fps,
                mapping=dict(offset_seconds=offset, body_duration=bd, master_duration=md,
                             timeline_duration=end, credits_duration=cd,
                             matched_packets=counts, method='identical video packet hashes at start/middle/end; titles overlaid; credits appended'))


def choose(baseline, reframes, a, b, n, slam=()):
    adjacent = lambda e: {(x['id'], y['id']): i for i, (x, y) in enumerate(zip(e['shots'], e['shots'][1:]))}
    ai, bi = adjacent(a), adjacent(b)
    candidates = [p for p in baseline['pairs'] if (p['from'], p['to']) in ai and (p['from'], p['to']) in bi]
    priority = [p for p in candidates if not p['scene_boundary'] and (p.get('size_jump') or 0) > 2
                and (p['from'] in reframes or p['to'] in reframes)]
    key = lambda p: ai[p['from'], p['to']]
    priority.sort(key=lambda p: (-(p['size_jump']), key(p)))
    # Alternate the two descending rankings: avoids adding LU and RGB units.
    lu = sorted(candidates, key=lambda p: (-p['loudness_jump'], key(p)))
    rgb = sorted(candidates, key=lambda p: (-p['rgb_jump'], key(p)))
    # 镜内"人脸怼上来"：v1 里人脸放大最多、v2 换了新条的镜头，看它和下一镜的接点
    slams = [p for sid in slam for p in candidates if p['from'] == sid and p not in priority]
    ranked = priority[:max(1, n - len(slams))] + slams + priority + [p for pair in zip(lu, rgb) for p in pair]
    chosen, seen = [], set()
    for p in ranked:
        k = (p['from'], p['to'])
        if k not in seen:
            why = ('reframed size jump' if p in priority else
                   'in-shot face push (v1 face grows, replaced by static take)' if p in slams else 'largest loudness/colour gap')
            chosen.append(dict(p, selection_reason=why))
            seen.add(k)
        if len(chosen) >= n:
            break
    return sorted(chosen, key=key)


def fingerprint(path, time, count=1):
    return run(['ffmpeg', '-v', 'error', '-threads', '1', '-ss', str(max(0,time)),
                '-i', str(path), '-frames:v', str(count), '-vf',
                'scale=64:36,crop=64:24:0:6', '-threads', '1', '-pix_fmt', 'gray',
                '-f', 'rawvideo', '-'])


def align_cut(film, e, x, y, nominal):
    """Resolve encoder/concat frame duplication against immutable edited segments."""
    manifest = film.cache / f"{e['name']}.txt"
    paths = [Path(shlex.split(line)[1]) for line in manifest.read_text().splitlines()
             if line.startswith('file ')]
    if len(paths) != len(e['shots']):
        raise ValueError(f'{manifest}: segment count mismatch')
    cache = dict(zip((s['id'] for s in e['shots']), paths))
    for sid in (x['id'], y['id']):
        if not cache[sid].name.startswith(sid + '_'):
            raise ValueError(f'{manifest}: segment order mismatch')
    xd, _ = video_info(cache[x['id']])
    ref = [fingerprint(cache[x['id']], xd - 1/e['fps']), fingerprint(cache[y['id']], 0)]
    data = fingerprint(e['master'], nominal - 4/e['fps'], count=9)
    frames = {k:data[(k+4)*1536:(k+5)*1536] for k in range(-4,5)}
    mse = lambda a,b: sum((u-v)**2 for u,v in zip(a,b))/len(a)
    if any(len(f) != 1536 for f in ref + list(frames.values())):
        raise ValueError('Incomplete boundary alignment frame')
    scores = {k:(mse(frames[k-1],ref[0])+mse(frames[k],ref[1]))/2 for k in range(-3,5)}
    best = min(scores, key=lambda k:(scores[k],abs(k),k))
    if best in (-3,4) or scores[best] > 400:
        raise ValueError(f"Cannot confidently align {x['id']} → {y['id']}: {scores}")
    return nominal + best/e['fps'], dict(method='paired cache last/first frame grayscale MSE, central image excluding bars',
                                        correction_frames=best, scores=scores,
                                        cache_from=str(cache[x['id']]),cache_to=str(cache[y['id']]))


def frame_rgb(path, time):
    data = run(['ffmpeg', '-v', 'error', '-threads', '1', '-ss', str(time), '-i', str(path),
                '-frames:v', '1', '-vf', 'scale=256:144', '-threads', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'])
    if len(data) != 256 * 144 * 3:
        raise ValueError(f'Cannot decode frame at {time}: {path}')
    try:
        from continuity_report import stats
        import numpy as np
        return stats(np.frombuffer(data, np.uint8).reshape(144, 256, 3))['rgb_mean']
    except ImportError:
        return [sum(data[c::3]) / (256 * 144) for c in range(3)]


def metrics(e, c, tmp, tag):
    t = c['master_cut_seconds']
    times = [t - 1 / e['fps'], t]
    means = [frame_rgb(e['master'], x) for x in times]
    lufs = []
    for i, (start, length) in enumerate(c['audio_windows']):
        wav = tmp / f'{tag}_{i}.wav'
        ff('-ss', start, '-i', e['master'], '-t', length, '-vn', '-c:a', 'pcm_s16le', wav)
        try:
            from continuity_report import loudness
            value = loudness(wav)
        except ImportError:
            p = subprocess.run(['ffmpeg', '-hide_banner', '-i', str(wav), '-af', 'ebur128', '-f', 'null', '-'], capture_output=True, text=True, check=True)
            values = re.findall(r'I:\s*(-?[\d.]+) LUFS', p.stderr)
            value = float(values[-1]) if values else None
        # ebur128's -70 floor is silence/unmeasurable, not a meaningful LU gap.
        lufs.append(value if value is not None and value > -70 else None)
    return dict(lufs=lufs, loudness_difference_lu=abs(lufs[0]-lufs[1]) if None not in lufs else None,
                rgb_means=means, colour_distance_rgb=math.dist(*means), frame_times=times)


def label(tmp, font, text, x, y, size=28):
    p = tmp / f'label_{len(list(tmp.glob("label_*")))}.txt'
    p.write_text(text, encoding='utf-8')
    return f"drawtext=fontfile='{font}':textfile='{p}':expansion=none:fontcolor=white:fontsize={size}:x={x}:y={y}"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--film', required=True)
    ap.add_argument('--a', default='final')
    ap.add_argument('--b', default='final_v2')
    ap.add_argument('--n', type=int, default=10)
    ap.add_argument('--pad', type=float, default=2.)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--slam', default='', help='comma-separated shot ids whose v1 take pushed in; their outgoing cut is shown')
    args = ap.parse_args()
    if args.n < 1 or not math.isfinite(args.pad) or args.pad < .4:
        ap.error('--n must be positive and --pad must be finite and >= 0.4 seconds')
    film = FilmConfig(args.film)
    a, b = edit(film, safe_name(args.a)), edit(film, safe_name(args.b))
    qa = ROOT / 'renders/qa'
    bp = qa / f'continuity_{args.film}_v1.json'
    if not bp.exists():
        bp = qa / f'continuity_{args.film}.json'
    base = read(bp)
    rp = qa / f'{args.film}_reframe_plan.json'
    reframes = {s['id']: s for s in read(rp)} if rp.exists() else {}
    sizes = {s['id']: s.get('shot_size', '?') for s in base['shots']}
    cuts = choose(base, reframes, a, b, args.n, [x for x in args.slam.split(',') if x])
    if not cuts:
        raise ValueError('No common adjacent cuts found')
    source_sizes = {}
    for e in (a, b):
        p = film.videos / f"{e['name']}_sources.json"
        source_sizes[e['name']] = {s['id']: s.get('shot_size', '?') for s in read(p)['shots']} if p.exists() else {}
    for c in cuts:
        for tag, e in [('v1', a), ('v2', b)]:
            lookup = {s['id']: s for s in e['shots']}
            x, y = lookup[c['from']], lookup[c['to']]
            if abs(x['start'] + x['length'] - y['start']) > .01:
                raise ValueError('Selected cut has a timeline gap or overlap')
            nominal = round(y['start'] * e['fps']) / e['fps'] + e['mapping']['offset_seconds']
            t, alignment = align_cut(film, e, x, y, nominal)
            if t - args.pad < 0 or t + args.pad > e['mapping']['body_duration'] + e['mapping']['offset_seconds']:
                raise ValueError(f'{y["id"]}: --pad extends outside the film body')
            ss = source_sizes[e['name']]
            # Never infer completed re-render installation from a future reframe plan.
            sz = [ss.get(s['id'], s.get('shot_size', sizes.get(s['id'], '?'))) for s in (x, y)]
            if e['name'] != 'final' and reframes and not ss:
                sz = [s.get('shot_size', '?') for s in (x, y)]
            c[tag] = dict(edit_cut_seconds=y['start'], master_cut_seconds=t, window_start=t-args.pad,
                          sizes=sz, alignment=alignment, audio_windows=[[t-min(args.pad,x['length']), min(args.pad,x['length'])], [t,min(args.pad,y['length'])]])
        scene = next(s['scene'] for s in a['shots'] if s['id'] == c['from'])
        size_text = lambda i: c['v1']['sizes'][i] if c['v1']['sizes'][i] == c['v2']['sizes'][i] else c['v1']['sizes'][i]+'→'+c['v2']['sizes'][i]
        c['caption'] = f"{scene} · {c['from']} {size_text(0)} → {c['to']} {size_text(1)}"
    same = args.a == args.b
    report = dict(film=args.film, same_edit_control=same, baseline=str(bp), pad=args.pad,
                  selection='Reframed same-scene jumps >2 steps descending, then alternating loudness/RGB ranks; output in film order.',
                  metric_note='Scored master audio over up to pad seconds each side; RGB Euclidean distance of full-frame means including letterbox/subtitles. Sizes are metadata, ? means unavailable. Silence LU differences are null.',
                  edits={k:{key:value for key,value in e.items() if key != 'shots'} for k,e in [('v1',a),('v2',b)]}, cuts=cuts)
    if args.dry_run:
        print(json.dumps(report, ensure_ascii=False, indent=2)); return
    fonts = run(['fc-list', ':lang=zh', 'file', '--format=%{file}\n']).decode().splitlines()
    if not fonts:
        raise ValueError('No CJK font found by fc-list')
    dest = film.videos / 'transition_compare.mp4'
    jpg = qa / f'{args.film}_transition_compare.jpg'
    jp = qa / f'{args.film}_transition_compare.json'
    # Never replace even an earlier comparison without explicit removal by caller.
    for p in (dest, jpg, jp):
        if p.exists():
            raise ValueError(f'Output already exists; refusing to overwrite: {p}')
    enc = ['-c:v','libx264','-preset','veryfast','-crf','20','-pix_fmt','yuv420p','-threads','2','-c:a','aac','-ar','48000','-ac','2']
    with tempfile.TemporaryDirectory(prefix='transition_compare_') as td:
        tmp = Path(td)
        font = tmp / 'font.ttc'
        font.symlink_to(fonts[0])
        segments, rows = [], []
        for i,c in enumerate(cuts):
            print(f"Cut {i+1}/{len(cuts)}: {c['caption']}", flush=True)
            for tag,e in [('v1',a),('v2',b)]:
                c[tag]['metrics'] = metrics(e,c[tag],tmp,f'{i}_{tag}')
            caption = c['caption']
            note = '同版校验 / SAME EDIT CONTROL' if same else '景别为分镜标注 / Sizes are editorial metadata'
            for audio in (0,1):
                part = tmp / f'pair_{i}_{audio}.mp4'
                inputs = []
                for tag,e in [('v1',a),('v2',b)]:
                    inputs += ['-ss',str(c[tag]['window_start']),'-i',e['master']]
                vf = ';'.join(f'[{j}:v]setpts=PTS-STARTPTS,fps=24,scale=960:540:force_original_aspect_ratio=decrease,pad=960:540:(ow-iw)/2:(oh-ih)/2,setsar=1[v{j}]' for j in (0,1))
                vf += ';[v0][v1]hstack,pad=1920:1080:0:230,' + ','.join([
                    label(tmp,font,'v1 修改前 / before',30,140),label(tmp,font,'v2 修改后 / after',990,140),
                    label(tmp,font,caption,30,830,30),label(tmp,font,'剪切对比 / Cut comparison',30,890),
                    label(tmp,font,f'正在播放 v{audio+1} 音轨 / Listening to v{audio+1} audio',30,940),label(tmp,font,note,30,50)])+'[v]'
                vf += f';[{audio}:a]asetpts=PTS-STARTPTS,apad[a]'
                ff(*inputs,'-filter_complex',vf,'-map','[v]','-map','[a]','-t',2*args.pad,*enc,part)
                segments.append(part)
            if i < len(cuts)-1:
                black=tmp / f'black_{i}.mp4'
                ff('-f','lavfi','-i','color=black:s=1920x1080:r=24:d=0.5','-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-t','0.5',*enc,black)
                segments.append(black)
            cells=[]
            for tag,e in [('v1',a),('v2',b)]:
                for j,t in enumerate(c[tag]['metrics']['frame_times']):
                    p=tmp / f'cell_{i}_{tag}_{j}.png'
                    ff('-ss',t,'-i',e['master'],'-frames:v','1','-vf','scale=480:270:force_original_aspect_ratio=decrease,pad=480:270:(ow-iw)/2:(oh-ih)/2',p)
                    cells.append(p)
            row=tmp / f'row_{i}.png'
            vf='[0:v][1:v][2:v][3:v]hstack=inputs=4,pad=1920:370:0:90,'+','.join([
                label(tmp,font,caption,12,8,25),label(tmp,font,'v1 修改前 / before · X 最后一帧 / last | Y 第一帧 / first',12,49,21),
                label(tmp,font,'v2 修改后 / after · X 最后一帧 / last | Y 第一帧 / first',972,49,21)])
            ff(*[z for p in cells for z in ('-i',str(p))],'-filter_complex',vf,'-frames:v','1',row)
            rows.append(row)
        manifest=tmp/'concat.txt'
        manifest.write_text(''.join(f"file '{p}'\n" for p in segments))
        movie=tmp/'result.mp4'
        ff('-f','concat','-safe','0','-i',manifest,'-c','copy','-movflags','+faststart',movie)
        sheet=tmp/'result.jpg'
        vf=f'vstack=inputs={len(rows)}' if len(rows)>1 else 'null'
        ff(*[z for p in rows for z in ('-i',str(p))],'-filter_complex',vf,'-frames:v','1','-q:v','2',sheet)
        # Validate before publishing the three new artifacts.
        ff('-xerror','-i',movie,'-f','null','-')
        ff('-xerror','-i',sheet,'-f','null','-')
        report['output_probe']=probe(movie)
        report['decode_check']='ffmpeg full video/audio and JPEG decode passed'
        import shutil
        shutil.copyfile(movie,dest); shutil.copyfile(sheet,jpg)
        jp.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'{dest}\n{jpg}\n{jp}')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, FileNotFoundError, subprocess.CalledProcessError) as exc:
        sys.exit(f'transition_compare: {exc}')
