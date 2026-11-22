"""Opt-in continuity edit wrapper. Existing rough_cut defaults and files stay untouched.

Run after echo's final_master.mp4 and final_validation.json exist:
 python continuity.py --film catfilm --name final_v2 --normalize --audio-crossfade --color-match --trim-push-in
A report from continuity_report.py is required. Never overwrites the original final.
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
import numpy as np
from film_config import FilmConfig, ROOT


def grade_filter(shot, shots):
    if shot['engine']!='ltx': return ''
    neighbours=[s for s in shots if s['scene']==shot['scene'] and s['engine']=='h3']
    if not neighbours: return ''
    # Nearest H3 on each side; fallback to one side at scene edges.
    i=shots.index(shot); left=[s for s in shots[:i] if s in neighbours]; right=[s for s in shots[i+1:] if s in neighbours]
    refs=left[-1:]+right[:1]
    target=np.mean([s['first']['rgb_mean'] for s in refs],axis=0)
    source=(np.array(shot['first']['rgb_mean'])+shot['last']['rgb_mean'])/2
    target_std=np.mean([s['first']['rgb_std'] for s in refs],axis=0)
    source_std=(np.array(shot['first']['rgb_std'])+shot['last']['rgb_std'])/2
    gain=1+.25*(np.clip(target_std/np.maximum(source_std,1),.8,1.2)-1)
    bias=np.clip(.25*(target-source*gain),-8,8)
    return 'lutrgb='+':'.join(f"{c}='clip(val*{g:.6f}+{b:.6f},0,255)'" for c,g,b in zip('rgb',gain,bias))


def trim_window(shot, cut):
    """Only shorten silent shots with reliable scale evidence; dialogue out-points are sacrosanct."""
    p=shot.get('push_in',{})
    if shot['dialogue'] or not p.get('reliable') or p['scale']<=1.3: return cut
    # Explicit out-points may protect production sound even without scripted dialogue.
    if 'out' in cut: return cut
    fraction=min(1,.3/(p['scale']-1))
    return dict(cut,out=shot['in_point']+(shot['out_point']-shot['in_point'])*fraction)


def audio_mix(timeline, measured, dest, target, crossfade, jl):
    """Mix real source handles around fixed picture cuts; no cumulative A/V shortening."""
    rate=48000; total=round((timeline[-1]['start']+timeline[-1]['length'])*rate)
    scratch=dest.with_suffix('.pcm'); mix=np.memmap(scratch,dtype='float32',mode='w+',shape=(total,2)); mix[:]=0
    weights_path=dest.with_suffix('.weights'); weights=np.memmap(weights_path,dtype='float32',mode='w+',shape=(total,)); weights[:]=0
    for i,s in enumerate(timeline):
        m=measured[s['id']]
        if 'signature' in m:
            path=Path(m['source'])
            if m['signature'] != [path.stat().st_size,path.stat().st_mtime_ns]: raise RuntimeError('Take changed before audio mix: '+s['id'])
        half=5/48 if crossfade else 0
        # Shift only the crossfade centre, not speech or video timestamps.
        centre=(2/24 if jl=='l' else -2/24 if jl=='j' else 0)
        before=half; after=half
        if i and timeline[i-1]['scene']!=s['scene']: before=max(0,half-centre)
        if i+1<len(timeline) and timeline[i+1]['scene']!=s['scene']: after=max(0,half+centre)
        start=round(s['start']*rate); count=round(s['length']*rate)
        pre=min(round(before*rate),round(s['in']*rate),start)
        count=min(count,total-start)
        post=max(0,min(round(after*rate),max(0,round((m['duration']-s['out'])*rate)),total-start-count))
        gain=np.clip(target-m['lufs'],-18,12) if target is not None and m['lufs']>-60 else 0
        raw=subprocess.check_output(['ffmpeg','-v','error','-threads','1','-ss',str(s['in']-pre/rate),'-i',m['source'],'-t',str((pre+count+post)/rate),'-vn','-af',f'volume={gain}dB','-ar',str(rate),'-ac','2','-f','f32le','-'])
        samples=np.frombuffer(raw,np.float32).reshape(-1,2).copy(); needed=pre+count+post
        samples=np.pad(samples,((0,max(0,needed-len(samples))),(0,0)))[:needed]
        # At each boundary the outgoing and incoming ramps have complementary weights.
        fade=round(half*2*rate)
        envelope=np.ones(needed,dtype=np.float32)
        if i and fade:
            n=min(fade,len(samples)); envelope[:n]*=np.linspace(0,1,n)
        if i+1<len(timeline) and fade:
            n=min(fade,len(samples)); envelope[-n:]*=np.linspace(1,0,n)
        mix[start-pre:start-pre+needed]+=samples*envelope[:,None]
        weights[start-pre:start-pre+needed]+=envelope
    for pos in range(0,total,rate*10):
        end=min(total,pos+rate*10)
        mix[pos:end]/=np.maximum(weights[pos:end,None],1e-8)
    mix.flush(); del mix,weights
    weights_path.unlink()
    subprocess.run(['ffmpeg','-v','error','-y','-f','f32le','-ar',str(rate),'-ac','2','-i',str(scratch),'-af','alimiter=limit=0.89:level=false:latency=true','-c:a','pcm_s24le',str(dest)],check=True)
    scratch.unlink()


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('--film',required=True); ap.add_argument('--name',default='final_v2')
    for flag in ('normalize','audio-crossfade','color-match','trim-push-in','scene-dissolve'): ap.add_argument('--'+flag,action='store_true')
    ap.add_argument('--lufs',type=float,default=-18); ap.add_argument('--jl-cut',choices=['j','l']); args=ap.parse_args(argv)
    if args.name in ('final','draft') or not args.name.replace('_','').isalnum(): ap.error('Use a distinct safe output name')
    if not all((ROOT/'videos/echo'/p).is_file() for p in ('final_master.mp4','final_validation.json')): raise SystemExit('Blocked: echo final_master.mp4 AND final_validation.json are required before recuts')
    film=FilmConfig(args.film)
    (film.videos/f'{args.name}_continuity.json').unlink(missing_ok=True)
    # Re-measure every current take; v1 baseline never supplies gains/grades for new takes.
    from continuity_report import measure
    from concurrent.futures import ThreadPoolExecutor
    cuts=json.loads(film.cuts.read_text()) if film.cuts.exists() else {}
    shots=[s for s in film.load_shots() if not cuts.get(s['id'],{}).get('drop')]
    with ThreadPoolExecutor(4) as pool:
        measured=list(pool.map(measure,[(s,cuts.get(s['id'],{})) for s in shots]))
    report={'shots':[m[0] for m in measured]}; measurements={s['id']:s for s in report['shots']}
    film.videos.mkdir(parents=True,exist_ok=True)
    (film.videos/f'{args.name}_sources.json').write_text(json.dumps(report,indent=2))
    import rough_cut as rc
    original=rc.segment; options=vars(args)
    previous=[]
    def segment(shot,cut):
        m=measurements[shot['id']]
        path=Path(m['source'])
        if m['signature'] != [path.stat().st_size,path.stat().st_mtime_ns]: raise RuntimeError('Take changed during cut: '+shot['id'])
        if args.trim_push_in: cut=trim_window(m,cut)
        base,a,b,length=original(shot,cut)
        vf=grade_filter(m,report['shots']) if args.color_match else ''
        key=hashlib.sha256((str(base)+vf).encode()).hexdigest()[:12]; out=film.cache/f"{shot['id']}_continuity_{key}.mp4"
        if vf and not out.exists(): subprocess.run(['ffmpeg','-v','error','-y','-i',str(base),'-vf',vf,*rc.VENC,*rc.COMMON,str(out)],check=True)
        if not vf: out=base
        if args.scene_dissolve and previous:
            prev_path,prev_shot=previous[-1]
            if prev_shot['scene']!=shot['scene'] and not prev_shot.get('dialogue') and not shot.get('dialogue'):
                key=hashlib.sha256((str(prev_path)+str(out)+'dissolve8').encode()).hexdigest()[:12]
                dissolved=film.cache/f"{shot['id']}_dissolve_{key}.mp4"
                if not dissolved.exists():
                    fade=8/rc.FPS
                    graph=f'[0:v]trim=start={max(0,rc.video_dur(prev_path)-fade)},setpts=PTS-STARTPTS,settb=AVTB[p];[1:v]settb=AVTB[v];[p][v]xfade=transition=fade:duration={fade}:offset=0[o]'
                    subprocess.run(['ffmpeg','-v','error','-y','-filter_complex_threads','1','-i',str(prev_path),'-i',str(out),'-filter_complex',graph,'-map','[o]','-map','1:a',*rc.VENC,*rc.COMMON,'-frames:v',str(round(rc.video_dur(out)*rc.FPS)),str(dissolved)],check=True)
                out=dissolved
        previous.append((out,shot))
        return out,a,b,length
    rc.segment=segment
    rc.CONTINUITY_TIMING=True
    sys.argv=['rough_cut.py','--film',args.film,'--name',args.name]; rc.main()
    timeline=json.loads((film.videos/f'{args.name}.json').read_text())
    if args.normalize or args.audio_crossfade or args.jl_cut:
        wav=film.videos/f'{args.name}_production.wav'; audio_mix(timeline['shots'],measurements,wav,args.lufs if args.normalize else None,args.audio_crossfade,args.jl_cut)
        out=film.videos/f'{args.name}.mp4'; temp=out.with_suffix('.mix.mp4')
        subprocess.run(['ffmpeg','-v','error','-y','-i',str(out),'-i',str(wav),'-map','0:v','-map','1:a','-c:v','copy','-c:a','aac','-b:a','192k','-t',str(timeline['duration']),str(temp)],check=True); temp.replace(out)
    for m in measurements.values():
        path=Path(m['source'])
        if m['signature'] != [path.stat().st_size,path.stat().st_mtime_ns]: raise RuntimeError('Take changed during edit: '+m['id'])
    (film.videos/f'{args.name}_continuity.json').write_text(json.dumps(options,indent=2))

if __name__=='__main__': main()
