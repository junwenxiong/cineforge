#!/usr/bin/env node
/**
 * Product-Level Real Browser UX & Visual Verification Suite (Node v24 + Chromium CDP)
 * Verifies the simplified Kling/Hailuo/SwarmUI-style CineForge Studio product end-to-end:
 *   1. First-time novice (Colab offline, 1440x900): bare / -> #studio, 3-tab topbar,
 *      1-click sample -> Generate (stays on page) -> live 4-step progress + honest offline banner
 *      + playable local preview MP4 + expandable sanitized logs + zero emoji tofu glyphs.
 *   2. Real Colab online flow (isolated farm_server + heartbeat + mock H3 & V2V workers):
 *      topbar live pill "Colab 在线 (1 GPU)" -> #farm live GPU & logs -> H3 5s clip 0%->100%
 *      -> playable Colab final MP4 -> V2V real PNG+MP4 upload -> clean vs side_by_side toggle.
 *   3. Lite ComfyUI #workflow view: auto-selects user's project, renders SVG wires & nodes.
 *   4. Edge cases & 390x844 mobile layout: invalid .txt upload reject, cancel task, 0 overflow.
 */

import { spawn, spawnSync } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const ROOT = path.resolve(__dirname, '..', '..');
const STUDIO_DIR = path.join(ROOT, 'studio');
const FARM_SERVER = fs.existsSync(path.join(ROOT, 'tools', 'film', 'farm_server.py'))
  ? path.join(ROOT, 'tools', 'film', 'farm_server.py')
  : path.join(ROOT, 'automation', 'film', 'farm_server.py');
const STUDIO_SERVER = path.join(STUDIO_DIR, 'server.py');

const OUT_DIR = process.env.CINEFORGE_PRODUCT_UX_DIR || path.join(os.tmpdir(), 'cineforge-product-ux');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const EMOJI_RE = /[\u{1F300}-\u{1FAFF}]/u;

function findChromeBinary() {
  if (process.env.CHROME_BIN && fs.existsSync(process.env.CHROME_BIN)) return process.env.CHROME_BIN;
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
  throw new Error('Chromium binary not found');
}

const CHROME_BIN = findChromeBinary();

function cleanEnv(extra = {}) {
  const env = { ...process.env, ...extra };
  for (const k of ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']) {
    delete env[k];
  }
  env.NO_PROXY = '127.0.0.1,localhost';
  env.no_proxy = '127.0.0.1,localhost';
  return env;
}

async function getFreePort(exclude = new Set([8765, 8866])) {
  for (let i = 0; i < 60; i++) {
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
  throw new Error('Unable to allocate free port');
}

async function waitHttp(url, timeoutMs = 25_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const r = await fetch(url);
      if (r.ok) return await r.text();
    } catch {
      // retry
    }
    await sleep(250);
  }
  throw new Error(`Timed out waiting for ${url}`);
}

function genPng(outPath, color = '#f59e0b') {
  const res = spawnSync(
    'ffmpeg',
    ['-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', `color=c=${color}:s=320x240`, '-frames:v', '1', outPath],
    { encoding: 'utf8' }
  );
  if (res.status !== 0) throw new Error(`ffmpeg png failed: ${res.stderr}`);
  return outPath;
}

function genMotionMp4(outPath, bg = '#1d4ed8', box = '#fbbf24', dur = 2.0, freq = 330) {
  const vf = `drawbox=x=40:y=60:w=160:h=120:color=${box}:t=fill,hue=h=360*t`;
  const res = spawnSync(
    'ffmpeg',
    [
      '-hide_banner', '-loglevel', 'error', '-y',
      '-f', 'lavfi', '-t', String(dur), '-i', `color=c=${bg}:s=640x480:r=24`,
      '-f', 'lavfi', '-t', String(dur), '-i', `sine=frequency=${freq}:sample_rate=44100`,
      '-vf', vf,
      '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
      '-c:a', 'aac', '-ar', '44100', '-ac', '2', '-shortest',
      outPath,
    ],
    { encoding: 'utf8' }
  );
  if (res.status !== 0) throw new Error(`ffmpeg mp4 failed: ${res.stderr}`);
  return fs.readFileSync(outPath);
}

