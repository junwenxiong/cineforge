"""Isolated LTX regression checks; no cloud, live server, or token files."""
import ast
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

from film_config import FilmConfig
from ltx_stage import stage
from ltx_collect import collect


def main():
    root = Path(tempfile.mkdtemp(prefix='film-ltx-'))
    wf = root / 'films/testfilm'
    (wf / 'shots').mkdir(parents=True)
    (wf / 'scenes.json').write_text('[{"id":"S01"}]')
    assets = root / 'assets/testfilm'
    (assets / 'kf').mkdir(parents=True)
    key = assets / 'kf/testfilm_close.png'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=1344x768',
                    '-frames:v', '1', str(key)], check=True)
    shots = [dict(id='testfilm_close', engine='ltx', keyframe='assets/testfilm/kf/testfilm_close.png',
                  prompt='Fallback video prompt', seconds=1, refs=[]),
             dict(id='testfilm_missing', engine='ltx', keyframe='assets/testfilm/kf/other.png',
                  ltx_prompt='Video prompt', seconds=1, refs=['assets/missing.png']),
             dict(id='testfilm_h3', prompt='H3', seconds=1, refs=[])]
    (wf / 'shots/S01.json').write_text(json.dumps(shots))
    film = FilmConfig('testfilm', root)
    dry = stage(film, dry_run=True)
    assert not (root / 'renders').exists()
    assert len(dry['jobs']) == 1 and dry['jobs'][0]['prompt'].startswith('Fallback video prompt')
    assert dry['keyframe_specs'] == []
    assert dry['missing_refs'] == {'testfilm_missing': ['assets/missing.png']}
    result = stage(film)
    staged = result['jobs'][0]['keyframe']
    assert (root / staged).read_bytes() == key.read_bytes()
    lab = root / 'renders/lab/ltx_testfilm'
    lab.mkdir(parents=True)
    upload = lab / 'testfilm_close_distilled.mp4'
    upload.write_bytes(b'incomplete upload')
    assert collect(film) == []
    assert not (root / 'renders/testfilm_close/job.json').exists()
    def video(size, audio):
        cmd = ['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', f'color=c=blue:s={size}:r=24']
        if audio:
            cmd += ['-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000']
        subprocess.run(cmd + ['-t', '0.3', '-c:v', 'libx264', '-preset', 'ultrafast',
                              '-pix_fmt', 'yuv420p', str(upload)], check=True)
    video('320x240', True)
    assert collect(film) == []
    video('1344x768', False)
    assert collect(film) == []
    video('1344x768', True)
    receipt = root / 'renders/testfilm_close/job.json'
    receipt.write_text('{"status":"submitted"}')
    assert collect(film) == [] and receipt.read_text() == '{"status":"submitted"}'
    # Preserve fixture receipt without deletion; free the destination for acceptance check.
    receipt.rename(receipt.with_name('prior-job.json'))
    assert collect(film) == ['testfilm_close']
    before = receipt.read_bytes()
    record = json.loads(before)
    assert record['sha256'] == hashlib.sha256(upload.read_bytes()).hexdigest()
    assert record['via'] == 'ltx:ltx_testfilm'
    assert collect(film) == [] and receipt.read_bytes() == before
    assert stage(film, dry_run=True)['jobs'] == []
    # Execute only pure worker_config, never the Colab script's top-level main().
    source = Path(__file__).with_name('lab') / 'ltx25.py'
    tree = ast.parse(source.read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'worker_config')
    import re
    namespace = {'re': re}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(source), 'exec'), namespace)
    config = namespace['worker_config']
    assert config('ltx_catfilm_1') == ('ltx_catfilm', 0, 1)
    assert config('ltx_catfilm_0of2') == ('ltx_catfilm', 0, 2)
    assert config('ltx_catfilm_1of2') == ('ltx_catfilm', 1, 2)
    partitions = [[i for i in range(13) if i % config(w)[2] == config(w)[1]]
                  for w in ['ltx_starcore_0of2', 'ltx_starcore_1of2']]
    assert sorted(partitions[0] + partitions[1]) == list(range(13))
    assert not set(partitions[0]) & set(partitions[1])
    assert config('ltxv2a') == ('ltxv2', 0, 1)
    assert config('lab') == ('ltx25', 0, 1)
    try:
        config('ltx_catfilm_2of2')
        raise AssertionError('invalid shard accepted')
    except ValueError:
        pass
    # H3 has no CLI dry run. Test its loader/readiness functions without opening Box.
    h3_tree = ast.parse(Path(__file__).with_name('h3_film_queue.py').read_text())
    h3_functions = [n for n in h3_tree.body if isinstance(n, ast.FunctionDef)
                    and n.name in ('load_queue', 'ready')]
    h3 = {'ROOT': root, 'Path': Path, 'json': json, 'SCENE_ORDER': ['S01']}
    exec(compile(ast.Module(body=h3_functions, type_ignores=[]), 'h3_film_queue.py', 'exec'), h3)
    assert [s['id'] for s in h3['load_queue'](str(wf / 'shots'))] == ['testfilm_h3']
    assert not h3['ready'](shots[0])
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    escape = root / 'assets/testfilm/lab_kf_ltx/escape.png'
    escape.symlink_to(wf / 'scenes.json')
    env = dict(os.environ, LTX_TEST_TOKEN=secrets.token_urlsafe(24))
    server = subprocess.Popen([sys.executable, str(Path(__file__).with_name('farm_server.py')),
                               '--root', str(root), '--films', 'testfilm', '--port', str(port),
                               '--token-env', 'LTX_TEST_TOKEN'], env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    def request(path, post=False, **query):
        query['t'] = env['LTX_TEST_TOKEN']
        req = urllib.request.Request(f'http://127.0.0.1:{port}' + path + '?' + urllib.parse.urlencode(query),
                                     data=b'' if post else None)
        with urllib.request.urlopen(req, timeout=2) as response:
            return response.status, response.read()
    try:
        for _ in range(50):
            if server.poll() is not None:
                raise RuntimeError('Test server exited')
            try:
                request('/status')
                break
            except urllib.error.URLError:
                time.sleep(.1)
        assert request('/lab/kf', p=staged)[1] == key.read_bytes()
        for path in ['assets/testfilm/lab_kf_ltx/escape.png',
                     'assets/testfilm/lab_kf_ltx/../../../films/testfilm/scenes.json',
                     'assets/testfilm/kf/testfilm_close.png']:
            try:
                request('/lab/kf', p=path)
                raise AssertionError('non-staged/traversal file served')
            except urllib.error.HTTPError as exc:
                assert exc.code == 404
        assert json.loads(request('/claim', True, w='test')[1])['id'] == 'testfilm_h3'
        assert request('/claim', True, w='test')[0] == 204
        assert not (root / 'renders/testfilm_missing/claim.json').exists()
        assert not (root / 'renders/farm/token').exists()
        print(f'PASS: staging, fallback, missing specs, bad/resolution/audio rejection, receipt preservation,')
        print(f'collection SHA256/idempotency, worker names/shards, H3 skip, HTTP keyframe/traversal/claims on port {port}')
    finally:
        server.terminate()
        server.wait(timeout=10)
        print(f'Stopped only test child PID {server.pid}; fixtures retained: {root}')


if __name__ == '__main__':
    main()
