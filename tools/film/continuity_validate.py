"""Decode, loudness, timeline/subtitle checks and ten before/after cut pairs."""
import argparse
import json
import re
import numpy as np
import shlex
import subprocess
from PIL import Image, ImageDraw
from pathlib import Path
from film_config import FilmConfig, ROOT
from continuity_report import frame, duration, loudness


def seconds(value):
    h,m,s=value.split(':'); return int(h)*3600+int(m)*60+float(s)


def pair_sheet(f,name,tl,old):
    report=json.loads((ROOT/f'renders/qa/continuity_{f.name}.json').read_text()); cuts=sorted(report['pairs'],key=lambda p:p['score'],reverse=True)[:10]
    canvas=Image.new('RGB',(1024,608*len(cuts))); draw=ImageDraw.Draw(canvas)
    lookups=[{s['id']:s for s in x['shots']} for x in [old,tl]]
    for i,cut in enumerate(cuts):
        for row,(name,lookup) in enumerate(zip(['final',name],lookups)):
            target=lookup[cut['to']]['start']
            validation_path=f.videos/f'{name}_validation.json'
            offset=json.loads(validation_path.read_text()).get('end_dialogue_video_offset_frames',0) if validation_path.exists() else 0
            target += offset/24
            path=f.videos/f'{name}_master.mp4'; y=i*608+row*304
            draw.text((5,y),f"{name}: {cut['from']} -> {cut['to']}",fill='white')
            for col,t in enumerate([target-1/24,target]): canvas.paste(Image.fromarray(frame(path,t)).resize((512,288)),(col*512,y+16))
    canvas.save(ROOT/f'renders/qa/transitions_before_after_{f.name}.jpg')


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--film',required=True); ap.add_argument('--name',default='final_v2'); args=ap.parse_args()
    f=FilmConfig(args.film); source=f.videos/f'{args.name}_master.mp4'; body=f.videos/f'{args.name}.mp4'
    tl=json.loads((f.videos/f'{args.name}.json').read_text()); old=json.loads((f.videos/'final.json').read_text())
    check=subprocess.run(['ffmpeg','-v','error','-i',str(source),'-f','null','-'],capture_output=True,text=True)
    streams=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(body)]))['streams']
    video=next(s for s in streams if s['codec_type']=='video'); audio=next(s for s in streams if s['codec_type']=='audio')
    vd=float(video['duration']); ad=float(audio['duration'])
    events=[]
    for line in (f.videos/f'{args.name}.ass').read_text().splitlines():
        if line.startswith('Dialogue:'):
            fields=line.split(',',9)
            if fields[3] in ('Dlg','VO'): events.append((seconds(fields[1]),seconds(fields[2])))
    expected=sum(len([d for d in s.get('dialogue',[]) if d.get('text')]) for s in tl['shots'])
    violations=[e for e in events if not any(s.get('dialogue') and e[0]>=s['start']-.02 and e[1]<=s['start']+s['length']+.02 for s in tl['shots'])]
    # Duration/PTS checks detect cumulative timing errors; pixel alignment still needs visual review.
    gaps=[abs(b['start']-(a['start']+a['length'])) for a,b in zip(tl['shots'],tl['shots'][1:])]
    result=dict(shots=len(tl['shots']),full_decode_returncode=check.returncode,full_decode_errors=check.stderr,duration_seconds=duration(source),body_video_seconds=vd,body_audio_seconds=ad,body_vs_timeline_seconds=vd-tl['duration'],av_duration_delta_seconds=ad-vd,integrated_lufs=loudness(source),dialogue_subtitles=len(events),expected_subtitles=expected,subtitle_outside_shot=violations,max_timeline_gap=max(gaps,default=0),visual_alignment='Review pair sheet; no claim of measured lip-sync')
    meter=subprocess.run(['ffmpeg','-hide_banner','-i',str(source),'-vn','-af','ebur128=peak=true','-f','null','-'],capture_output=True,text=True,check=True)
    (f.videos/f'{args.name}_loudness.log').write_text(meter.stderr)
    peaks=re.findall(r'Peak:\s*(-?[\d.]+) dBFS',meter.stderr)
    result['master_vs_expected_seconds']=result['duration_seconds']-(vd+f.credits_seconds)
    result['true_peak_dbfs']=float(peaks[-1]) if peaks else None
    last=next(s for s in reversed(tl['shots']) if s.get('dialogue'))
    segments=[Path(shlex.split(line)[1]) for line in (f.cache/f'{args.name}.txt').read_text().splitlines() if line.startswith('file ')]
    ref=frame(segments[tl['shots'].index(last)],.5)[25:118].astype(float)
    alignment=[]
    for offset in range(-3,4):
        sample=frame(source,last['start']+.5+offset/24)[25:118].astype(float)
        alignment.append(dict(offset_frames=offset,mae=float(np.abs(ref-sample).mean())))
    best=min(alignment,key=lambda x:x['mae'])
    result['last_dialogue_frame_comparison']=alignment
    result['end_dialogue_video_offset_frames']=best['offset_frames']
    result['visual_alignment']='Pixel comparison to the actual graded segment, excluding subtitle bars; not a lip-sync assessment'
    result['passed']=check.returncode==0 and not check.stderr and abs(vd-tl['duration'])<=1/24 and abs(ad-vd)<.1 and len(events)==expected and not violations and max(gaps,default=0)<.003 and result['true_peak_dbfs'] is not None and result['true_peak_dbfs']<=-1 and -19<=result['integrated_lufs']<=-14 and abs(best['offset_frames'])<=1 and abs(result['master_vs_expected_seconds'])<.1
    (f.videos/f'{args.name}_validation.json').write_text(json.dumps(result,indent=2))
    pair_sheet(f,args.name,tl,old)
    print(json.dumps(result)); raise SystemExit(0 if result['passed'] else 1)

if __name__=='__main__': main()