function startMockColabWorker(farmPort, farmToken, tmpDir) {
  let stopped = false;
  let paused = false;
  let seq = 0;

  const loop = (async () => {
    while (!stopped) {
      try {
        // Send real heartbeat so farm_server /status reports live NVIDIA A100 GPU
        await fetch(
          `http://127.0.0.1:${farmPort}/heartbeat?t=${encodeURIComponent(farmToken)}&w=colab_a100_01`,
          {
            method: 'POST',
            body: JSON.stringify({ state: paused ? 'idle' : 'online', gpu: 'NVIDIA A100-SXM4-80GB', engine: 'H3 / LTX-2.5' }),
          }
        );

        if (!paused) {
          // 1. Poll H3
          const clRes = await fetch(
            `http://127.0.0.1:${farmPort}/claim?t=${encodeURIComponent(farmToken)}&w=colab_a100_01&films=studio`,
            { method: 'POST', body: '{}' }
          );
          if (clRes.status === 200) {
            const job = await clRes.json();
            const clip = genMotionMp4(path.join(tmpDir, `h3_${job.id}.mp4`), '#0284c7', 'yellow', 1.8, 360 + seq++ * 40);
            const meta = encodeURIComponent(JSON.stringify({ wall_sec: 1.9 }));
            await fetch(
              `http://127.0.0.1:${farmPort}/result/${encodeURIComponent(job.id)}?t=${encodeURIComponent(farmToken)}&w=colab_a100_01&meta=${meta}`,
              { method: 'POST', body: clip }
            );
            continue;
          }

          // 2. Poll V2V
          const v2vRes = await fetch(
            `http://127.0.0.1:${farmPort}/lab/jobs?m=v2v_studio&t=${encodeURIComponent(farmToken)}&w=colab_a100_01`
          );
          if (v2vRes.ok) {
            const jobs = await v2vRes.json();
            if (Array.isArray(jobs) && jobs.length > 0) {
              for (const j of jobs) {
                if (stopped || paused) break;
                const catBytes = genMotionMp4(path.join(tmpDir, `cat_${j.id}.mp4`), '#f59e0b', '#78350f', 1.5, 480);
                await fetch(
                  `http://127.0.0.1:${farmPort}/lab/upload/v2v_studio/${encodeURIComponent(j.id)}.mp4?t=${encodeURIComponent(farmToken)}&w=colab_a100_01`,
                  { method: 'POST', body: catBytes }
                );
              }
              continue;
            }
          }
        }
      } catch {
        // ignore during shutdown
      }
      await sleep(300);
    }
  })();

  return {
    setPaused(v) { paused = Boolean(v); },
    async stop() { stopped = true; await loop.catch(() => {}); },
  };
}

