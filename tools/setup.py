#!/usr/bin/env python3
"""CineForge first-run setup and health check. Standard library only.

  python3 tools/setup.py init      create the private .env and ask for the HF token once
        --reset-hf                 replace the stored Hugging Face token
        --hf-token-stdin           read the token from stdin instead of prompting
        --venv                     also create .venv and install requirements.txt
        --hand-model               also download the MediaPipe hand model (~8 MB)
        --offline                  skip token verification and downloads
  python3 tools/setup.py doctor    PASS/WARN/FAIL report with a fix for each problem
        --offline --json
  python3 tools/setup.py run -- COMMAND ...
                                   run COMMAND with .env values added to its environment

Secrets live only in .env at the repository root. This script never prints them.
"""
import argparse
import ctypes.util
import getpass
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / '.env'
EXAMPLE = ROOT / '.env.example'
VENV = ROOT / '.venv'
HAND_URL = ('https://storage.googleapis.com/mediapipe-models/hand_landmarker/'
            'hand_landmarker/float16/latest/hand_landmarker.task')
HAND_MODEL = Path.home() / '.cache' / 'mp' / 'hand_landmarker.task'
HF_WHOAMI = 'https://huggingface.co/api/whoami-v2'
LTX_REPO = 'Lightricks/LTX-2.5'
LTX_PROBE = f'https://huggingface.co/{LTX_REPO}/resolve/main/.gitattributes'  # tiny, gated
SKILL = 'skills/cineforge/SKILL.md'
SKILL_STUBS = {'Claude Code': '.claude/skills/cineforge/SKILL.md',
               'Codex/Gemini': '.agents/skills/cineforge/SKILL.md'}
