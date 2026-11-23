#!/usr/bin/env node
/**
 * Zero-dependency UI & Visual E2E Verification Script for CineForge Studio.
 * Uses Node v24 built-in fetch + WebSocket over Chromium CDP at 1440x900.
 */

import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const ROOT = path.resolve(__dirname, '..', '..');
const STUDIO_DIR = path.join(ROOT, 'studio');

function findChromeBinary() {
  if (process.env.CHROME_BIN && fs.existsSync(process.env.CHROME_BIN)) {
    return process.env.CHROME_BIN;
  }
  const cacheDir = path.join(os.homedir(), '.cache', 'ms-playwright');
  if (fs.existsSync(cacheDir)) {
    const dirs = fs.readdirSync(cacheDir).filter((d) => d.startsWith('chromium-')).sort().reverse();
    for (const d of dirs) {
      const cand = path.join(cacheDir, d, 'chrome-linux64', 'chrome');
      if (fs.existsSync(cand)) return cand;
    }
  }
  for (const name of ['google-chrome', 'chromium', 'chromium-browser']) {
    const res = spawnSync('which', [name], { encoding: 'utf8' });
    const found = (res.stdout || '').trim();
    if (res.status === 0 && found) return found;
  }
  throw new Error('Chromium binary not found; set CHROME_BIN or install Playwright chromium');
}

const CHROME_BIN = findChromeBinary();
const DEFAULT_OUT_DIR = process.env.CINEFORGE_UX_REPORT_DIR || path.join(os.tmpdir(), 'cineforge-verify-ui');

function parseArgs(argv) {
  const args = { outDir: DEFAULT_OUT_DIR, keepTestData: false };
  for (let i = 2; i < argv.length; i++) {
    if (argv[i] === '--out-dir' && argv[i + 1]) {
      args.outDir = path.resolve(argv[++i]);
    } else if (argv[i] === '--keep-test-data') {
      args.keepTestData = true;
    }
  }
  return args;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function getFreePort(exclude = new Set([8765, 8866])) {
  for (let i = 0; i < 40; i++) {
    const port = await new Promise((resolve, reject) => {
      const srv = net.createServer();
      srv.unref();
      srv.on('error', reject);
      srv.listen(0, '127.0.0.1', () => {
        const p = srv.address().port;
        srv.close(() => resolve(p));
      });
    });
    if (!exclude.has(port)) return port;
  }
  throw new Error('Failed to find free port');
}

async function startStudioServer(port) {
  const logPath = path.join(os.tmpdir(), `cineforge_ui_server_${port}.log`);
  const logFd = fs.openSync(logPath, 'w');
  const proc = spawn('python3', [path.join(STUDIO_DIR, 'server.py'), '--host', '127.0.0.1', '--port', String(port)], {
    cwd: ROOT,
    stdio: ['ignore', logFd, logFd],
  });

  const deadline = Date.now() + 45_000;
  while (Date.now() < deadline) {
    if (proc.exitCode !== null) {
      const log = fs.readFileSync(logPath, 'utf8');
      throw new Error(`studio/server.py exited early (${proc.exitCode}):\n${log}`);
    }
    try {
      const res = await fetch(`http://127.0.0.1:${port}/api/health`);
      if (res.ok) {
        const data = await res.json();
        if (data.ok) return { proc, logPath, logFd };
      }
    } catch {
      // retry
    }
    await sleep(300);
  }
  const log = fs.readFileSync(logPath, 'utf8');
  proc.kill('SIGKILL');
  throw new Error(`studio/server.py health timeout:\n${log}`);
}

async function launchChrome() {
  const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'cineforge-chrome-'));
  const xdgConfig = path.join(userDataDir, 'config');
  const xdgCache = path.join(userDataDir, 'cache');
  fs.mkdirSync(xdgConfig, { recursive: true });
  fs.mkdirSync(xdgCache, { recursive: true });
  const fontConfPath = path.join(userDataDir, 'fonts.conf');
  const userFonts = path.join(os.homedir(), '.local', 'share', 'fonts');
  fs.writeFileSync(
    fontConfPath,
    `<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">
<fontconfig>
  <dir>/usr/share/fonts</dir>
  <dir>${userFonts}</dir>
  <cachedir>${path.join(userDataDir, 'fc-cache')}</cachedir>
</fontconfig>\n`,
    'utf8'
  );
  const chromeArgs = [
    '--headless=new',
    '--no-sandbox',
    '--disable-setuid-sandbox',
    '--disable-gpu',
    '--disable-dev-shm-usage',
    '--disable-crash-reporter',
    '--disable-breakpad',
    '--no-first-run',
    '--no-default-browser-check',
    '--remote-debugging-port=0',
    '--window-size=1440,900',
    '--force-device-scale-factor=1',
    '--autoplay-policy=no-user-gesture-required',
    `--user-data-dir=${userDataDir}`,
    'about:blank',
  ];
  const proc = spawn(CHROME_BIN, chromeArgs, {
    stdio: ['ignore', 'pipe', 'pipe'],
    env: {
      ...process.env,
      HOME: userDataDir,
      XDG_CONFIG_HOME: xdgConfig,
      XDG_CACHE_HOME: xdgCache,
      XDG_DATA_HOME: path.join(os.homedir(), '.local', 'share'),
      FONTCONFIG_FILE: fontConfPath,
    },
  });

  const wsBrowserUrl = await new Promise((resolve, reject) => {
    let stderrBuf = '';
    const timer = setTimeout(() => {
      reject(new Error(`Chrome CDP startup timed out. stderr:\n${stderrBuf}`));
    }, 20_000);
    proc.stderr.on('data', (chunk) => {
      stderrBuf += chunk.toString('utf8');
      const m = stderrBuf.match(/DevTools listening on (ws:\/\/[^\s]+)/);
      if (m) {
        clearTimeout(timer);
        resolve(m[1]);
      }
    });
    proc.on('exit', (code) => {
      clearTimeout(timer);
      reject(new Error(`Chrome exited prematurely (${code}). stderr:\n${stderrBuf}`));
    });
  });

  const u = new URL(wsBrowserUrl);
  const debugOrigin = `http://${u.hostname}:${u.port}`;
  let target = null;
  for (let i = 0; i < 30; i++) {
    const listRes = await fetch(`${debugOrigin}/json/list`);
    const targets = await listRes.json();
    target = targets.find((t) => t.type === 'page' && t.webSocketDebuggerUrl);
    if (target) break;
    await sleep(150);
  }
  if (!target) throw new Error('No Chromium page target found');
  return { proc, userDataDir, pageWsUrl: target.webSocketDebuggerUrl };
}