class CDP {
  constructor(ws) {
    this.ws = ws;
    this.nextId = 1;
    this.pending = new Map();
    this.consoleErrors = [];
    this.pageErrors = [];
    this.httpErrors = [];
    this.failedRequests = [];
    this._reqUrls = new Map();

    ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(String(ev.data));
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (msg.error) reject(new Error(`${msg.error.code}: ${msg.error.message}`));
        else resolve(msg.result);
        return;
      }
      if (msg.method === 'Runtime.consoleAPICalled' && msg.params?.type === 'error') {
        const txt = (msg.params.args || []).map((a) => a.value ?? a.description ?? '').join(' ');
        if (txt && !txt.includes('status of 400')) this.consoleErrors.push(txt);
      } else if (msg.method === 'Runtime.exceptionThrown') {
        const d = msg.params?.exceptionDetails;
        this.pageErrors.push(d?.exception?.description || d?.text || 'Uncaught exception');
      } else if (msg.method === 'Network.requestWillBeSent') {
        this._reqUrls.set(msg.params.requestId, msg.params.request.url);
      } else if (msg.method === 'Network.responseReceived') {
        const { response } = msg.params;
        if (response.status >= 400 && !response.url.includes('/api/uploads')) {
          this.httpErrors.push({ status: response.status, url: response.url });
        }
      } else if (msg.method === 'Network.loadingFailed') {
        const { requestId, canceled, errorText } = msg.params;
        if (!canceled && errorText !== 'net::ERR_ABORTED') {
          this.failedRequests.push({ errorText, url: this._reqUrls.get(requestId) || requestId });
        }
      }
    });
  }

  static async launch(tmpDir) {
    const userDataDir = fs.mkdtempSync(path.join(tmpDir, 'chrome-'));
    const xdgConfig = path.join(userDataDir, 'config');
    const xdgCache = path.join(userDataDir, 'cache');
    fs.mkdirSync(xdgConfig, { recursive: true });
    fs.mkdirSync(xdgCache, { recursive: true });
    const fontConf = path.join(userDataDir, 'fonts.conf');
    const userFonts = path.join(os.homedir(), '.local', 'share', 'fonts');
    fs.writeFileSync(
      fontConf,
      `<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd"><fontconfig><dir>/usr/share/fonts</dir><dir>${userFonts}</dir><cachedir>${path.join(userDataDir, 'fc-cache')}</cachedir></fontconfig>\n`
    );
    const proc = spawn(
      CHROME_BIN,
      [
        '--headless=new', '--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu',
        '--disable-dev-shm-usage', '--no-first-run', '--no-default-browser-check',
        '--remote-debugging-port=0', '--window-size=1440,900', '--force-device-scale-factor=1',
        '--autoplay-policy=no-user-gesture-required', `--user-data-dir=${userDataDir}`, 'about:blank',
      ],
      {
        stdio: ['ignore', 'pipe', 'pipe'],
        env: { ...cleanEnv(), HOME: userDataDir, XDG_CONFIG_HOME: xdgConfig, XDG_CACHE_HOME: xdgCache, FONTCONFIG_FILE: fontConf },
      }
    );

    const wsBrowserUrl = await new Promise((resolve, reject) => {
      let buf = '';
      const t = setTimeout(() => reject(new Error(`Chrome startup timeout:\n${buf}`)), 20_000);
      proc.stderr.on('data', (c) => {
        buf += c.toString('utf8');
        const m = buf.match(/DevTools listening on (ws:\/\/[^\s]+)/);
        if (m) { clearTimeout(t); resolve(m[1]); }
      });
    });

    const bWs = new WebSocket(wsBrowserUrl);
    await new Promise((res, rej) => {
      bWs.addEventListener('open', res, { once: true });
      bWs.addEventListener('error', rej, { once: true });
    });
    const browserCdp = new CDP(bWs);
    const u = new URL(wsBrowserUrl);

    const openIsolatedPage = async (url) => {
      const { browserContextId } = await browserCdp.send('Target.createBrowserContext', {});
      const { targetId } = await browserCdp.send('Target.createTarget', { url, browserContextId });
      const targets = await (await fetch(`http://127.0.0.1:${u.port}/json/list`)).json();
      const target = targets.find((t) => t.id === targetId);
      const ws = new WebSocket(target.webSocketDebuggerUrl);
      await new Promise((res, rej) => {
        ws.addEventListener('open', res, { once: true });
        ws.addEventListener('error', rej, { once: true });
      });
      const page = new CDP(ws);
      await page.send('Page.enable');
      await page.send('Runtime.enable');
      await page.send('Network.enable');
      await page.send('DOM.enable');
      return page;
    };

    return {
      openIsolatedPage,
      close() {
        try { bWs.close(); } catch {}
        try { proc.kill('SIGKILL'); } catch {}
      },
    };
  }

  send(method, params = {}, timeoutMs = 20_000) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      const t = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`CDP timeout on ${method}`));
      }, timeoutMs);
      this.pending.set(id, {
        resolve: (v) => { clearTimeout(t); resolve(v); },
        reject: (e) => { clearTimeout(t); reject(e); },
      });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  async evalJs(expr) {
    const r = await this.send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) {
      throw new Error(`JS error: ${r.exceptionDetails.exception?.description || r.exceptionDetails.text}`);
    }
    return r.result?.value;
  }

  async waitFor(predJs, label, timeoutMs = 25_000) {
    const deadline = Date.now() + timeoutMs;
    let last = null;
    while (Date.now() < deadline) {
      last = await this.evalJs(`(() => (${predJs}))()`);
      if (last) return last;
      await sleep(220);
    }
    throw new Error(`Timed out waiting for ${label} (last=${JSON.stringify(last)})`);
  }

  async setViewport(width, height, mobile = false) {
    await this.send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile });
    await sleep(250);
  }

  async setFileInput(selector, filePath) {
    const { root } = await this.send('DOM.getDocument', { depth: 1 });
    const { nodeId } = await this.send('DOM.querySelector', { nodeId: root.nodeId, selector });
    if (!nodeId) throw new Error(`File input not found: ${selector}`);
    await this.send('DOM.setFileInputFiles', { nodeId, files: [filePath] });
  }

  async checkHealth(label, { checkNoEmoji = true } = {}) {
    const rep = await this.evalJs(`(() => {
      const text = document.body.innerText || '';
      const imgs = [...document.querySelectorAll('img')].filter((im) => {
        const r = im.getBoundingClientRect();
        const st = getComputedStyle(im);
        return r.width > 0 && r.height > 0 && st.display !== 'none' && st.visibility !== 'hidden' && im.loading !== 'lazy';
      });
      return {
        scrollW: document.documentElement.scrollWidth,
        innerW: window.innerWidth,
        brokenImgs: imgs.filter((im) => !im.complete || im.naturalWidth === 0).map((im) => im.src),
        textLen: text.trim().length,
        text,
      };
    })()`);
    const errs = [];
    if (rep.scrollW > rep.innerW + 2) errs.push(`Horizontal overflow: ${rep.scrollW} > ${rep.innerW}`);
    if (rep.brokenImgs.length > 0) errs.push(`Broken images: ${rep.brokenImgs.join(', ')}`);
    if (rep.textLen < 30) errs.push(`Empty page (${rep.textLen} chars)`);
    if (checkNoEmoji && EMOJI_RE.test(rep.text)) {
      const m = rep.text.match(EMOJI_RE);
      errs.push(`Found raw emoji glyph that renders as tofu on Linux: ${JSON.stringify(m?.[0])}`);
    }
    if (this.consoleErrors.length) errs.push(`consoleErrors: ${this.consoleErrors.join(' | ')}`);
    if (this.pageErrors.length) errs.push(`pageErrors: ${this.pageErrors.join(' | ')}`);
    if (this.httpErrors.length) errs.push(`httpErrors: ${JSON.stringify(this.httpErrors)}`);
    if (this.failedRequests.length) errs.push(`failedRequests: ${JSON.stringify(this.failedRequests)}`);
    if (errs.length) throw new Error(`[${label}] health failed:\n  - ${errs.join('\n  - ')}`);
    console.log(`[OK] ${label} | ${rep.innerW}px scrollW=${rep.scrollW} | brokenImgs=0`);
    return rep;
  }

  async shot(name) {
    fs.mkdirSync(OUT_DIR, { recursive: true });
    const p = path.join(OUT_DIR, name);
    const { data } = await this.send('Page.captureScreenshot', { format: 'png', fromSurface: true });
    fs.writeFileSync(p, Buffer.from(data, 'base64'));
    console.log(`[PNG] ${p}`);
    return p;
  }

  close() {
    try { this.ws.close(); } catch {}
  }
}

