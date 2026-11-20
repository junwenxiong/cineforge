"""Local isolated HTTP regression check. No cloud, live farm, or token files."""
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


def main():
    root = Path(tempfile.mkdtemp(prefix='film-p0-'))
    for name, prefix in [('starcore', 'sc'), ('catfilm', 'catfilm')]:
        wf = root / 'films' / name
        (wf / 'shots').mkdir(parents=True)
        (wf / 'scenes.json').write_text(json.dumps([{'id': 'S01'}, {'id': 'S02'}]))
        ref = root / 'assets' / name / 'refs/a.png'
        ref.parent.mkdir(parents=True)
        ref.write_bytes(b'reference-fixture')
        for scene in ['S01', 'S02']:
            shots = [dict(id=f'{prefix}_{scene.lower()}_{i:02}', scene=scene, prompt='test', seconds=1,
                          refs=[ref.relative_to(root).as_posix()]) for i in [1, 2]]
            (wf / 'shots' / f'{scene}.json').write_text(json.dumps(shots))
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = dict(os.environ, FILM_TEST_TOKEN=secrets.token_urlsafe(24))
    server = subprocess.Popen([sys.executable, str(Path(__file__).with_name('farm_server.py')),
                               '--root', str(root), '--farm-dir', str(root / 'state'), '--port', str(port),
                               '--films', 'starcore,catfilm', '--token-env', 'FILM_TEST_TOKEN'], env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    def request(path, post=False, **query):
        query['t'] = env['FILM_TEST_TOKEN']
        req = urllib.request.Request(f'http://127.0.0.1:{port}' + path + '?' + urllib.parse.urlencode(query),
                                     data=b'' if post else None)
        with urllib.request.urlopen(req, timeout=2) as response:
            return response.status, response.read()
    try:
        for _ in range(50):
            if server.poll() is not None:
                raise RuntimeError('Test server exited (port 8799 may be occupied)')
            try:
                status, data = request('/status')
                break
            except urllib.error.URLError:
                time.sleep(.1)
        else:
            raise AssertionError('Test server did not start')
        assert status == 200 and json.loads(data) == {}
        assert request('/ref/assets/catfilm/refs/a.png')[1] == b'reference-fixture'
        try:
            request('/ref/../films/catfilm/scenes.json')
            raise AssertionError('Traversal allowed')
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
        expected = [f'{p}_{s}_{i:02}' for p in ['sc', 'catfilm'] for s in ['s02', 's01'] for i in [2, 1]]
        actual = [json.loads(request('/claim', True, w='test')[1])['id'] for _ in expected]
        assert actual == expected, actual
        assert request('/claim', True, w='test')[0] == 204
        assert 'test' in json.loads(request('/status')[1])
        assert not (root / 'state/token').exists()
        # Release only test fixtures, then check explicit worker film selection.
        for claim in (root / 'renders').glob('*/claim.json'):
            record = json.loads(claim.read_text()); record['lease_until'] = 0
            claim.write_text(json.dumps(record))
        assert json.loads(request('/claim', True, w='cat', films='catfilm')[1])['id'] == 'catfilm_s02_02'
        print('PASS: /status, 8 priority/reverse claims, exhaustion, film filter, cross-film refs, traversal rejection, no token files')
        print(f'Fixture retained: {root}')
    finally:
        server.terminate()
        server.wait(timeout=10)
        print('Stopped only test child PID', server.pid)


if __name__ == '__main__':
    main()