class CDPClient {
  constructor(wsUrl) {
    this.wsUrl = wsUrl;
    this.nextId = 1;
    this.pending = new Map();
    this.listeners = new Map();
    this.consoleErrors = [];
    this.pageErrors = [];
    this.httpErrors = [];
    this.failedRequests = [];
  }

  async connect() {
    this.ws = new WebSocket(this.wsUrl);
    await new Promise((resolve, reject) => {
      this.ws.addEventListener('open', resolve, { once: true });
      this.ws.addEventListener('error', reject, { once: true });
    });

    this.ws.addEventListener('message', (evt) => {
      const msg = JSON.parse(String(evt.data));
      if (msg.id) {
        const entry = this.pending.get(msg.id);
        if (entry) {
          this.pending.delete(msg.id);
          if (msg.error) {
            entry.reject(new Error(`CDP ${entry.method}: ${JSON.stringify(msg.error)}`));
          } else {
            entry.resolve(msg.result || {});
          }
        }
      } else if (msg.method) {
        this._handleEvent(msg.method, msg.params || {});
      }
    });

    await this.send('Page.enable');
    await this.send('Runtime.enable');
    await this.send('Network.enable');
    await this.send('Log.enable');
    await this.send('Emulation.setDeviceMetricsOverride', {
      width: 1440,
      height: 900,
      deviceScaleFactor: 1,
      mobile: false,
    });
  }

  _handleEvent(method, params) {
    if (method === 'Runtime.consoleAPICalled' && params.type === 'error') {
      const text = (params.args || [])
        .map((a) => a.value ?? a.description ?? '')
        .join(' ');
      this.consoleErrors.push(text);
    } else if (method === 'Runtime.exceptionThrown') {
      const desc =
        params.exceptionDetails?.exception?.description ||
        params.exceptionDetails?.text ||
        JSON.stringify(params.exceptionDetails);
      this.pageErrors.push(desc);
    } else if (method === 'Log.entryAdded' && params.entry?.level === 'error') {
      // Ignore duplicate network error already captured in httpErrors, still record
      const txt = `${params.entry.source || 'log'}: ${params.entry.text || ''}`;
      if (!txt.includes('Failed to load resource')) {
        this.consoleErrors.push(txt);
      }
    } else if (method === 'Network.responseReceived') {
      const status = params.response?.status ?? 0;
      const url = params.response?.url ?? '';
      if (status >= 400) {
        this.httpErrors.push({ status, url, type: params.type });
      }
    } else if (method === 'Network.loadingFailed') {
      if (!params.canceled && params.type !== 'Media' && params.type !== 'EventSource') {
        this.failedRequests.push({
          type: params.type,
          errorText: params.errorText,
        });
      }
    }
    const cbs = this.listeners.get(method);
    if (cbs) {
      for (const cb of cbs) cb(params);
    }
  }

