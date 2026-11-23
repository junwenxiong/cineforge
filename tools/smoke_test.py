"""Offline checks; temporary film state and a loopback-only random-port farm."""
import json
import os
from pathlib import Path
import py_compile
import secrets
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from new_film import create
from validate_film import FilmConfig, ROOT, validate


SETUP_FILES=['tools/setup.py','.env.example','.gitignore','requirements.txt','AGENTS.md','CLAUDE.md','GEMINI.md']


def check_setup():
    """init/doctor/run in a temp copy: never reads the real .env, no network, token never printed."""
    with tempfile.TemporaryDirectory(prefix='cineforge-setup-') as directory:
        root=Path(directory)
        for rel in SETUP_FILES:
            (root/rel).parent.mkdir(parents=True,exist_ok=True); shutil.copy2(ROOT/rel,root/rel)
        shutil.copytree(ROOT/'skills',root/'skills')  # no .claude/.agents: init must restore them
        env={k:v for k,v in os.environ.items() if k!='HF_TOKEN'}
        env['PYTHONDONTWRITEBYTECODE']='1'
        git=shutil.which('git')
        if git: subprocess.run([git,'init','-q'],cwd=root,env=env,check=True,capture_output=True)
        def setup(*args,stdin=''):
            out=subprocess.run([sys.executable,str(root/'tools/setup.py'),*args],cwd=root,env=env,input=stdin,
                               capture_output=True,text=True,timeout=300)
            assert fake not in out.stdout+out.stderr, 'token printed'
            return out
        fake='hf_'+secrets.token_hex(16)
        out=setup('init','--offline','--hf-token-stdin',stdin=fake+'\n')
        assert out.returncode==0, out.stdout+out.stderr
        assert f'HF_TOKEN={fake}' in (root/'.env').read_text().splitlines()
        if os.name!='nt': assert stat.S_IMODE((root/'.env').stat().st_mode)==0o600
        for stub in ['.claude/skills/cineforge/SKILL.md','.agents/skills/cineforge/SKILL.md']:
            assert 'skills/cineforge/SKILL.md' in (root/stub).read_text(), stub
        def doctor():
            out=setup('doctor','--offline','--json')
            report=json.loads(out.stdout)
            checks={c['name']:c['status'] for c in report['checks']}
            assert out.returncode==(1 if 'FAIL' in checks.values() else 0), out.stdout
            assert report['ok']==(out.returncode==0)
            return checks
        checks=doctor()
        assert checks['env-file']=='PASS' and checks['hf-token']=='PASS', checks
        assert checks['hf-login']=='SKIP' and checks['ltx-access']=='SKIP', checks
        assert checks['skills']=='PASS' and checks['instructions']=='PASS', checks
        if git: assert checks['env-ignored']=='PASS', checks
        out=setup('run','--',sys.executable,'-c','import os; print(len(os.environ["HF_TOKEN"]))')
        assert out.returncode==0 and out.stdout.strip()==str(len(fake)), out.stderr
        (root/'.env').write_text('HF_TOKEN=\n')
        assert doctor()['hf-token']=='FAIL'
    print('PASS setup init/doctor --offline --json/run in a temp copy; token stored, never printed')


def main():
    with tempfile.TemporaryDirectory(prefix='cineforge-smoke-') as directory:
        root=Path(directory)
        for index,p in enumerate(sorted(ROOT.rglob('*.py'))):
            if '.venv' in p.parts: continue
            py_compile.compile(str(p),cfile=str(root / f'{index}.pyc'),doraise=True)
        print('PASS py_compile: every repository Python file')
        shutil.copytree(ROOT/'examples',root/'examples')
        for name in ['starcore','catfilm','echo']:
            create(name,name,root)
            result=validate(FilmConfig(name,root))
            assert not result['errors'], result
            assert result['shots'] > 0, result
            print('PASS example:',json.dumps(result))
        create('newstory',root=root)
        assert FilmConfig('newstory',root).prefix == 'newstory'
        try: create('starcore','starcore',root)
        except ValueError: pass
        else: raise AssertionError('Existing film overwritten')
        try: create('../escape',root=root)
        except ValueError: pass
        else: raise AssertionError('Unsafe name accepted')
        assert validate(FilmConfig('starcore',root),True)['errors']
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
        token=secrets.token_urlsafe(32)
        env=dict(os.environ,CINEFORGE_SMOKE_TOKEN=token,PYTHONDONTWRITEBYTECODE='1')
        proc=subprocess.Popen([sys.executable,str(ROOT/'tools/film/farm_server.py'),'--root',str(root),
                              '--port',str(port),'--token-env','CINEFORGE_SMOKE_TOKEN'],env=env,
                              stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        base=f'http://127.0.0.1:{port}'
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            for _ in range(100):
                if proc.poll() is not None:
                    raise AssertionError(proc.communicate()[1].decode())
                try:
                    with opener.open(base+'/status?t='+token,timeout=.5) as response:
                        assert json.load(response)=={}
                    break
                except (urllib.error.URLError,TimeoutError): time.sleep(.05)
            else: raise AssertionError('Server did not become ready')
            for suffix in ['/status','/status?t=wrong']:
                try: opener.open(base+suffix,timeout=1)
                except urllib.error.HTTPError as exc: assert exc.code==403
                else: raise AssertionError('Unauthenticated request accepted')
            assert not (root/'renders/farm/token').exists()
            print('PASS farm /status authenticated=200; absent/wrong token=403; no token file')
        finally:
            proc.terminate()
            try: proc.communicate(timeout=5)
            except subprocess.TimeoutExpired: proc.kill(); proc.communicate(timeout=5)
        print('PASS owned farm process stopped; temporary state removed')
    check_setup()
    print('PASS offline smoke test (no GPU or external network)')


if __name__=='__main__': main()
