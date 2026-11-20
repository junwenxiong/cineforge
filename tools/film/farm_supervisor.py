"""Conservative farm supervisor. --dry-run is one read-only decision pass.

No server/tunnel restarts, no raw browser output logging, no receipt deletion.
Unknown browser/runtime state always fails closed. SIGTERM stops only this daemon.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.request
import urllib.parse

ROOT = Path(__file__).resolve().parents[2]
FARM = ROOT / 'renders/farm'
HERE = Path(__file__).resolve().parent
FILMS = ('catfilm', 'echo', 'starcore')


def read_json(path, default=None):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def events(path, now):
    """Resolve time-only log lines backwards, including midnight rollover."""
    if not path.exists():
        return []
    day = time.localtime(path.stat().st_mtime)
    midnight = time.mktime((day.tm_year, day.tm_mon, day.tm_mday, 0, 0, 0, 0, 0, -1))
    result, previous = [], 86400
    for line in reversed(path.read_text(encoding='utf-8', errors='replace').splitlines()):
        if not re.match(r'^\d\d:\d\d:\d\d ', line):
            continue
        h, m, s = map(int, line[:8].split(':'))
        seconds = h * 3600 + m * 60 + s
        if seconds > previous:
            midnight -= 86400
        previous = seconds
        stamp = midnight + seconds
        if now - stamp > 86400:
            break
        result.append((stamp, line[9:]))
    return list(reversed(result))


class Supervisor:
    def __init__(self, dry=False):
        self.dry = dry
        self.state_path = FARM / 'supervisor_state.json'
        self.state = read_json(self.state_path, {})
        self.alerted = {}
        self.last_report = 0
        self.started = time.time()
        self.orphans = {}
        self.dead = False

    def log(self, message, alert=False):
        # Messages must be constructed from IDs/metrics, never subprocess errors.
        line = time.strftime('%Y-%m-%d %H:%M:%S ') + ('DRY ' if self.dry else '') + message
        print(line, flush=True)
        if not self.dry:
            with (FARM / ('supervisor_alerts.log' if alert else 'supervisor.log')).open('a') as f:
                f.write(line + '\n')

    def alert(self, key, message):
        if time.time() - self.alerted.get(key, 0) > 1800:
            self.alerted[key] = time.time()
            self.log('ESCALATION ' + message, True)

    def api(self, path, data=None, **query):
        query['t'] = (FARM / 'token').read_text().strip()
        request = urllib.request.Request('http://127.0.0.1:8765' + path + '?' + urllib.parse.urlencode(query), data=data)
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read() or b'{}')

    def probe(self, name=None):
        result = subprocess.run(['python.exe', '-X', 'utf8', str(HERE.relative_to(ROOT) / 'farm_supervisor_browser.py'),
                                 *([name] if name else [])], cwd=ROOT, capture_output=True, timeout=45)
        if result.returncode:
            self.alert('browser', 'Windows Python / isolated CDP 9333 unavailable; cloud actions blocked (WSL interop may be restricted)')
            return None
        try:
            return json.loads(result.stdout)
        except ValueError:
            self.alert('probe', 'Browser probe returned invalid status; cloud actions blocked')
            return None

    def drive(self, command, *args):
        self.log('action colab_drive ' + ' '.join((command, *args)))
        if self.dry:
            return True
        try:
            result = subprocess.run(['python.exe', '-X', 'utf8', 'tools/film/farm_supervisor_browser.py', '--drive', command, *args],
                                    cwd=ROOT, capture_output=True, timeout=150)
            if result.returncode == 0:
                return True
        except subprocess.TimeoutExpired:
            pass
        self.alert('drive:' + command, f'colab_drive {command} failed/timed out; inspect isolated browser; output suppressed for credentials')
        return False

    def drain(self, worker, enabled=True):
        path = FARM / 'drain'
        names = set(path.read_text().split()) if path.exists() else set()
        owned = self.state.setdefault('owned_drains', [])
        if not enabled and worker not in owned:
            return
        if (worker in names) == enabled:
            return
        self.log(f'drain {worker}={enabled}')
        if not self.dry:
            names.add(worker) if enabled else names.discard(worker)
            if enabled and worker not in owned:
                owned.append(worker)
            elif not enabled and worker in owned:
                owned.remove(worker)
            path.write_text(' '.join(sorted(names)) + '\n')

    def progress(self):
        counts, pending, claims = {}, {}, {}
        for film in FILMS:
            shots = [s for p in sorted((ROOT / 'films' / film / 'shots').glob('*.json')) for s in json.loads(p.read_text())]
            counts[film] = {'h3': [0, 0], 'ltx': [0, 0]}
            pending[film] = 0
            for shot in shots:
                kind = 'ltx' if shot.get('engine') == 'ltx' else 'h3'
                sid = shot['id']; folder = ROOT / 'renders' / sid
                job = read_json(folder / 'job.json', {})
                complete = job.get('status') == 'completed' and (folder / 'raw.mp4').is_file()
                counts[film][kind][1] += 1
                counts[film][kind][0] += int(complete)
                claim = read_json(folder / 'claim.json', {})
                if kind == 'h3' and not complete and not (folder / 'job.json').exists() and claim.get('status') != 'done':
                    if claim.get('status') == 'claimed' or (claim.get('attempts', 0) < 3 and all((ROOT / r).is_file() for r in shot.get('refs', []))):
                        pending[film] += 1
                    else:
                        self.alert('blocked:' + film, f'{film}: H3 shots blocked by missing references or exhausted attempts')
                if claim.get('status') == 'claimed' and not (folder / 'job.json').exists():
                    claims[sid] = claim
        return counts, pending, claims

    def verify(self, worker, log, now):
        waiting = self.state.setdefault('verify', {})
        start = waiting.get(worker)
        if not start:
            return False
        if any(t > start and (re.search(rf'^claim .* -> {re.escape(worker)}$', l) or
                             re.search(rf'^saved .* from {re.escape(worker)} ', l)) for t, l in log):
            self.log(f'verified {worker}: new claim/saved after restart')
            del waiting[worker]
            return False
        if now - start > 180:
            self.alert('verify:' + worker, f'{worker}: no new claim/saved within 3 minutes after start/rerun')
        return True

    def repair(self, worker, page, now):
        if self.probe(None if self.dry else 'starcore_' + worker) is None:
            return
        self.log(f'health inspection {worker}: masked screenshot captured')
        self.state.setdefault('cooldown', {})[worker] = now
        if page['disconnected']:
            # Only recreate positively disconnected runtimes, never infer from heartbeat.
            self.drain(worker)
            if not self.drive('kill', 'starcore_' + worker):
                return
            if not self.drive('close', 'starcore_' + worker):
                return
            self.drain(worker, False)
            ok = self.drive('new', worker, 'G4 GPU')
        else:
            ok = self.drive('rerun', 'starcore_' + worker)
        if ok:
            self.state.setdefault('verify', {})[worker] = time.time()

    def launch(self, worker, lab=None):
        ok = self.drive('newlab', worker, 'G4 GPU', 'ltx25.py') if lab else self.drive('new', worker, 'G4 GPU')
        if ok and not lab:
            self.state.setdefault('verify', {})[worker] = time.time()
        if not self.dry:
            pages = self.probe()
            if pages:
                for page in pages:
                    if page['name'] == 'starcore_' + worker and page['limited']:
                        self.drive('click', page['name'], '取消', 'Cancel')
                        self.log(f'capacity limit {worker}; backoff 15 minutes; existing runtimes retained')
                        self.state.setdefault('verify', {}).pop(worker, None)

    def release_orphans(self, status, claims, now):
        current = {s for v in status.values() for s in v.get('current', [])}
        for sid, claim in claims.items():
            worker = claim.get('worker', '')
            v = status.get(worker, {})
            # No lease edits outside server lock. Require two fresh idle snapshots:
            # missing heartbeat/current is not proof a GPU stopped preparing a shot.
            candidate = (sid not in current and now - claim.get('at', now) > 600 and
                         claim.get('lease_until', 0) > now + 120 and
                         now - v.get('seen', 0) < 90 and v.get('state') in ('idle', 'finished') and not v.get('current'))
            if not candidate:
                self.orphans.pop(sid, None)
                continue
            if sid not in self.orphans:
                self.orphans[sid] = now
                self.drain(worker)
                continue
            if now - self.orphans[sid] < 60:
                continue
            fresh = self.api('/status')
            latest = read_json(ROOT / 'renders' / sid / 'claim.json', {})
            if (latest != claim or latest.get('lease_until', 0) <= time.time() + 60 or (ROOT / 'renders' / sid / 'job.json').exists() or
                    any(sid in x.get('current', []) for x in fresh.values())):
                continue
            self.log(f'release orphan {sid} owner={worker} via server fail; attempts retained')
            if not self.dry:
                self.api('/fail/' + sid, b'supervisor: orphan after two fresh idle snapshots', w=worker)
            self.drain(worker, False)

    def vsr_valid(self, sid):
        path = ROOT / 'renders/lab/vsr' / (sid + '.mp4')
        meta = read_json(path.with_suffix('.json'), {})
        return path.is_file() and bool(meta.get('output_sha256')) and hashlib.sha256(path.read_bytes()).hexdigest() == meta['output_sha256']

    def ensure_collector(self, script, film=None):
        # PID namespaces can conceal existing host processes. Never guess absence.
        if Path('/proc/1/comm').read_text().strip().startswith('codex'):
            self.alert('pidnamespace', 'Host process namespace unavailable; cannot safely verify/restart VSR assembler or LTX collectors')
            return
        args = ['python3', '-u', str(HERE / script), *(['--film', film] if film else []), '--watch']
        for path in Path('/proc').glob('[0-9]*/cmdline'):
            try:
                words = path.read_bytes().decode().split('\0')
                if any(Path(x).name == script for x in words) and (not film or film in words) and '--watch' in words:
                    return
            except (OSError, UnicodeError):
                pass
        self.log('start collector ' + script + (' ' + film if film else ''))
        if not self.dry:
            with (FARM / ('supervisor_' + script + (film or '') + '.out')).open('ab') as out:
                subprocess.Popen(args, cwd=ROOT, stdout=out, stderr=out, start_new_session=True)

    def tick(self):
        now = time.time()
        try:
            status = self.api('/status')
        except Exception:
            self.alert('server', 'Farm server unavailable; stopping supervisor without touching server/tunnel (in-memory HF secret)')
            self.dead = True
            return
        # Tunnel liveness is tested without ever logging its address or credentials.
        try:
            base = (FARM / 'url').read_text().strip()
            token = (FARM / 'token').read_text().strip()
            with urllib.request.urlopen(base + '/status?t=' + urllib.parse.quote(token), timeout=15) as r:
                r.read()
        except Exception:
            self.state['tunnel_failures'] = self.state.get('tunnel_failures', 0) + 1
            self.alert('tunnel', 'Tunnel unavailable; cloud mutations suspended; server/tunnel must not be restarted')
            if self.state['tunnel_failures'] >= 3:
                self.log('stopping after three tunnel failures; operator intervention required')
                self.dead = True
            return
        self.state['tunnel_failures'] = 0
        log = events(FARM / 'farm.log', now)
        counts, pending, claims = self.progress()
        rejected = sum('bad upload rejected' in l for t, l in log if now - t <= 600)
        mb = sum(float(m.group(1)) for t, l in log if now - t <= 300 and
                 (l.startswith('saved ') or l.startswith('lab upload ')) and (m := re.search(r' ([\d.]+)MB', l))) / 5
        vsr = sum(p.with_suffix('.mp4').is_file() and read_json(p, {}).get('output_sha256') is not None
                  for p in (ROOT / 'renders/lab/vsr').glob('*.json'))
        pages = self.probe()
        if now - self.last_report >= 300:
            self.log('progress ' + ' '.join(f'{f}:H3={c["h3"][0]}/{c["h3"][1]},LTX={c["ltx"][0]}/{c["ltx"][1]}' for f, c in counts.items()) +
                     f' VSR={vsr}/354 active_runtimes=' + (str(sum(not p['disconnected'] for p in pages)) if pages is not None else 'unknown') +
                     f' upload_MB/min={mb:.2f} rejected_10min={rejected}')
            self.last_report = now
        self.ensure_collector('vsr_assemble.py')
        for film in ('catfilm', 'echo'):
            if (FARM / f'lab_jobs_ltx_{film}.json').exists():
                self.ensure_collector('ltx_collect.py', film)
        if pages is None:
            for worker, value in status.items():
                if not re.fullmatch(r'g4cf\d+', worker):
                    continue
                saves = [t for t, line in log if re.search(rf'^saved .* from {re.escape(worker)} ', line)]
                if now - value.get('seen', 0) > 180 or (value.get('current') and now - max(saves or [self.started]) > 420):
                    self.alert('blocked-health:' + worker, f'{worker}: health threshold exceeded; browser unavailable, repair blocked')
            if sum(pending.values()) and now - self.state.get('capacity', 0) >= 900:
                self.log('capacity decision: g4cf3 candidate; cannot attempt until isolated browser is observable')
                self.state['capacity'] = now
            return
        by_name = {p['name']: p for p in pages}
        for page in pages:
            if page['limited'] and re.fullmatch(r'starcore_g4cf\d+', page['name']):
                self.drive('click', page['name'], '取消', 'Cancel')
        self.release_orphans(status, claims, now)
        for worker, v in status.items():
            page = by_name.get('starcore_' + worker)
            # Scope: farm-owned workers only, never Box h100a/unknown notebooks.
            if not re.fullmatch(r'g4cf\d+', worker) or not page:
                continue
            if self.verify(worker, log, now):
                continue
            owned = [c for c in claims.values() if c.get('worker') == worker]
            if not sum(pending.values()):
                self.drain(worker)
                if not v.get('current') and not owned and now - v.get('seen', 0) < 90:
                    if self.drive('kill', page['name']):
                        self.drive('close', page['name'])
                continue
            last = max([t for t, l in log if re.search(rf'^saved .* from {re.escape(worker)} ', l)] or
                       [min([c['at'] for c in owned] or [now])])
            stalled = (bool(owned or v.get('current')) and now - last > 420) or now - v.get('seen', 0) > 180
            if stalled and now - self.state.get('cooldown', {}).get(worker, 0) > 900:
                self.repair(worker, page, now)
        page = by_name.get('starcore_vsr0of2')
        if page:
            # Films first: don't infer spare bandwidth from low throughput on a slow link.
            if pending['catfilm'] + pending['echo']:
                if self.state.get('vsr') != 'paused':
                    if self.drive('stop', page['name']):
                        self.state['vsr'] = 'paused'
            elif self.state.get('vsr') != 'running' and vsr < 354:
                if self.drive('run', page['name']):
                    self.state['vsr'] = 'running'
            # Do not kill a sharded lab until its explicit final upload log exists.
            finished = any('[vsr0of2]' in l and 'finished rc=0' in l for _, l in events(FARM / 'lab.log', now))
            vsr_jobs = read_json(FARM / 'lab_jobs_vsr.json', [])
            shard = [j for i, j in enumerate(vsr_jobs) if j.get('index', i) % 2 == 0]
            received = bool(shard) and all(self.vsr_valid(j['id']) for j in shard)
            if finished and received and not page['busy'] and now - max([t for t, l in log if 'from vsr0of2' in l] or [now]) > 120:
                if self.drive('kill', page['name']):
                    self.drive('close', page['name'])
        for film in ('catfilm', 'echo'):
            worker = f'ltx_{film}_0of1'
            page = by_name.get('starcore_' + worker)
            jobs = read_json(FARM / f'lab_jobs_ltx_{film}.json', [])
            finished = any(f'[{worker}]' in l and 'lab finished' in l for _, l in events(FARM / 'lab.log', now))
            last_upload = max([t for t, l in log if 'from ' + worker in l] or [now])
            if page and jobs and finished and not page['busy'] and now - last_upload > 120 and all(
                    read_json(ROOT / 'renders' / j['id'] / 'job.json', {}).get('status') == 'completed' for j in jobs):
                if self.drive('kill', page['name']):
                    self.drive('close', page['name'])
        if now - self.state.get('capacity', 0) >= 900:
            self.state['capacity'] = now
            active = sum(not p['disconnected'] for p in pages)
            if active < 4:
                for film in ('catfilm', 'echo'):
                    jobs = read_json(FARM / f'lab_jobs_ltx_{film}.json', [])
                    worker = f'ltx_{film}_0of1'
                    stable = (FARM / f'lab_jobs_ltx_{film}.json').exists() and now - (FARM / f'lab_jobs_ltx_{film}.json').stat().st_mtime > 120
                    if stable and jobs and any(not (ROOT / 'renders' / j['id'] / 'job.json').exists() for j in jobs) and not any(p['name'].startswith(f'starcore_ltx_{film}_') for p in pages):
                        self.launch(worker, lab=True)
                        return
                if sum(pending.values()):
                    for n in range(1, 9):
                        worker = f'g4cf{n}'
                        page = by_name.get('starcore_' + worker)
                        if page and page['disconnected']:
                            if self.drive('run', page['name']):
                                self.state.setdefault('verify', {})[worker] = time.time()
                                after = self.probe() if not self.dry else []
                                for item in after or []:
                                    if item['name'] == page['name'] and item['limited']:
                                        self.drive('click', page['name'], '取消', 'Cancel')
                                        self.state.setdefault('verify', {}).pop(worker, None)
                                        self.log('capacity limit; backoff 15 minutes')
                            return
                        if page is None:
                            self.launch(worker)
                            return

    def run(self, once=False):
        while True:
            stop = FARM / 'supervisor.stop'
            if stop.exists() and stop.stat().st_mtime >= self.started:
                self.log('stop requested; leaving farm workers/server/tunnel running')
                break
            start = time.monotonic()
            try:
                self.tick()
            except Exception as exc:
                self.alert('exception', 'Supervisor iteration failed: ' + type(exc).__name__ + '; retry in 60s')
            if not self.dry:
                temp = self.state_path.with_suffix('.tmp')
                try:
                    temp.write_text(json.dumps(self.state))
                    temp.replace(self.state_path)
                except OSError:
                    print('Supervisor state persistence failed; retry next iteration', flush=True)
            if once or self.dry or self.dead:
                break
            time.sleep(max(1, 60 - (time.monotonic() - start)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    FARM.mkdir(parents=True, exist_ok=True)
    if args.dry_run:
        Supervisor(True).run(True)
        return
    with (FARM / 'supervisor.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Supervisor already running')
        (FARM / 'supervisor.pid').write_text(str(os.getpid()) + '\n')
        Supervisor().run(args.once)


if __name__ == '__main__':
    main()