  send(method, params = {}, timeoutMs = 20_000) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`CDP timeout on ${method}`));
      }, timeoutMs);
      this.pending.set(id, {
        method,
        resolve: (res) => {
          clearTimeout(timer);
          resolve(res);
        },
        reject: (err) => {
          clearTimeout(timer);
          reject(err);
        },
      });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  async evalJs(expression) {
    const res = await this.send('Runtime.evaluate', {
      expression,
      awaitPromise: true,
      returnByValue: true,
    });
    if (res.exceptionDetails) {
      throw new Error(
        `evalJs exception: ${res.exceptionDetails.exception?.description || res.exceptionDetails.text}`
      );
    }
    return res.result?.value;
  }

  async waitFor(predicateJs, label, timeoutMs = 15_000) {
    const deadline = Date.now() + timeoutMs;
    let lastVal = null;
    while (Date.now() < deadline) {
      lastVal = await this.evalJs(`(() => { return (${predicateJs}); })()`);
      if (lastVal) return lastVal;
      await sleep(200);
    }
    throw new Error(`Timed out waiting for ${label} (last=${JSON.stringify(lastVal)})`);
  }

  async navigate(url) {
    await this.send('Page.navigate', { url });
    await sleep(400);
  }

  async setHash(hash) {
    await this.evalJs(`window.location.hash = ${JSON.stringify(hash)}; window.scrollTo(0, 0);`);
    await sleep(500);
  }

  async waitImagesLoaded(timeoutMs = 12_000) {
    await this.waitFor(
      `(() => {
        const isVis = (img) => {
          const r = img.getBoundingClientRect();
          const st = getComputedStyle(img);
          if (r.width <= 0 || r.height <= 0 || st.visibility === 'hidden' || st.display === 'none') return false;
          if (img.loading === 'lazy') {
            if (r.bottom <= 0 || r.top >= window.innerHeight || r.right <= 0 || r.left >= window.innerWidth) return false;
            let p = img.parentElement;
            while (p && p !== document.body) {
              const ps = getComputedStyle(p);
              if (/(auto|scroll|hidden|clip)/.test(ps.overflowY + ' ' + ps.overflowX)) {
                const pr = p.getBoundingClientRect();
                if (r.bottom <= pr.top || r.top >= pr.bottom || r.right <= pr.left || r.left >= pr.right) return false;
              }
              p = p.parentElement;
            }
          }
          return true;
        };
        const imgs = [...document.querySelectorAll('img')].filter(isVis);
        if (imgs.length === 0) return true;
        return imgs.every((img) => img.complete && img.naturalWidth > 0);
      })()`,
      'all visible images loaded',
      timeoutMs
    );
  }

  async checkPageHealth(viewName) {
    const report = await this.evalJs(`(() => {
      const scrollW = document.documentElement.scrollWidth;
      const innerW = window.innerWidth;
      const isVis = (img) => {
        const r = img.getBoundingClientRect();
        const st = getComputedStyle(img);
        if (r.width <= 0 || r.height <= 0 || st.visibility === 'hidden' || st.display === 'none') return false;
        if (img.loading === 'lazy') {
          if (r.bottom <= 0 || r.top >= window.innerHeight || r.right <= 0 || r.left >= window.innerWidth) return false;
          let p = img.parentElement;
          while (p && p !== document.body) {
            const ps = getComputedStyle(p);
            if (/(auto|scroll|hidden|clip)/.test(ps.overflowY + ' ' + ps.overflowX)) {
              const pr = p.getBoundingClientRect();
              if (r.bottom <= pr.top || r.top >= pr.bottom || r.right <= pr.left || r.left >= pr.right) return false;
            }
            p = p.parentElement;
          }
        }
        return true;
      };
      const visibleImgs = [...document.querySelectorAll('img')].filter(isVis);
      const brokenImgs = visibleImgs
        .filter((img) => !img.complete || img.naturalWidth === 0)
        .map((img) => img.getAttribute('src') || img.src);
      return {
        hash: window.location.hash,
        scrollW,
        innerW,
        overflow: scrollW > innerW + 2,
        visibleImgCount: visibleImgs.length,
        brokenImgs,
        bodyTextLen: (document.body.innerText || '').trim().length,
      };
    })()`);

    const errors = [];
    if (report.overflow) {
      errors.push(`Horizontal overflow: scrollWidth=${report.scrollW} > innerWidth=${report.innerW}`);
    }
    if (report.brokenImgs.length > 0) {
      errors.push(`Broken visible images (${report.brokenImgs.length}): ${report.brokenImgs.join(', ')}`);
    }
    if (report.bodyTextLen < 40) {
      errors.push(`Page appears empty (bodyTextLen=${report.bodyTextLen})`);
    }
    if (this.consoleErrors.length > 0) {
      errors.push(`console.error: ${this.consoleErrors.join(' | ')}`);
    }
    if (this.pageErrors.length > 0) {
      errors.push(`pageerror: ${this.pageErrors.join(' | ')}`);
    }
    if (this.httpErrors.length > 0) {
      errors.push(`HTTP >= 400: ${JSON.stringify(this.httpErrors)}`);
    }
    if (this.failedRequests.length > 0) {
      errors.push(`Failed network requests: ${JSON.stringify(this.failedRequests)}`);
    }
    if (errors.length > 0) {
      throw new Error(`[${viewName}] health check failed:\n  - ${errors.join('\n  - ')}`);
    }
    console.log(
      `[OK] ${viewName} (${report.hash || '#'}) | viewport=${report.innerW}x900 scrollW=${report.scrollW} | imgs=${report.visibleImgCount} broken=0`
    );
    return report;
  }

  async capturePng(outPath) {
    fs.mkdirSync(path.dirname(outPath), { recursive: true });
    const { data } = await this.send('Page.captureScreenshot', {
      format: 'png',
      fromSurface: true,
    });
    fs.writeFileSync(outPath, Buffer.from(data, 'base64'));
    console.log(`[PNG] Saved ${outPath}`);
  }

  close() {
    try {
      this.ws?.close();
    } catch {
      // ignore
    }
  }
}

