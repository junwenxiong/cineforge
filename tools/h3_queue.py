"""调用 Box 自带的本地画布协议。凭据只在进程内存中；一次一个任务。"""
import argparse, hashlib, json, os, re, sys, time, uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
import requests
from urllib3.util.retry import Retry
from PIL import Image
import imageio_ffmpeg, subprocess
ROOT=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:41520'
R=ROOT/'renders'
R.mkdir(exist_ok=True)
def write(p,value):
    tmp=p.with_suffix('.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    tmp.replace(p)
def open_canvas():
    entry=os.environ.get('DRAMAPIE_ENTRY','').strip()
    key=os.environ.get('DRAMAPIE_API_KEY','').strip()
    if not key and entry.startswith('sk-'):
        key, entry = entry, ''
    s=requests.Session();s.trust_env=False
    # Box 轮询偶尔返回网关错误，沿用原任务号重读状态，不重复提交生成。
    retry = Retry(total=4, backoff_factor=2, status_forcelist=(429, 502, 503, 504),
                  allowed_methods=frozenset({"GET", "HEAD"}))
    s.mount(BASE, requests.adapters.HTTPAdapter(max_retries=retry))
    if key:
        s.headers['Authorization']='Bearer '+key
    else:
        if not re.fullmatch(re.escape(BASE)+r'/c/[\w-]+/',entry):
            raise ValueError('请从本机 Box 复制画布入口链接或画布 Key，经 DRAMAPIE_ENTRY / DRAMAPIE_API_KEY 传入。')
        s.get(entry,timeout=10,allow_redirects=False).raise_for_status()
        auth=s.get(BASE+'/api/sso',timeout=10).json()
        if not auth.get('loggedIn'): raise RuntimeError('本机画布尚未登录')
        s.headers['Authorization']='Bearer '+auth['apiKey']
    models=s.get(BASE+'/v1/models',timeout=10).json()['data']
    assert 'minimax-h3' in [model['id'] for model in models]
    return s
def valid(p):
    return p.is_file() and subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-xerror','-i',str(p),'-f','null','-'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0
def run(s,shot,deadline):
    slug=shot['id']
    if not re.fullmatch(r'[a-zA-Z0-9_-]+',slug): raise ValueError(slug)
    folder=R/slug;folder.mkdir(exist_ok=True)
    path=folder/'job.json'; out=folder/'raw.mp4'
    state=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if state.get('shot') and state['shot']!=shot: raise ValueError('镜头参数变更请使用新版本 ID')
    if state.get('status')=='completed' and valid(out): return
    if state.get('status')=='failed': return
    if time.time()+120>deadline: raise TimeoutError('剩余预算时间不足，结束队列')
    ref=ROOT/shot['ref']; image_bytes=ref.read_bytes()
    if not state:
        state={'shot':shot,'model':'minimax-h3','request':str(uuid.uuid4()),'start':time.time(),'status':'prepared','reference_sha256':hashlib.sha256(image_bytes).hexdigest()}
        write(path,state)
    if not state.get('remote_id'):
        resolution=shot.get('resolution','480p')
        size={'480p':'854x480','720p':'1280x720','1080p':'1920x1080'}[resolution]
        data=dict(model='minimax-h3',prompt=shot['prompt'],seconds=str(shot.get('seconds',8)),size=size,ratio='16:9',resolution_name=resolution,generate_audio='true',watermark='false',mode='frames')
        files={'first_frame':('first.jpg',image_bytes,'image/jpeg')}
        if shot.get('last'):files['last_frame']=('last.jpg',(ROOT/shot['last']).read_bytes(),'image/jpeg')
        response=s.post(BASE+'/v1/videos',data=data,files=files,headers={'x-request-id':state['request']},timeout=90)
        if response.status_code==409:
            taskid=response.json().get('error',{}).get('task_id')
            if not taskid:response.raise_for_status()
        else:
            response.raise_for_status();obj=response.json();taskid=obj.get('data',obj)['id']
        state.update(remote_id=taskid,status='submitted');write(path,state);print('submitted',slug,flush=True)
    url=BASE+'/v1/videos/'+state['remote_id']
    while time.time()<deadline:
        res=s.get(url,timeout=30);res.raise_for_status();d=res.json();d=d.get('data',d)
        if d.get('status') in ('failed','cancelled'):
            state.update(status='failed',error=str(d.get('error',{}).get('code') or 'backend_error'),elapsed=round(time.time()-state['start'],1));write(path,state);print(slug,'failed',state['error'],flush=True);return
        if d.get('status')=='completed' or d.get('video_url'):
            res=s.get(url+'/content',timeout=120,allow_redirects=False)
            if res.is_redirect:
                location=res.headers['Location']
                # 下载签名成片链接时不向文件服务器转发本机画布的鉴权头
                if urlsplit(location).scheme!='https':raise ValueError('不支持的下载重定向')
                res=requests.get(location,timeout=120)
            res.raise_for_status(); tmp=folder/'download.mp4';tmp.write_bytes(res.content)
            if not valid(tmp):raise ValueError('成片解码失败')
            tmp.replace(out);state.update(status='completed',elapsed=round(time.time()-state['start'],1),bytes=out.stat().st_size,sha256=hashlib.sha256(out.read_bytes()).hexdigest())
            write(path,state);print('saved',slug,state['elapsed'],flush=True);return
        time.sleep(3)
    raise TimeoutError('到了本轮预算截止时间，保留任务编号')
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('queue');parser.add_argument('--budget',default='films/budget.json');parser.add_argument('--shots',nargs='+');args=parser.parse_args()
    budget=json.loads((ROOT/args.budget).read_text(encoding='utf-8'))
    if budget['deadline_epoch']<=time.time():sys.exit('本轮预算过期；重新核对余额和计费速率')
    session=open_canvas()
    from contextlib import ExitStack
    import msvcrt
    with (R/'queue.lock').open('a+b') as lock:
        lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        items=json.loads((ROOT/args.queue).read_text(encoding='utf-8'))
        if args.shots:
            missing=set(args.shots)-{item['id'] for item in items}
            if missing:parser.error('未知镜号 '+', '.join(sorted(missing)))
            items=[item for item in items if item['id'] in args.shots]
        for item in items:
            for attempt in range(3):
                try:run(session,item,budget['deadline_epoch']);break
                except (requests.ConnectionError,requests.Timeout):
                    if attempt==2:raise
                    time.sleep(5)