function cleanupProjects(pids, initialUploads) {
  const py = `
import shutil
from pathlib import Path
root = Path(${JSON.stringify(ROOT)})
studio = root / "studio"
pids = ${JSON.stringify([...pids])}
keep_uploads = set(${JSON.stringify([...initialUploads])})
for pid in pids:
    if not pid or not pid.startswith("studio_"):
        continue
    for p in (root / "workflows" / pid, root / "films" / pid, root / "assets" / pid, root / "videos" / pid):
        shutil.rmtree(p, ignore_errors=True)
    for d in (studio / "data" / "previews", studio / "data" / "dispatch", studio / "data" / "thumbs"):
        if d.is_dir():
            for f in d.glob(f"*{pid}*"):
                shutil.rmtree(f, ignore_errors=True) if f.is_dir() else f.unlink(missing_ok=True)
    for p in (root / "renders").glob(f"{pid}*"):
        shutil.rmtree(p, ignore_errors=True)
    v2v_dir = root / "renders" / "lab" / "v2v_studio"
    if v2v_dir.is_dir():
        for f in v2v_dir.glob(f"{pid}*"):
            f.unlink(missing_ok=True)
uploads = studio / "data" / "uploads"
if uploads.is_dir():
    for f in uploads.iterdir():
        if f.is_file() and f.name not in keep_uploads:
            f.unlink(missing_ok=True)
`;
  spawnSync('python3', ['-c', py], { encoding: 'utf8' });
}