function cleanupUiTestData(createdProjectIds, testReviewerName) {
  const py = `
import shutil, sqlite3
from pathlib import Path
root = Path(${JSON.stringify(ROOT)})
studio = root / "studio"
db_path = studio / "data" / "studio.db"
pids = ${JSON.stringify([...createdProjectIds])}
reviewer = ${JSON.stringify(testReviewerName)}
for pid in pids:
    if not pid or not pid.startswith("studio_"):
        continue
    for d in (root / "workflows" / pid, root / "films" / pid, root / "assets" / pid, root / "videos" / pid):
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
    for folder in (studio / "data" / "previews", studio / "data" / "dispatch", studio / "data" / "thumbs"):
        if folder.exists():
            for item in folder.glob(f"*{pid}*"):
                if item.is_dir(): shutil.rmtree(item, ignore_errors=True)
                else: item.unlink(missing_ok=True)
if db_path.exists():
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    for tbl in tables:
        cols = [r[1] for r in cur.execute(f'PRAGMA table_info("{tbl}")').fetchall()]
        for pid in pids:
            if not pid.startswith("studio_"): continue
            if "id" in cols and tbl in ("projects", "studio_projects"):
                cur.execute(f'DELETE FROM "{tbl}" WHERE id = ?', (pid,))
            if "project_id" in cols:
                cur.execute(f'DELETE FROM "{tbl}" WHERE project_id = ?', (pid,))
        if "reviewer_name" in cols:
            cur.execute(f'DELETE FROM "{tbl}" WHERE reviewer_name = ?', (reviewer,))
    conn.commit()
    conn.close()
`;
  const res = spawnSync('python3', ['-c', py], { encoding: 'utf8' });
  if (res.status !== 0) {
    console.error('Cleanup warning:', res.stderr);
  }
}

