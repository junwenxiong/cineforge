"""Flag unbridged size jumps in edit order; scene boundaries are exempt."""
import argparse
import json
import re
from pathlib import Path
from film_config import FilmConfig

SIZES={'ECU':0,'CU':1,'MCU':2,'MS':3,'MWS':4,'FS':4,'WS':5,'EWS':6}

def shot_rank(shot):
    size = shot.get('shot_size')
    if size in SIZES:
        return SIZES[size]
    prompt = (shot.get('ltx_prompt') or shot.get('prompt', '')).split('[Shot 1]')[-1]
    if size == 'OTS' and re.search(r'over-the-shoulder medium shot', prompt, re.I):
        return SIZES['MS']
    if size == 'INSERT':
        if re.search(r'insert medium close-up', prompt, re.I):
            return SIZES['MCU']
        if re.search(r'insert medium shot', prompt, re.I):
            return SIZES['MS']
        if re.search(r'insert close-up|low-angle insert at floor level', prompt, re.I):
            return SIZES['CU']
    return None

def check(shots):
    warnings=[]
    for a,b in zip(shots,shots[1:]):
        if a['scene']!=b['scene']: continue
        x,y=a.get('shot_size'),b.get('shot_size')
        ax, by = shot_rank(a), shot_rank(b)
        if ax is None or by is None:
            warnings.append(dict(previous=a['id'],shot=b['id'],reason='unknown shot_size',sizes=[x,y])); continue
        if abs(ax-by)>2:
            warnings.append(dict(previous=a['id'],shot=b['id'],sizes=[x,y],steps=abs(ax-by),suggestion='Insert a bridging MS/OTS'))
    return warnings

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--film',required=True); ap.add_argument('--shots-dir',type=Path); args=ap.parse_args()
    film=FilmConfig(args.film); cuts=json.loads(film.cuts.read_text()) if film.cuts.exists() else {}
    shots = ([s for scene in film.order for s in json.loads((args.shots_dir / (scene+'.json')).read_text())]
             if args.shots_dir else film.load_shots())
    print(json.dumps(check([s for s in shots if not cuts.get(s['id'],{}).get('drop')]),ensure_ascii=False,indent=2))

if __name__=='__main__': main()
