"""Measure edit continuity without models. Scale estimates are candidates, not face detection."""
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json
import re
import subprocess
import numpy as np
from PIL import Image, ImageDraw
from film_config import FilmConfig, ROOT


def duration(path):
    return float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',str(path)]))


def frame(path, time):
    data = subprocess.check_output(['ffmpeg','-v','error','-threads','1','-ss',str(max(0,time)),'-i',str(path),'-frames:v','1','-vf','scale=256:144','-threads','1','-f','rawvideo','-pix_fmt','rgb24','-'])
    return np.frombuffer(data,np.uint8).reshape(144,256,3).copy()


def stats(a):
    return dict(rgb_mean=a.mean((0,1)).tolist(),rgb_std=a.std((0,1)).tolist(),luma=float((a @ np.array([.2126,.7152,.0722])).mean()))


def loudness(path):
    p = subprocess.run(['ffmpeg','-hide_banner','-threads','1','-i',str(path),'-vn','-af','ebur128','-f','null','-'],capture_output=True,text=True,check=True)
    values = re.findall(r'I:\s*(-?[\d.]+) LUFS',p.stderr)
    return float(values[-1]) if values else None


def scale_estimate(first,last):
    # Normalised centred crop correlation; subject motion/occlusion may invalidate this proxy.
    b=last.astype(float); b=(b-b.mean((0,1)))/(b.std((0,1))+1)
    scores=[]
    for scale in np.linspace(1,2,41):
        h,w=first.shape[:2]; ch,cw=round(h/scale),round(w/scale)
        a=np.asarray(Image.fromarray(first[(h-ch)//2:(h-ch)//2+ch,(w-cw)//2:(w-cw)//2+cw]).resize((w,h),Image.Resampling.BILINEAR)).astype(float)
        a=(a-a.mean((0,1)))/(a.std((0,1))+1)
        scores.append(float(np.mean(a*b)))
    i=int(np.argmax(scores))
    return dict(scale=round(1+i*.025,3),correlation=round(scores[i],3),improvement=round(scores[i]-scores[0],3),reliable=scores[i]>.65 and scores[i]-scores[0]>.04,method='centred_crop_normalised_correlation')


def measure(item):
    shot,cut=item; sid=shot['id']; path=Path(shot.get('_source', ROOT/'renders'/sid/'raw.mp4'))
    signature=[path.stat().st_size,path.stat().st_mtime_ns]
    dur=duration(path); start=float(cut.get('in',.25)); end=min(float(cut.get('out',shot['seconds']*.92)),dur)
    a,b=frame(path,start),frame(path,max(start,end-1/24))
    if shot.get('_source'): a,b=a[19:125],b[19:125]  # exclude baked letterbox from image statistics/scale search
    engine=shot.get('engine','h3')
    receipt=ROOT/'renders'/sid/'job.json'
    if not shot.get('_source') and receipt.exists():
        job=json.loads(receipt.read_text()); via=job.get('via','')+' '+job.get('model','')
        if 'ltx' in via.lower(): engine='ltx'
        elif 'h3' in via.lower() or 'colab-farm' in via: engine='h3'
    out=dict(id=sid,scene=shot['scene'],engine=engine,shot_size=shot.get('shot_size'),dialogue=bool(shot.get('dialogue')),source=str(path),signature=signature,in_point=start,out_point=end,duration=dur,lufs=loudness(path),first=stats(a),last=stats(b))
    if engine=='ltx': out['push_in']=scale_estimate(a,b)
    if signature != [path.stat().st_size,path.stat().st_mtime_ns]: raise RuntimeError(f'Source changed during measurement: {sid}')
    return out,a,b


SIZES={'ECU':0,'CU':1,'MCU':2,'MS':3,'MWS':4,'FS':4,'WS':5,'EWS':6}


def sheet(pairs,frames,dest):
    canvas=Image.new('RGB',(1024,318*len(pairs)), '#202020'); d=ImageDraw.Draw(canvas)
    for i,p in enumerate(pairs):
        a,b=p['from'],p['to']; y=i*318
        canvas.paste(Image.fromarray(frames[a][1]).resize((512,288)),(0,y+30))
        canvas.paste(Image.fromarray(frames[b][0]).resize((512,288)),(512,y+30))
        d.text((8,y+8),f"{a} -> {b} | size {p['size_jump']} | LU {p['loudness_jump']:.1f} | RGB {p['rgb_jump']:.1f}",fill='white')
    if pairs: canvas.save(dest)


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--film',required=True); ap.add_argument('--workers',type=int,default=4); ap.add_argument('--edit-cache', help='Measure immutable segments from this existing edit, not mutable raw takes'); args=ap.parse_args()
    film=FilmConfig(args.film); cuts=json.loads(film.cuts.read_text()) if film.cuts.exists() else {}
    shots=[s for s in film.load_shots() if not cuts.get(s['id'],{}).get('drop')]
    missing=[s['id'] for s in shots if not (ROOT/'renders'/s['id']/'raw.mp4').exists()]
    if missing and not args.edit_cache: raise SystemExit(f'Raw shots not stable/complete: {missing}')
    # Follow final edit order where available, including explicit omissions.
    timeline=film.videos/f'{args.edit_cache or "final"}.json'
    if timeline.exists():
        lookup={s['id']:s for s in shots}; tl=json.loads(timeline.read_text())['shots']; shots=[lookup[s['id']] for s in tl]
        cuts={s['id']:{'in':s['in'],'out':s['out']} for s in tl}
    if args.edit_cache:
        import shlex
        plan=ROOT/f'renders/qa/{args.film}_reframe_plan.json'
        originals={s['id']:s for s in json.loads(plan.read_text())} if plan.exists() else {}
        for shot in shots:
            if shot['id'] in originals:
                original=originals[shot['id']]
                shot['shot_size']=original['old_size']; shot['engine']=original['old_engine']
        paths=[shlex.split(line)[1] for line in (film.cache/f'{args.edit_cache}.txt').read_text().splitlines() if line.startswith('file ')]
        if len(paths)!=len(shots): raise ValueError('Edit cache and timeline count differ')
        for shot,path in zip(shots,paths):
            if not Path(path).name.startswith(shot['id']+'_'): raise ValueError('Edit cache order mismatch')
            shot['_source']=path
            cuts[shot['id']]={'in':0,'out':duration(path)-1/24}
    qa=ROOT/'renders/qa'; qa.mkdir(exist_ok=True,parents=True)
    with ThreadPoolExecutor(args.workers) as pool: results=list(pool.map(measure,[(s,cuts.get(s['id'],{})) for s in shots]))
    measured=[r[0] for r in results]; frames={r[0]['id']:(r[1],r[2]) for r in results}; pairs=[]
    for a,b in zip(measured,measured[1:]):
        jump=abs(SIZES[a['shot_size']]-SIZES[b['shot_size']]) if a['shot_size'] in SIZES and b['shot_size'] in SIZES else None
        lu=abs(a['lufs']-b['lufs']); rgb=float(np.linalg.norm(np.array(a['last']['rgb_mean'])-b['first']['rgb_mean']))
        pairs.append(dict(**{'from':a['id'],'to':b['id']},scene_boundary=a['scene']!=b['scene'],engine_change=a['engine']!=b['engine'],size_jump=jump,loudness_jump=lu,rgb_jump=rgb,luma_jump=abs(a['last']['luma']-b['first']['luma']),score=(jump or 0)*2+min(lu,20)+rgb/15))
    candidates=[dict(id=s['id'],**s['push_in'],reason='Strong scale candidate; speech prevents automatic shortening' if s['dialogue'] else 'Review motion/occlusion before re-render') for s in measured if s.get('push_in',{}).get('scale',1)>1.3]
    summary=dict(shots=len(shots),cuts=len(pairs),engine_changes=sum(p['engine_change'] for p in pairs),size_jumps_over_two=sum((p['size_jump'] or 0)>2 and not p['scene_boundary'] for p in pairs),loudness_jumps_over_6=sum(p['loudness_jump']>6 for p in pairs),mean_rgb_jump=float(np.mean([p['rgb_jump'] for p in pairs])),strong_scale_candidates=len(candidates),reliable_strong_scale=sum(s.get('push_in',{}).get('reliable',False) and s['push_in']['scale']>1.3 for s in measured))
    (qa/f'continuity_{args.film}.json').write_text(json.dumps(dict(summary=summary,shots=measured,pairs=pairs),indent=2))
    rerender_path=qa/f'rerender_static_{args.film}.json'
    prior=json.loads(rerender_path.read_text()) if rerender_path.exists() else {}
    manual=prior.get('manually_confirmed_ids',[])
    protected={s['id'] for s in measured if s['dialogue'] and s.get('push_in',{}).get('reliable')}
    confirmed=[s for s in candidates if s['id'] in manual or s['id'] in protected]
    rerender_path.write_text(json.dumps(dict(note='Re-render candidates protect dialogue. Uncertain scale candidates are separate; subject motion can confound this estimator.',manually_confirmed_ids=manual,shots=confirmed,uncertain_scale_candidates=[s for s in candidates if s not in confirmed]),indent=2))
    sheet(sorted(pairs,key=lambda p:p['score'],reverse=True)[:30],frames,qa/f'continuity_{args.film}.jpg')
    print(json.dumps(summary))

if __name__=='__main__': main()