async function main() {
  const args = parseArgs(process.argv);
  const port = await getFreePort();
  const baseUrl = `http://127.0.0.1:${port}`;
  const createdProjectIds = new Set();
  const UI_TEST_REVIEWER = '__ui_qa_reviewer__';

  let serverInfo = null;
  let chromeInfo = null;
  let cdp = null;

  try {
    console.log(`Starting studio/server.py on port ${port}...`);
    serverInfo = await startStudioServer(port);
    console.log('Launching headless Chromium at 1440x900...');
    chromeInfo = await launchChrome();
    cdp = new CDPClient(chromeInfo.pageWsUrl);
    await cdp.connect();

    // =========================================================================
    // 1. #discover (灵感广场) + External Share Modal + Guest Preview Toggle
    // =========================================================================
    await cdp.navigate(`${baseUrl}/#discover`);
    await cdp.waitFor(
      `document.querySelector('#app-main') && document.querySelectorAll('#app-main img').length >= 3`,
      'discover gallery rendered'
    );
    await cdp.waitImagesLoaded();

    // Toggle V2V comparison tabs
    const v2vToggleInfo = await cdp.evalJs(`(() => {
      const main = document.querySelector('#app-main');
      const classicBtns = [...main.querySelectorAll('[data-v2v-idx]')];
      if (classicBtns.length >= 2) classicBtns[1].click();
      const catBtn = main.querySelector('[data-v2v-mode="cat"]');
      const sbsBtn = main.querySelector('[data-v2v-mode="side_by_side"]');
      if (catBtn) catBtn.click();
      if (sbsBtn) sbsBtn.click();
      return {
        classicTabs: classicBtns.length,
        hasCatMode: Boolean(catBtn),
        hasSbsMode: Boolean(sbsBtn),
      };
    })()`);
    console.log('Discover V2V controls:', v2vToggleInfo);
    if (v2vToggleInfo.classicTabs < 2 || !v2vToggleInfo.hasCatMode || !v2vToggleInfo.hasSbsMode) {
      throw new Error(`Expected V2V classic tabs & mode toggles on #discover, got ${JSON.stringify(v2vToggleInfo)}`);
    }
    await sleep(700);
    await cdp.evalJs('window.scrollTo(0, 0)');
    await sleep(250);
    await cdp.checkPageHealth('01_discover');
    await cdp.capturePng(path.join(args.outDir, '01_discover.png'));

    // Test topbar Guest Preview toggle & External Share Modal (#16)
    const guestCheck = await cdp.evalJs(`(() => {
      const guestBtn = document.querySelector('#topbar-guest-toggle');
      if (!guestBtn) return { ok: false, reason: 'missing #topbar-guest-toggle' };
      const beforeGuest = document.body.classList.contains('is-guest-preview');
      guestBtn.click();
      const afterGuestOn = document.body.classList.contains('is-guest-preview');
      guestBtn.click();
      const afterGuestOff = document.body.classList.contains('is-guest-preview');
      return { ok: !beforeGuest && afterGuestOn && !afterGuestOff, beforeGuest, afterGuestOn, afterGuestOff };
    })()`);
    if (!guestCheck.ok) {
      throw new Error(`Guest Preview toggle failed: ${JSON.stringify(guestCheck)}`);
    }

    const shareOpen = await cdp.evalJs(`(async () => {
      const shareBtn = document.querySelector('#topbar-share-btn');
      if (!shareBtn) return { ok: false, reason: 'missing #topbar-share-btn' };
      shareBtn.click();
      await new Promise((r) => setTimeout(r, 400));
      const modal = document.querySelector('#share-modal');
      const modalVisible = Boolean(modal && !modal.hidden && getComputedStyle(modal).display !== 'none' && modal.getBoundingClientRect().height > 100);
      const modalText = modal ? modal.innerText : '';
      const hasPublicCmd = modalText.includes('--public') || modalText.includes('start.sh');
      const hasIpynbLink = Boolean(modal && modal.querySelector('a[href*="/api/farm/colab-notebook"]'));
      return { ok: modalVisible && hasPublicCmd && hasIpynbLink, modalVisible, hasPublicCmd, hasIpynbLink };
    })()`);
    if (!shareOpen.ok) {
      throw new Error(`External Share Modal open check failed: ${JSON.stringify(shareOpen)}`);
    }
    await cdp.capturePng(path.join(args.outDir, '08_external_share.png'));

    const shareClose = await cdp.evalJs(`(async () => {
      const modal = document.querySelector('#share-modal');
      const closeBtn = modal?.querySelector('[data-share-close], .modal-close, button[aria-label*="关闭"]') || modal?.querySelector('button');
      if (closeBtn) closeBtn.click();
      else document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
      await new Promise((r) => setTimeout(r, 250));
      const modalClosed = !modal || modal.hidden || getComputedStyle(modal).display === 'none' || !modal.classList.contains('open');
      return { ok: modalClosed };
    })()`);
    console.log('Shell External Share & Guest Preview check:', { guestCheck, shareOpen, shareClose });
    if (!shareClose.ok) {
      throw new Error(`External Share Modal close check failed: ${JSON.stringify(shareClose)}`);
    }

    // =========================================================================
    // 2. #create (创作台)
    // =========================================================================
    await cdp.setHash('#create');
    await cdp.waitFor(
      `document.querySelectorAll('#app-main [data-style-id]').length >= 2 && document.querySelector('#cr-title-input')`,
      'create view rendered'
    );
    await cdp.waitImagesLoaded();

    // Click a preset chip, click a style card, verify cost estimator updates
    const createPrep = await cdp.evalJs(`(() => {
      const main = document.querySelector('#app-main');
      const presetBtn = main.querySelector('[data-preset-id]');
      if (presetBtn) presetBtn.click();

      const styleCards = [...main.querySelectorAll('[data-style-id]')];
      if (styleCards.length >= 2) styleCards[1].click();

      const getEst = () => ({
        shots: main.querySelector('[data-est-shots]')?.textContent?.trim() || '',
        cost: main.querySelector('[data-est-cost]')?.textContent?.trim() || '',
      });
      const durBtns = [...main.querySelectorAll('[data-duration]')];
      const dur15 = main.querySelector('[data-duration="15"]');
      const dur180 = main.querySelector('[data-duration="180"]');
      const dur30 = main.querySelector('[data-duration="30"]');
      if (dur15) dur15.click();
      const est15 = getEst();
      if (dur180) dur180.click();
      const est180 = getEst();
      if (dur30) dur30.click();
      const est30 = getEst();

      return {
        clickedPreset: Boolean(presetBtn),
        styleCardCount: styleCards.length,
        durBtnCount: durBtns.length,
        est15,
        est180,
        est30,
        estimatorChanged: est15.shots !== est180.shots && est15.cost !== est180.cost,
      };
    })()`);
    console.log('Create interaction:', createPrep);
    if (createPrep.styleCardCount < 2) {
      throw new Error(`Expected >= 2 style cards on #create, got ${createPrep.styleCardCount}`);
    }
    if (!createPrep.estimatorChanged) {
      throw new Error(`Expected cost/shot estimator to update on #create: ${JSON.stringify(createPrep)}`);
    }
    await sleep(400);
    await cdp.evalJs('window.scrollTo(0, 0)');
    await sleep(250);
    await cdp.checkPageHealth('02_create');
    await cdp.capturePng(path.join(args.outDir, '02_create.png'));

    // Submit create form and verify navigation into #workflow/<newId>
    const clickedSubmit = await cdp.evalJs(`(() => {
      const submitBtn = document.querySelector('#cr-submit-btn');
      if (!submitBtn) return false;
      submitBtn.click();
      return true;
    })()`);
    if (!clickedSubmit) throw new Error('Could not find #cr-submit-btn on #create');

    await cdp.waitFor(
      `/^#workflow\\/studio_/.test(window.location.hash)`,
      'navigation to #workflow/studio_* after project creation',
      15_000
    );
    const createdHash = await cdp.evalJs('window.location.hash');
    const createdId = createdHash.replace(/^#workflow\//, '').split('?')[0];
    createdProjectIds.add(createdId);
    console.log(`[OK] Created project via UI -> ${createdHash} (id=${createdId})`);

    // =========================================================================
    // 3. #workflow/starcore (工作流看板 — Kanban + Shot Inspector)
    // =========================================================================
    await cdp.setHash('#workflow/starcore');
    await cdp.waitFor(
      `(() => {
        const main = document.querySelector('#app-main');
        if (!main) return false;
        const stages = main.querySelectorAll('.wf-stage-card').length;
        const cols = main.querySelectorAll('.wf-col').length;
        const cards = main.querySelectorAll('.wf-shot-card').length;
        return stages === 6 && cols === 4 && cards >= 3;
      })()`,
      'workflow kanban for starcore loaded (6 stages, 4 cols, >=3 shot cards)'
    );
    await cdp.waitImagesLoaded();
    // Regression guard: ensure Kanban shot cards are never flex-squished
    const cardGeom = await cdp.evalJs(`(() => {
      const cards = [...document.querySelectorAll('#app-main .wf-shot-card')].slice(0, 5);
      const heights = cards.map((c) => Math.round(c.getBoundingClientRect().height));
      return { count: cards.length, minHeight: Math.min(...heights), heights };
    })()`);
    console.log('Kanban card geometry:', cardGeom);
    if (cardGeom.count < 3 || cardGeom.minHeight < 120) {
      throw new Error(`Kanban shot cards appear squished (minHeight=${cardGeom.minHeight}): ${JSON.stringify(cardGeom)}`);
    }
    await sleep(400);
    await cdp.evalJs('window.scrollTo(0, 0)');
    await sleep(250);
    await cdp.checkPageHealth('03_workflow_kanban');
    await cdp.capturePng(path.join(args.outDir, '03_workflow_kanban.png'));

    // Open Shot Inspector drawer
    const openedDrawer = await cdp.evalJs(`(() => {
      const card = document.querySelector('#app-main .wf-shot-card[data-open-shot]');
      if (!card) return false;
      card.click();
      return true;
    })()`);
    if (!openedDrawer) throw new Error('Could not click a .wf-shot-card to open Shot Inspector');

    await cdp.waitFor(
      `(() => {
        const drawer = document.querySelector('.wf-drawer[data-drawer-panel]');
        if (!drawer) return false;
        const r = drawer.getBoundingClientRect();
        return r.width > 240 && r.height > 300;
      })()`,
      'shot inspector drawer visible'
    );
    await cdp.waitImagesLoaded();
    await sleep(450);
    await cdp.checkPageHealth('04_shot_inspector');
    await cdp.capturePng(path.join(args.outDir, '04_shot_inspector.png'));

    // Close drawer before switching to DAG view
    await cdp.evalJs(`(() => {
      const closeBtn = document.querySelector('.wf-drawer [data-close-drawer]');
      if (closeBtn) closeBtn.click();
    })()`);
    await sleep(300);

    // =========================================================================
    // 4. #workflow/starcore — DAG View
    // =========================================================================
    const clickedDag = await cdp.evalJs(`(() => {
      const dagBtn = document.querySelector('#app-main [data-switch-view="dag"]');
      if (!dagBtn) return false;
      dagBtn.click();
      return true;
    })()`);
    if (!clickedDag) throw new Error('Could not find DAG view tab on #workflow');

    await cdp.waitFor(
      `(() => {
        const svg = document.querySelector('#app-main [data-dag-svg]');
        const paths = svg ? svg.querySelectorAll('path').length : 0;
        const nodes = document.querySelectorAll('#app-main .dag-node').length;
        return paths >= 5 && nodes === 6;
      })()`,
      'DAG SVG edges & 6 nodes rendered'
    );
    await sleep(450);
    await cdp.evalJs('window.scrollTo(0, 0)');
    await sleep(250);
    await cdp.checkPageHealth('05_workflow_dag');
    await cdp.capturePng(path.join(args.outDir, '05_workflow_dag.png'));

    // =========================================================================
    // 5. #farm (算力工坊)
    // =========================================================================
    await cdp.setHash('#farm');
    await cdp.waitFor(
      `(() => {
        const main = document.querySelector('#app-main');
        return Boolean(main?.querySelector('[data-view="farm"]')) && main.querySelectorAll('.fe-kpi-card').length === 4;
      })()`,
      'compute farm view loaded'
    );

    const farmToggle = await cdp.evalJs(`(() => {
      const main = document.querySelector('#app-main');
      const btns = [...main.querySelectorAll('#fe-cost-tabs [data-tier-key]')];
      if (btns.length < 2) return { count: btns.length, changed: false };
      btns[0].click();
      const firstAmt = main.querySelector('.fe-savings-amount')?.textContent?.trim() || '';
      btns[btns.length - 1].click();
      const lastAmt = main.querySelector('.fe-savings-amount')?.textContent?.trim() || '';

      // Incremental checks (#16): SVG telemetry chart & .ipynb download link
      const ipynbLink = main.querySelector('a[href*="/api/farm/colab-notebook"]');
      const chartSvg = [...main.querySelectorAll('svg')].find((s) => {
        const r = s.getBoundingClientRect();
        return r.width >= 200 && r.height >= 80 && s.querySelectorAll('path, polyline, circle').length >= 3;
      });
      return {
        count: btns.length,
        firstAmt,
        lastAmt,
        changed: firstAmt !== lastAmt,
        hasIpynbDownload: Boolean(ipynbLink),
        hasTelemetrySvg: Boolean(chartSvg),
      };
    })()`);
    console.log('Farm cost calculator & EasyColab checks:', farmToggle);
    if (farmToggle.count < 2 || !farmToggle.changed) {
      throw new Error(`Farm cost calculator toggle check failed: ${JSON.stringify(farmToggle)}`);
    }
    if (!farmToggle.hasIpynbDownload || !farmToggle.hasTelemetrySvg) {
      throw new Error(`Farm EasyColab checks failed (ipynb/SVG telemetry chart): ${JSON.stringify(farmToggle)}`);
    }
    await sleep(400);
    await cdp.evalJs('window.scrollTo(0, 0)');
    await sleep(250);
    await cdp.checkPageHealth('06_compute_farm');
    await cdp.capturePng(path.join(args.outDir, '06_compute_farm.png'));

    // =========================================================================
    // 6. #eval (评测中心)
    // =========================================================================
    await cdp.setHash('#eval');
    await cdp.waitFor(
      `Boolean(document.querySelector('#fe-eval-form') && document.querySelector('#fe-reviewer-name'))`,
      'evaluation center loaded'
    );

    const evalSubmit = await cdp.evalJs(`(() => {
      const nameInput = document.querySelector('#fe-reviewer-name');
      if (nameInput) {
        nameInput.value = ${JSON.stringify(UI_TEST_REVIEWER)};
        nameInput.dispatchEvent(new Event('input', { bubbles: true }));
      }
      const roleBtns = [...document.querySelectorAll('#fe-role-pills .fe-role-pill')];
      if (roleBtns.length >= 2) roleBtns[1].click();

      const rows = [...document.querySelectorAll('#fe-stars-group .fe-star-row')];
      let clickedStars = 0;
      for (const row of rows) {
        const star5 = row.querySelector('.fe-star-btn[data-score="5"]');
        if (star5) {
          star5.click();
          clickedStars++;
        }
      }
      const textarea = document.querySelector('#fe-comment');
      if (textarea) {
        textarea.value = '自动化 UI 评测验证：界面高级暗黑电影质感，三分钟上手零门槛！';
        textarea.dispatchEvent(new Event('input', { bubbles: true }));
      }
      const submitBtn = document.querySelector('#fe-submit-eval');
      if (submitBtn) submitBtn.click();
      return { hasName: Boolean(nameInput), rows: rows.length, clickedStars, submitted: Boolean(submitBtn) };
    })()`);
    console.log('Eval submit:', evalSubmit);
    if (!evalSubmit.submitted || evalSubmit.clickedStars < 4) {
      throw new Error(`Could not submit evaluation form on #eval: ${JSON.stringify(evalSubmit)}`);
    }

    await cdp.waitFor(
      `(document.querySelector('#app-main')?.innerText || '').includes(${JSON.stringify(UI_TEST_REVIEWER)})`,
      'new review visible on evaluation wall',
      10_000
    );
    await sleep(400);
    await cdp.evalJs('window.scrollTo(0, 0)');
    await sleep(250);
    await cdp.checkPageHealth('07_beta_eval');
    await cdp.capturePng(path.join(args.outDir, '07_beta_eval.png'));

    console.log('\nALL 7 UI VIEWS & INTERACTIONS VERIFIED WITH ZERO ERRORS!');
  } finally {
    cdp?.close();
    if (chromeInfo) {
      chromeInfo.proc.kill('SIGKILL');
      fs.rmSync(chromeInfo.userDataDir, { recursive: true, force: true });
    }
    if (serverInfo) {
      serverInfo.proc.kill('SIGTERM');
      await sleep(500);
      if (serverInfo.proc.exitCode === null) serverInfo.proc.kill('SIGKILL');
      try {
        fs.closeSync(serverInfo.logFd);
      } catch {
        // ignore
      }
      fs.rmSync(serverInfo.logPath, { force: true });
    }
    if (!args.keepTestData) {
      cleanupUiTestData(createdProjectIds, UI_TEST_REVIEWER);
    }
  }
}

main().catch((err) => {
  console.error('\n[FAIL] UI verification failed:\n', err);
  process.exit(1);
});
