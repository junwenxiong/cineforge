"""Offline checks; temporary film state and a loopback-only random-port farm."""
import json
import os
from pathlib import Path
import py_compile
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from new_film import create
from validate_film import FilmConfig, ROOT, validate


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
        try:
            for _ in range(100):
                if proc.poll() is not None:
                    raise AssertionError(proc.communicate()[1].decode())
                try:
                    with urllib.request.urlopen(base+'/status?t='+token,timeout=.5) as response:
                        assert json.load(response)=={}
                    break
                except (urllib.error.URLError,TimeoutError): time.sleep(.05)
            else: raise AssertionError('Server did not become ready')
            for suffix in ['/status','/status?t=wrong']:
                try: urllib.request.urlopen(base+suffix,timeout=1)
                except urllib.error.HTTPError as exc: assert exc.code==403
                else: raise AssertionError('Unauthenticated request accepted')
            assert not (root/'renders/farm/token').exists()
            print('PASS farm /status authenticated=200; absent/wrong token=403; no token file')
        finally:
            proc.terminate()
            try: proc.communicate(timeout=5)
            except subprocess.TimeoutExpired: proc.kill(); proc.communicate(timeout=5)
        print('PASS owned farm process stopped; temporary state removed')
    print('PASS offline smoke test (no GPU or external network)')


if __name__=='__main__': main()