STUB_TEXT = """---
name: cineforge
description: Make AI films with the CineForge production playbook.
---
Read and follow skills/cineforge/SKILL.md from the repository root. Start with `python3 tools/smoke_test.py`, then `python3 tools/new_film.py NAME`. The shared playbook owns step order and commands; do not invent alternate automation or bypass the user's budget and authorization.
"""
MODULES = {'pillow': 'PIL'}
LINE = re.compile(r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$')


# ---------- .env handling (also importable: from setup import load_env) ----------

def parse_env(text):
    values = {}
    for line in text.splitlines():
        match = LINE.match(line)
        if not match:
            continue
        key, value = match.groups()
        if len(value) >= 2 and value[0] in '"\'' and value[-1] == value[0]:
            value = value[1:-1]
        else:
            value = re.split(r'\s+#', value, maxsplit=1)[0]
        values[key] = value
    return values


def read_env(path=ENV_FILE):
    return parse_env(path.read_text(encoding='utf-8')) if path.is_file() else {}


def load_env(path=ENV_FILE, environ=None):
    """Add non-empty .env values to environ; variables that are already set win."""
    environ = os.environ if environ is None else environ
    for key, value in read_env(path).items():
        if value and not environ.get(key):
            environ[key] = value
    return environ


def write_private(path, text):
    fd, tmp = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def set_env_value(path, key, value):
    lines = path.read_text(encoding='utf-8').splitlines() if path.exists() else []
    for index, line in enumerate(lines):
        match = LINE.match(line)
        if match and match.group(1) == key:
            lines[index] = f'{key}={value}'
            break
    else:
        lines.append(f'{key}={value}')
    write_private(path, '\n'.join(lines) + '\n')


def mask(token):
    return ('hf_' if token.startswith('hf_') else '') + f'… ({len(token)} chars)'


# ---------- small helpers ----------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # never forward the Authorization header to another host


def hf_request(url, token, method='GET'):
    request = urllib.request.Request(url, method=method, headers={
        'Authorization': f'Bearer {token}', 'User-Agent': 'cineforge-setup'})
    try:
        with urllib.request.build_opener(_NoRedirect).open(request, timeout=15) as response:
            return response.status, response.read() if method == 'GET' else b''
    except urllib.error.HTTPError as exc:
        return exc.code, b''


def hf_whoami(token):
    """Return (ok, text). Raises OSError on network problems."""
    code, body = hf_request(HF_WHOAMI, token)
    if code != 200:
        return False, f'Hugging Face rejected the token (HTTP {code})'
    data = json.loads(body or b'{}')
    role = (data.get('auth') or {}).get('accessToken', {}).get('role', 'unknown')
    return True, f"valid for user {data.get('name', '?')} ({role} token)"


def venv_python():
    for rel in ('bin/python', 'Scripts/python.exe'):
        if (VENV / rel).exists():
            return VENV / rel
    return None


def run_quiet(cmd, timeout=30):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return out.returncode, out.stdout + out.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        return -1, str(exc)


def requirement_modules():
    mods = {}
    path = ROOT / 'requirements.txt'
    for line in path.read_text().splitlines() if path.exists() else []:
        name = re.split(r'[\s<>=!~;\[#]', line.strip(), maxsplit=1)[0].lower()
        if name:
            mods[MODULES.get(name, name.replace('-', '_'))] = name
    return mods


PROBE = '''import importlib, json, sys
result = {}
for name in sys.argv[1:]:
    try:
        importlib.import_module(name); result[name] = ""
    except Exception as exc:
        result[name] = (type(exc).__name__ + ": " + str(exc))[:200]
print(json.dumps(result))'''


def probe_imports(python, modules):
    code, out = run_quiet([str(python), '-I', '-c', PROBE, *modules], timeout=180)
    try:
        return json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {m: 'could not run ' + Path(python).name for m in modules}


def ensure_skill_stubs():
    made = []
    for label, rel in SKILL_STUBS.items():
        path = ROOT / rel
        if not path.is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(STUB_TEXT, encoding='utf-8')
            made.append(rel)
    return made


# ---------- init ----------

def cmd_init(args):
    say = lambda status, text: print(f'{status:<4}  {text}')
    if sys.version_info < (3, 10):
        say('WARN', f'Python {sys.version.split()[0]} is older than 3.10; some tools will not run')
    if ENV_FILE.exists():
        say('OK', '.env already exists; keeping your values')
    else:
        template = EXAMPLE.read_text(encoding='utf-8') if EXAMPLE.exists() else 'HF_TOKEN=\n'
        write_private(ENV_FILE, template)
        say('NEW', '.env created from .env.example (private: chmod 600, gitignored)')
    try:
        os.chmod(ENV_FILE, 0o600)
    except OSError:
        pass

    current = read_env().get('HF_TOKEN', '')
    token = ''
    if args.hf_token_stdin:
        token = sys.stdin.readline().strip()
    elif not current or args.reset_hf:
        if sys.stdin.isatty():
            print('Paste your Hugging Face read token (https://huggingface.co/settings/tokens).')
            print('Typing is hidden. Press Enter on an empty line to skip for now.')
            token = getpass.getpass('HF token: ').strip()
        else:
            say('SKIP', 'no terminal for a hidden prompt; rerun init in a terminal, '
                        'or pipe the token with --hf-token-stdin')
    if token:
        if not re.fullmatch(r'[\x21-\x7e]+', token):
            say('FAIL', 'that does not look like a token (spaces or unusual characters); not saved')
            return 1
        if not token.startswith('hf_'):
            say('WARN', 'Hugging Face tokens usually start with hf_; saving anyway')
        set_env_value(ENV_FILE, 'HF_TOKEN', token)
        say('OK', f'HF_TOKEN saved to .env as {mask(token)}')
        current = token
    elif current:
        say('OK', f'HF_TOKEN already set: {mask(current)}; change it with --reset-hf')
    status = 0
    if current and not args.offline:
        try:
            ok, text = hf_whoami(current)
            say('OK' if ok else 'FAIL', 'HF token ' + text)
            if not ok:
                print('      fix: make a read token at https://huggingface.co/settings/tokens, '
                      'then run: python3 tools/setup.py init --reset-hf')
                status = 1
        except (OSError, ValueError) as exc:
            say('WARN', f'could not reach Hugging Face to verify the token ({type(exc).__name__})')

    for rel in ensure_skill_stubs():
        say('NEW', f'restored assistant skill pointer {rel}')

    if args.venv:
        if venv_python() is None:
            say('RUN', 'creating .venv')
            code, out = run_quiet([sys.executable, '-m', 'venv', str(VENV)], timeout=300)
            if code:
                say('FAIL', 'could not create .venv. On Debian/Ubuntu: sudo apt install python3-venv '
                            '(or install uv and run: uv venv .venv)')
                print(out.strip()[-800:])
                return 1
        say('RUN', 'installing requirements.txt into .venv (this can take a few minutes)')
        if subprocess.call([str(venv_python()), '-m', 'pip', 'install', '-q', '-r',
                            str(ROOT / 'requirements.txt')]):
            say('FAIL', 'pip install failed; read the error above')
            return 1
        say('OK', '.venv ready. Optional browser for Playwright: .venv/bin/python -m playwright install chromium')

    if args.hand_model:
        if HAND_MODEL.is_file() and HAND_MODEL.stat().st_size > 1_000_000:
            say('OK', 'MediaPipe hand model already in ~/.cache/mp')
        elif args.offline:
            say('SKIP', 'hand model download skipped (--offline)')
        else:
            HAND_MODEL.parent.mkdir(parents=True, exist_ok=True)
            tmp = HAND_MODEL.with_suffix('.part')
            try:
                with urllib.request.urlopen(HAND_URL, timeout=60) as response, tmp.open('wb') as out:
                    shutil.copyfileobj(response, out)
                if tmp.stat().st_size < 1_000_000:
                    raise OSError('download too small')
                tmp.replace(HAND_MODEL)
                say('OK', 'MediaPipe hand model saved to ~/.cache/mp/hand_landmarker.task')
            except OSError as exc:
                tmp.unlink(missing_ok=True)
                say('WARN', f'hand model download failed ({exc}); rerun init --hand-model later')

    print('Next: python3 tools/setup.py doctor')
    return status


# ---------- doctor ----------

def cmd_doctor(args):
    checks = []

    def add(status, name, detail, fix=''):
        checks.append({'name': name, 'status': status, 'detail': detail, 'fix': fix if status != 'PASS' else ''})

    version = sys.version.split()[0]
    add('PASS' if sys.version_info >= (3, 10) else 'FAIL', 'python', f'Python {version}',
        'install Python 3.10 or newer: https://www.python.org/downloads/')

    for tool in ('ffmpeg', 'ffprobe'):
        if not shutil.which(tool):
            add('FAIL', tool, 'not found on PATH', 'sudo apt install ffmpeg  (macOS: brew install ffmpeg)')
            continue
        code, out = run_quiet([tool, '-hide_banner', '-version'])
        detail = (out.splitlines() or ['found'])[0].split(' Copyright')[0][:70]
        if tool == 'ffmpeg':
            code, filters = run_quiet([tool, '-hide_banner', '-filters'])
            if not re.search(r'\ssubtitles\s', filters):
                add('WARN', tool, detail + '; no subtitles filter',
                    'install an ffmpeg built with libass (sudo apt install ffmpeg)')
                continue
        add('PASS', tool, detail)

    add('PASS' if shutil.which('git') else 'WARN', 'git', 'found' if shutil.which('git') else 'not found',
        'sudo apt install git  (needed to update CineForge and check .gitignore)')
    add('PASS' if shutil.which('uv') else 'WARN', 'uv', 'found' if shutil.which('uv') else 'not found (optional)',
        'optional faster installer: https://docs.astral.sh/uv/getting-started/installation/')

    if shutil.which('fc-list'):
        code, out = run_quiet(['fc-list', ':lang=zh', 'family'])
        add('PASS' if out.strip() and code == 0 else 'WARN', 'cjk-font',
            'Chinese subtitle font found' if out.strip() and code == 0 else 'no Chinese font found',
            'sudo apt install fonts-noto-cjk')
    else:
        add('WARN', 'cjk-font', 'fc-list not available; cannot check fonts',
            'install fontconfig and a CJK font such as Noto Sans CJK')

    python = venv_python()
    add('PASS' if python else 'WARN', 'venv', '.venv found' if python else 'no .venv yet',
        'python3 tools/setup.py init --venv')
    python = python or Path(sys.executable)
    where = '.venv' if venv_python() else 'this Python'
    modules = requirement_modules()
    results = probe_imports(python, list(modules) + ['mediapipe'])
    missing = [pkg for mod, pkg in modules.items() if results.get(mod)]
    add('WARN' if missing else 'PASS', 'packages',
        f'missing in {where}: {", ".join(missing)}' if missing else f'requirements import in {where}',
        'python3 tools/setup.py init --venv')
    error = results.get('mediapipe', '')
    if not error:
        add('PASS', 'mediapipe', f'imports in {where}')
    elif 'libGLES' in error or 'libEGL' in error:
        add('WARN', 'mediapipe', 'installed but system GL libraries are missing', 'sudo apt install libgles2 libegl1')
    else:
        add('WARN', 'mediapipe', f'not importable in {where} (optional, hand checks)',
            'after init --venv: .venv/bin/python -m pip install mediapipe')
    if sys.platform.startswith('linux'):
        libs = [lib for lib in ('GLESv2', 'EGL') if not ctypes.util.find_library(lib)]
        add('WARN' if libs else 'PASS', 'gl-libs',
            'missing ' + ', '.join('lib' + lib for lib in libs) if libs else 'libGLESv2 and libEGL found',
            'sudo apt install libgles2 libegl1  (needed by mediapipe)')

    # .env and the token
    if not ENV_FILE.is_file():
        add('FAIL', 'env-file', '.env not found', 'python3 tools/setup.py init')
    else:
        add('PASS', 'env-file', '.env found')
        if os.name == 'nt':
            add('INFO', 'env-permissions', 'Windows: keep the repository inside your user folder')
        else:
            mode = stat.S_IMODE(ENV_FILE.stat().st_mode)
            fix = 'chmod 600 .env'
            if str(ROOT).startswith('/mnt/'):
                fix += ('  (this Windows drive ignores chmod: clone CineForge into your Linux home, '
                        'or enable WSL drvfs "metadata")')
            add('PASS' if mode & 0o077 == 0 else 'WARN', 'env-permissions', f'mode {mode:o}', fix)
    if shutil.which('git'):
        ignored = run_quiet(['git', '-C', str(ROOT), 'check-ignore', '-q', '.env'])[0]
        tracked = run_quiet(['git', '-C', str(ROOT), 'ls-files', '--error-unmatch', '.env'])[0] == 0
        if tracked:
            add('FAIL', 'env-ignored', '.env is committed to git',
                'git rm --cached .env, then revoke and replace every token in it')
        elif ignored == 0:
            add('PASS', 'env-ignored', '.env is gitignored')
        elif ignored == 1:
            add('FAIL', 'env-ignored', '.env is NOT gitignored', 'add a line ".env" to .gitignore')
        else:
            add('WARN', 'env-ignored', 'not a git checkout; cannot confirm', 'clone with git so .gitignore applies')
    else:
        add('WARN', 'env-ignored', 'git not installed; cannot confirm', 'sudo apt install git')

    token, source = os.environ.get('HF_TOKEN', ''), 'shell environment (overrides .env)'
    if not token:
        token, source = read_env().get('HF_TOKEN', ''), '.env'
    if not token:
        add('FAIL', 'hf-token', 'HF_TOKEN is empty', 'python3 tools/setup.py init  (hidden prompt)')
    else:
        good = token.startswith('hf_') and re.fullmatch(r'[\x21-\x7e]+', token)
        add('PASS' if good else 'WARN', 'hf-token', f'{mask(token)} from {source}',
            'tokens start with hf_: python3 tools/setup.py init --reset-hf')
    if args.offline or not token:
        reason = '--offline' if args.offline else 'no token'
        add('SKIP', 'hf-login', f'not checked ({reason})')
        add('SKIP', 'ltx-access', f'not checked ({reason})')
    else:
        try:
            ok, text = hf_whoami(token)
            add('PASS' if ok else 'FAIL', 'hf-login', text,
                'make a new read token at https://huggingface.co/settings/tokens, then init --reset-hf')
            code = hf_request(LTX_PROBE, token, method='HEAD')[0] if ok else 0
            if not ok:
                add('SKIP', 'ltx-access', 'not checked (token rejected)')
            elif 200 <= code < 400:
                add('PASS', 'ltx-access', f'{LTX_REPO} license accepted')
            else:
                add('FAIL', 'ltx-access', f'{LTX_REPO} files refused (HTTP {code})',
                    f'log in at https://huggingface.co/{LTX_REPO} and accept the license; fine-grained tokens '
                    'also need "Read access to contents of all public gated repos you can access"')
        except (OSError, ValueError) as exc:
            add('WARN', 'hf-login', f'could not reach Hugging Face ({type(exc).__name__})',
                'check your internet connection, or run doctor --offline')
            add('SKIP', 'ltx-access', 'not checked (no connection)')

    size_ok = HAND_MODEL.is_file() and HAND_MODEL.stat().st_size > 1_000_000
    add('PASS' if size_ok else 'WARN', 'hand-model',
        '~/.cache/mp/hand_landmarker.task found' if size_ok else 'MediaPipe hand model missing (optional)',
        'python3 tools/setup.py init --hand-model')

    add('PASS' if shutil.which('cloudflared') else 'WARN', 'cloudflared',
        'found' if shutil.which('cloudflared') else 'not found (needed to connect Colab to your farm)',
        'https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/')
    chrome = next((n for n in ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser', 'chrome')
                   if shutil.which(n)), '')
    caches = [Path(os.environ['PLAYWRIGHT_BROWSERS_PATH'])] if os.environ.get('PLAYWRIGHT_BROWSERS_PATH') else []
    caches += [Path.home() / '.cache/ms-playwright', Path.home() / 'Library/Caches/ms-playwright']
    if not chrome and any(p.is_dir() and any(p.glob('chromium-*')) for p in caches):
        chrome = 'Playwright Chromium'
    if not chrome and Path('/mnt/c/Program Files/Google/Chrome/Application/chrome.exe').exists():
        chrome = 'Windows Chrome (via WSL)'
    add('PASS' if chrome else 'WARN', 'chrome', chrome or 'no Chrome/Chromium found (optional browser tools)',
        '.venv/bin/python -m playwright install chromium')

    found = [n for n in ('claude', 'codex', 'gemini') if shutil.which(n)]
    add('INFO', 'assistants', ('on PATH: ' + ', '.join(found)) if found else 'no claude, codex or gemini on PATH')
    missing = [label for label, rel in SKILL_STUBS.items()
               if not (ROOT / rel).is_file() or SKILL not in (ROOT / rel).read_text(encoding='utf-8')]
    add('WARN' if missing or not (ROOT / SKILL).is_file() else 'PASS', 'skills',
        f'missing for {", ".join(missing)}' if missing else 'cineforge skill visible to Claude Code, Codex and Gemini',
        'python3 tools/setup.py init')
    claude_md = ROOT / 'CLAUDE.md'
    imports = claude_md.is_file() and '@AGENTS.md' in claude_md.read_text(encoding='utf-8')
    ok = imports and (ROOT / 'AGENTS.md').is_file() and (ROOT / 'GEMINI.md').is_file()
    add('PASS' if ok else 'WARN', 'instructions',
        'AGENTS.md, CLAUDE.md (@AGENTS.md) and GEMINI.md present' if ok else 'assistant instruction files incomplete',
        'git checkout -- AGENTS.md CLAUDE.md GEMINI.md')

    summary = {s: sum(c['status'] == s for c in checks) for s in ('PASS', 'WARN', 'FAIL', 'INFO', 'SKIP')}
    if args.json:
        print(json.dumps({'ok': not summary['FAIL'], 'summary': summary, 'checks': checks}, indent=2))
    else:
        print('CineForge doctor')
        for c in checks:
            print(f"{c['status']:<4}  {c['name']:<16}{c['detail']}")
            if c['fix'] and c['status'] in ('WARN', 'FAIL'):
                print(f"{'':<22}fix: {c['fix']}")
        print('Summary: ' + ', '.join(f'{n} {s}' for s, n in summary.items() if n))
    return 1 if summary['FAIL'] else 0


# ---------- run ----------

def cmd_run(args):
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        print('usage: python3 tools/setup.py run -- COMMAND [ARGS...]', file=sys.stderr)
        return 2
    if not ENV_FILE.is_file():
        print('note: .env not found; run python3 tools/setup.py init', file=sys.stderr)
    try:
        return subprocess.call(command, env=load_env(environ=dict(os.environ)))
    except FileNotFoundError:
        print(f'command not found: {command[0]}', file=sys.stderr)
        return 127
    except KeyboardInterrupt:
        return 130


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='cmd', required=True)
    init = sub.add_parser('init', help='create .env, store the HF token once, optional venv and hand model')
    init.add_argument('--reset-hf', action='store_true', help='replace the stored Hugging Face token')
    init.add_argument('--hf-token-stdin', action='store_true', help='read the token from stdin (no prompt)')
    init.add_argument('--venv', action='store_true', help='create .venv and install requirements.txt')
    init.add_argument('--hand-model', action='store_true', help='download the MediaPipe hand model to ~/.cache/mp')
    init.add_argument('--offline', action='store_true', help='skip token verification and downloads')
    doctor = sub.add_parser('doctor', help='check this computer and print a fix for each problem')
    doctor.add_argument('--offline', action='store_true', help='skip Hugging Face network checks')
    doctor.add_argument('--json', action='store_true', help='machine-readable output')
    run = sub.add_parser('run', help='run a command with .env loaded into its environment')
    run.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    return {'init': cmd_init, 'doctor': cmd_doctor, 'run': cmd_run}[args.cmd](args)


if __name__ == '__main__':
    sys.exit(main())