async function run() {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const uploadsDir = path.join(STUDIO_DIR, 'data', 'uploads');
  const initialUploads = new Set(fs.existsSync(uploadsDir) ? fs.readdirSync(uploadsDir) : []);
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'cineforge_prod_ux_'));
  const offlineFarmDir = path.join(tmpDir, 'farm_offline');
  const onlineFarmDir = path.join(tmpDir, 'farm_online');
  fs.mkdirSync(offlineFarmDir, { recursive: true });
  fs.mkdirSync(onlineFarmDir, { recursive: true });

  const farmPort = await getFreePort(new Set([8765, 8866]));
  const offlineFarmPort = await getFreePort(new Set([8765, 8866, farmPort]));
  const offlineStudioPort = await getFreePort(new Set([8765, 8866, farmPort, offlineFarmPort]));
  const onlineStudioPort = await getFreePort(new Set([8765, 8866, farmPort, offlineFarmPort, offlineStudioPort]));

  const createdPids = new Set();
  const procs = [];
  let worker = null;
  let browser = null;

  try {
    // 1. Offline Studio Server (Colab not running)
    const offLog = fs.openSync(path.join(tmpDir, 'studio_offline.log'), 'w');
    const offProc = spawn(
      'python3',
      [STUDIO_SERVER, '--host', '127.0.0.1', '--port', String(offlineStudioPort), '--farm-port', String(offlineFarmPort)],
      {
        cwd: ROOT,
        stdio: ['ignore', offLog, offLog],
        env: cleanEnv({ STUDIO_FARM_DIR: offlineFarmDir, STUDIO_DB_PATH: path.join(tmpDir, 'offline.db') }),
      }
    );
    procs.push(offProc);
    await waitHttp(`http://127.0.0.1:${offlineStudioPort}/api/health`);

    // 2. Online Farm Server (writes token into onlineFarmDir/token so Studio detects real live GPUs)
    const farmLog = fs.openSync(path.join(tmpDir, 'farm_online.log'), 'w');
    const farmProc = spawn(
      'python3',
      [FARM_SERVER, '--port', String(farmPort), '--farm-dir', onlineFarmDir],
      { cwd: ROOT, stdio: ['ignore', farmLog, farmLog], env: cleanEnv() }
    );
    procs.push(farmProc);
    const tokenPath = path.join(onlineFarmDir, 'token');
    const tokDeadline = Date.now() + 15_000;
    while (!fs.existsSync(tokenPath) && Date.now() < tokDeadline) await sleep(150);
    const farmToken = fs.readFileSync(tokenPath, 'utf8').trim();
    await waitHttp(`http://127.0.0.1:${farmPort}/status?t=${encodeURIComponent(farmToken)}&w=probe`);

    // 3. Online Studio Server connected to onlineFarmPort
    const onLog = fs.openSync(path.join(tmpDir, 'studio_online.log'), 'w');
    const onProc = spawn(
      'python3',
      [STUDIO_SERVER, '--host', '127.0.0.1', '--port', String(onlineStudioPort), '--farm-port', String(farmPort)],
      {
        cwd: ROOT,
        stdio: ['ignore', onLog, onLog],
        env: cleanEnv({ STUDIO_FARM_DIR: onlineFarmDir, STUDIO_DB_PATH: path.join(tmpDir, 'online.db') }),
      }
    );
    procs.push(onProc);
    await waitHttp(`http://127.0.0.1:${onlineStudioPort}/api/health`);

    worker = startMockColabWorker(farmPort, farmToken, tmpDir);
    browser = await CDP.launch(tmpDir);

    // =========================================================================
    // SCENARIO 1: Novice First Launch (Colab Offline, 1440x900)
    // =========================================================================
    const pageOff = await browser.openIsolatedPage(`http://127.0.0.1:${offlineStudioPort}/`);
    await pageOff.setViewport(1440, 900, false);
    await pageOff.waitFor(`window.location.hash === '#studio' && Boolean(document.querySelector('#st-generate-btn'))`, 'bare URL lands on #studio');

    // Verify minimal 3-tab topbar + honest "Colab 未连接"
    const navCheck = await pageOff.evalJs(`(() => ({
      navCount: document.querySelectorAll('.topnav .topnav-item').length,
      hasSidebar: Boolean(document.querySelector('#app-sidebar')),
      statusText: document.querySelector('#topbar-farm-text')?.innerText?.trim() || '',
    }))()`);
    console.log('Topbar check (offline):', navCheck);
    if (navCheck.navCount !== 3 || navCheck.hasSidebar) {
      throw new Error(`Expected clean 3-tab topbar with no sidebar, got ${JSON.stringify(navCheck)}`);
    }
    if (!navCheck.statusText.includes('未连接')) {
      throw new Error(`Expected honest offline status pill, got: ${navCheck.statusText}`);
    }

    // 1 click quick prompt -> click Generate -> stay on #studio -> live progress + offline banner + preview MP4
    await pageOff.evalJs(`(() => {
      document.querySelector('[data-qp-id]')?.click();
      document.querySelector('#st-generate-btn').click();
    })()`);

    await pageOff.waitFor(`Boolean(document.querySelector('#st-live-card')) && Boolean(document.querySelector('#st-offline-banner'))`, 'live progress & honest offline banner');
    const stayedHash = await pageOff.evalJs(`window.location.hash`);
    if (stayedHash !== '#studio') throw new Error(`Generate should stay on #studio, jumped to ${stayedHash}`);

    // Wait for local preview MP4 to become playable in main player
    await pageOff.waitFor(
      `(() => {
        const v = document.querySelector('#st-main-video');
        return Boolean(v && v.src.includes('_preview.mp4') && v.readyState >= 1 && v.videoWidth > 0);
      })()`,
      'local preview MP4 playable in #st-main-video',
      20_000
    );
    const pidOff = await pageOff.evalJs(`document.querySelector('[data-task-id]')?.dataset.taskId || ''`);
    if (pidOff.startsWith('studio_')) createdPids.add(pidOff);

    // Open inline live log drawer
    await pageOff.evalJs(`document.querySelector('#st-toggle-logs')?.click()`);
    await pageOff.waitFor(`Boolean(document.querySelector('#st-log-panel'))`, 'live log panel opened');

    await pageOff.checkHealth('01_studio_novice_offline');
    await pageOff.shot('01_studio_novice_offline.png');

    // Edge case: reject invalid .txt upload
    const badTxt = path.join(tmpDir, 'bad.txt');
    fs.writeFileSync(badTxt, 'invalid');
    await pageOff.setFileInput('#st-img-input', badTxt);
    await pageOff.waitFor(`(document.querySelector('#toast-root')?.innerText || '').includes('JPG')`, 'invalid upload rejected');

    // Edge case: cancel queued offline task
    await pageOff.evalJs(`document.querySelector('#st-cancel-btn')?.click()`);
    await pageOff.waitFor(`(document.querySelector('#st-live-card')?.innerText || '').includes('已取消')`, 'task canceled cleanly');
    pageOff.close();

    // =========================================================================
    // SCENARIO 2: Real Online Colab GPU (Heartbeat + H3 + V2V + #farm + #workflow)
    // =========================================================================
    const pageOn = await browser.openIsolatedPage(`http://127.0.0.1:${onlineStudioPort}/#farm`);
    await pageOn.setViewport(1440, 900, false);
    await pageOn.waitFor(
      `(document.querySelector('#topbar-farm-text')?.innerText || '').includes('Colab 在线') && (document.body.innerText || '').includes('NVIDIA A100')`,
      'honest Colab Online (1 GPU) + A100 visible on #farm',
      15_000
    );
    const farmLinks = await pageOn.evalJs(`(() => ({
      openColab: document.querySelector('#fe-open-colab')?.getAttribute('href') || '',
      ipynb: document.querySelector('#fe-download-ipynb')?.getAttribute('href') || '',
    }))()`);
    if (!farmLinks.openColab.includes('colab.research.google.com') || !farmLinks.ipynb.includes('/api/farm/colab-notebook')) {
      throw new Error(`Missing Colab links on #farm: ${JSON.stringify(farmLinks)}`);
    }
    await pageOn.checkHealth('02_connect_colab_online');
    await pageOn.shot('02_connect_colab_online.png');

    // Navigate to #studio -> generate 5s H3 clip -> watch progress reach 100% & final MP4 play
    await pageOn.evalJs(`window.location.hash = '#studio';`);
    await pageOn.waitFor(`Boolean(document.querySelector('#st-generate-btn'))`, '#studio mounted');
    await pageOn.evalJs(`(() => {
      document.querySelector('[data-qp-id="qp_mecha"]')?.click();
      document.querySelector('[data-dur="5"]')?.click();
      document.querySelector('#st-generate-btn').click();
    })()`);

    await pageOn.waitFor(
      `(() => {
        const card = document.querySelector('#st-live-card');
        const v = document.querySelector('#st-main-video');
        return Boolean(card && card.innerText.includes('已完成') && card.innerText.includes('100%') && v && v.src.includes('_final.mp4') && v.readyState >= 1 && v.videoWidth > 0);
      })()`,
      'H3 Colab clip completed 100% and final MP4 playing',
      30_000
    );
    const pidH3 = await pageOn.evalJs(`document.querySelector('[data-task-id]')?.dataset.taskId || ''`);
    if (pidH3.startsWith('studio_')) createdPids.add(pidH3);
    await pageOn.checkHealth('03_studio_completed');
    await pageOn.shot('03_studio_completed.png');

    // Switch to V2V mode -> real PNG + MP4 upload -> wait for completion -> side-by-side toggle
    const catPng = genPng(path.join(tmpDir, 'cat_ref.png'), '#f59e0b');
    const srcMp4 = path.join(tmpDir, 'human_src.mp4');
    genMotionMp4(srcMp4, '#1d4ed8', '#38bdf8', 2.5, 260);

    await pageOn.evalJs(`document.querySelector('.st-mode-btn[data-mode="v2v"]')?.click()`);
    await pageOn.waitFor(`Boolean(document.querySelector('#st-img-input'))`, 'V2V mode inputs visible');
    await pageOn.evalJs(`document.querySelector('#st-clear-vid')?.click()`);
    await pageOn.waitFor(`Boolean(document.querySelector('#st-vid-input'))`, 'V2V video file input ready');

    await pageOn.setFileInput('#st-img-input', catPng);
    await pageOn.waitFor(`Boolean(document.querySelector('#st-clear-img'))`, 'cat PNG uploaded');
    await pageOn.setFileInput('#st-vid-input', srcMp4);
    await pageOn.waitFor(`Boolean(document.querySelector('#st-clear-vid'))`, 'human MP4 uploaded');

    await pageOn.evalJs(`document.querySelector('#st-generate-btn').click()`);
    await pageOn.waitFor(
      `(() => {
        const sbsBtn = document.querySelector('[data-pm="side_by_side"]');
        const v = document.querySelector('#st-main-video');
        return Boolean(sbsBtn && v && v.src.includes('_final.mp4') && v.readyState >= 1 && v.videoWidth > 0);
      })()`,
      'V2V final MP4 + side_by_side switch ready',
      35_000
    );
    const pidV2v = await pageOn.evalJs(`document.querySelector('[data-task-id]')?.dataset.taskId || ''`);
    if (pidV2v.startsWith('studio_')) createdPids.add(pidV2v);
    const cleanW = await pageOn.evalJs(`document.querySelector('#st-main-video').videoWidth`);
    await pageOn.evalJs(`document.querySelector('[data-pm="side_by_side"]').click()`);
    await pageOn.waitFor(
      `(() => {
        const v = document.querySelector('#st-main-video');
        return Boolean(v && v.src.includes('side_by_side') && v.readyState >= 1 && v.videoWidth > ${cleanW});
      })()`,
      'V2V side-by-side width doubled',
      15_000
    );
    await pageOn.checkHealth('04_studio_v2v_sbs');
    await pageOn.shot('04_studio_v2v_sbs.png');

    // =========================================================================
    // SCENARIO 3: Lite ComfyUI #workflow View (1440x900)
    // =========================================================================
    await pageOn.evalJs(`window.location.hash = '#workflow';`);
    await pageOn.waitFor(
      `(() => {
        const svg = document.querySelector('[data-comfy-svg]');
        const paths = svg ? svg.querySelectorAll('path').length : 0;
        const nodes = document.querySelectorAll('.cf-node').length;
        return paths >= 4 && nodes >= 5;
      })()`,
      'Lite ComfyUI workflow auto-loaded on #workflow',
      15_000
    );
    await pageOn.checkHealth('05_workflow_comfy');
    await pageOn.shot('05_workflow_comfy.png');

    // =========================================================================
    // SCENARIO 4: Mobile Responsive Check (390x844) across all 3 tabs
    // =========================================================================
    for (const [hash, label, shotName] of [
      ['#studio', 'mobile_studio', '06_mobile_studio.png'],
      ['#farm', 'mobile_farm', null],
      ['#workflow', 'mobile_workflow', null],
    ]) {
      await pageOn.setViewport(390, 844, true);
      await pageOn.evalJs(`window.location.hash = ${JSON.stringify(hash)}; window.scrollTo(0, 0);`);
      await sleep(700);
      await pageOn.checkHealth(label);
      if (shotName) await pageOn.shot(shotName);
    }

    pageOn.close();
    console.log('\nALL PRODUCT UX SCENARIOS PASSED WITH ZERO ERRORS, ZERO OVERFLOW, ZERO EMOJI TOFU!');
  } finally {
    if (worker) await worker.stop();
    if (browser) browser.close();
    for (const p of procs) { try { p.kill('SIGTERM'); } catch {} }
    await sleep(300);
    for (const p of procs) { if (p.exitCode === null) { try { p.kill('SIGKILL'); } catch {} } }
    cleanupProjects(createdPids, initialUploads);
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
}

run().catch((err) => {
  console.error('\n[FAIL] Product UX test failed:\n', err);
  process.exit(1);
});
