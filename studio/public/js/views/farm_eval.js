/**
 * CineForge Studio — Compute Farm Monitor (#farm) & White-Collar Beta Evaluation Hub (#eval)
 * Exports: renderFarm(container, ctx), renderEval(container, ctx), destroy()
 */

// ---------------------------------------------------------------------------
// Module Cleanup Registry
// ---------------------------------------------------------------------------

const _cleanups = [];

export function destroy() {
  while (_cleanups.length > 0) {
    const fn = _cleanups.pop();
    try {
      fn();
    } catch {
      // ignore cleanup error
    }
  }
}

function registerCleanup(fn) {
  if (typeof fn === 'function') _cleanups.push(fn);
}

// ---------------------------------------------------------------------------
// Helpers & Inline SVG Icons (Zero external CDN assets)
// ---------------------------------------------------------------------------

function safeEsc(ctx, value) {
  if (ctx && typeof ctx.escHtml === 'function') return ctx.escHtml(String(value ?? ''));
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function notify(ctx, msg, type = 'info') {
  if (ctx && typeof ctx.toast === 'function') {
    ctx.toast(msg, type);
  }
}

function goRoute(ctx, hash) {
  const normalized = hash.startsWith('#') ? hash : `#${hash}`;
  if (ctx && typeof ctx.navigate === 'function') {
    ctx.navigate(normalized);
  } else {
    window.location.hash = normalized;
  }
}

/**
 * Defense-in-depth client-side secret redaction for any log/snippet display.
 */
function redactSecrets(text) {
  return String(text ?? '')
    .replace(/\bhf_[A-Za-z0-9_-]{8,}\b/g, 'hf_***REDACTED***')
    .replace(/\bsk-[A-Za-z0-9_-]{8,}\b/g, 'sk-***REDACTED***')
    .replace(/https?:\/\/[A-Za-z0-9.-]*trycloudflare\.com[^\s"']*/gi, 'https://<your-tunnel>.example')
    .replace(/127\.0\.0\.1:41520\/c\/[^\s"']*/gi, '<local-canvas-redacted>');
}

async function copyText(text, successMsg, ctx) {
  const cleaned = redactSecrets(text);
  try {
    if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
      await navigator.clipboard.writeText(cleaned);
      notify(ctx, successMsg, 'success');
      return true;
    }
  } catch {
    // fallback below
  }
  try {
    const ta = document.createElement('textarea');
    ta.value = cleaned;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    ta.style.pointerEvents = 'none';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    notify(ctx, successMsg, 'success');
    return true;
  } catch {
    notify(ctx, '复制失败，请手动选中命令复制', 'error');
    return false;
  }
}

function formatNumber(n) {
  const num = Number(n);
  if (!Number.isFinite(num)) return '0';
  return num.toLocaleString('zh-CN');
}

function formatScore(n) {
  const num = Number(n);
  if (!Number.isFinite(num) || num <= 0) return '0.0';
  return num.toFixed(1);
}

function formatTimeLabel(raw) {
  if (!raw) return '刚刚';
  const str = String(raw).trim();
  const date = new Date(str.includes('T') ? str : str.replace(' ', 'T'));
  if (!Number.isNaN(date.getTime())) {
    const mm = String(date.getMonth() + 1).padStart(2, '0');
    const dd = String(date.getDate()).padStart(2, '0');
    const hh = String(date.getHours()).padStart(2, '0');
    const mi = String(date.getMinutes()).padStart(2, '0');
    return `${mm}-${dd} ${hh}:${mi}`;
  }
  return str.slice(0, 16);
}

const ICONS = {
  server: `<svg class="fe-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="6" rx="2"/><rect x="3" y="14" width="18" height="6" rx="2"/><circle cx="7" cy="7" r="1" fill="currentColor"/><circle cx="7" cy="17" r="1" fill="currentColor"/></svg>`,
  film: `<svg class="fe-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="16" rx="2.5"/><path d="M7 4v16M17 4v16M2 9h5M17 9h5M2 15h5M17 15h5"/></svg>`,
  coins: `<svg class="fe-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="10" r="6"/><path d="M14.8 9.2a6 6 0 1 1-4.8 9.5"/><path d="M9 7.5v5"/></svg>`,
  trending: `<svg class="fe-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 18 13.5 8.5 8.5 13.5 1 6"/><polyline points="17 18 23 18 23 12"/></svg>`,
  gpu: `<svg class="fe-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="5" width="14" height="14" rx="2"/><rect x="9" y="9" width="6" height="6" rx="1"/><path d="M9 1v4M15 1v4M9 19v4M15 19v4M1 9h4M1 15h4M19 9h4M19 15h4"/></svg>`,
  terminal: `<svg class="fe-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>`,
  shield: `<svg class="fe-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><polyline points="9 12 11 14 15 10"/></svg>`,
  copy: `<svg class="fe-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>`,
  check: `<svg class="fe-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`,
  refresh: `<svg class="fe-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>`,
  chevron: `<svg class="fe-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>`,
  star: `<svg viewBox="0 0 24 24"><path d="M12 2.4l2.92 5.92 6.53.95-4.72 4.6 1.11 6.5L12 17.3l-5.84 3.07 1.11-6.5-4.72-4.6 6.53-.95L12 2.4z"/></svg>`,
  spark: `<svg class="fe-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2l2.4 7.2L22 12l-7.6 2.8L12 22l-2.4-7.2L2 12l7.6-2.8L12 2z"/></svg>`,
  share: `<svg class="fe-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>`,
  arrowRight: `<svg class="fe-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>`,
  zap: `<svg class="fe-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>`,
  download: `<svg class="fe-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>`,
  activity: `<svg class="fe-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>`,
  clockShield: `<svg class="fe-icon fe-icon--lg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="M12 8v4l2.5 1.5"/></svg>`,
  hardDrive: `<svg class="fe-icon fe-icon--lg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="12" x2="2" y2="12"/><path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/><line x1="6" y1="16" x2="6.01" y2="16"/><line x1="10" y1="16" x2="10.01" y2="16"/></svg>`,
  chatCopy: `<svg class="fe-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>`,
};

// ---------------------------------------------------------------------------
// VIEW 1: CONNECT GOOGLE COLAB (#farm) — Honest 3-Step Setup, Live GPUs & Logs
// ---------------------------------------------------------------------------

function normalizeFarmData(raw, tasksSnap = null) {
  const d = raw && typeof raw === 'object' ? raw : {};
  const farmServerOnline = Boolean(d.farm_server_online ?? d.online ?? d.farm_online);
  const liveWorkers = Array.isArray(d.live_workers) ? d.live_workers : [];
  const colabConnected = Boolean(d.colab_connected ?? liveWorkers.length > 0);
  const onlineGpuCount = Number(d.online_gpu_count ?? liveWorkers.length ?? 0);
  const port = Number(d.port ?? d.farm_port ?? 8765);
  const startFarmCmd = String(d.start_farm_cmd || 'bash studio/start.sh --with-farm --port 8866');
  const openColabUrl =
    d.open_in_colab_url ||
    d.colab_guide?.open_in_colab_url ||
    'https://colab.research.google.com/github/junwenxiong/cineforge/blob/main/colab/CineForge_Colab_Worker.ipynb';
  const notebookUrl = d.colab_notebook_url || '/api/farm/colab-notebook';

  const rawLogs = Array.isArray(d.recent_logs)
    ? d.recent_logs
    : Array.isArray(d.activity)
      ? d.activity
      : [];
  const logs = rawLogs
    .slice(0, 40)
    .map((entry) => {
      if (typeof entry === 'string') {
        return { time: '', tag: 'FARM', level: 'info', message: redactSecrets(entry) };
      }
      return {
        time: entry.time || entry.timestamp || '',
        tag: String(entry.tag || entry.source || 'FARM').toUpperCase().slice(0, 10),
        level: String(entry.level || 'info').toLowerCase(),
        message: redactSecrets(entry.message || entry.text || entry.detail || ''),
      };
    })
    .filter((x) => x.message);

  const activeTasksCount = Number(tasksSnap?.active_count ?? 0);

  return {
    farmServerOnline,
    colabConnected,
    onlineGpuCount,
    liveWorkers,
    port,
    startFarmCmd,
    openColabUrl,
    notebookUrl,
    logs,
    activeTasksCount,
    securityNote:
      d.colab_guide?.security_note ||
      '所有 API Key 与 HF_TOKEN 仅保存在本机 .env（权限 600）或 Colab Secrets 中，不会写入笔记本或日志。',
  };
}

function renderColabContent(container, ctx, farm) {
  const esc = (v) => safeEsc(ctx, v);

  const workersHtml = farm.liveWorkers.length > 0
    ? farm.liveWorkers.map((w) => {
        const isBusy = w.status === 'busy';
        return `
          <div class="cf-colab-worker">
            <div class="cf-colab-worker-main">
              <div class="cf-colab-worker-name">${esc(w.gpu || 'Colab GPU')}</div>
              <div class="cf-colab-worker-sub mono">节点 ${esc(w.id)} · ${esc(w.engine || 'H3 / LTX-2.5')}</div>
            </div>
            <div class="cf-colab-worker-right">
              <span class="st-badge ${isBusy ? 'is-gold' : 'is-emerald'}">${isBusy ? '正在渲染' : '在线就绪'}</span>
              <span class="cf-colab-worker-seen">${esc(w.last_seen || '刚刚')}</span>
            </div>
          </div>
        `;
      }).join('')
    : `
      <div class="cf-colab-empty">
        暂未检测到在线 Colab GPU。完成第 1、2 步并运行 Colab 单元格后，GPU 节点会在几秒内自动出现在这里。
      </div>
    `;

  const logsHtml = farm.logs.length > 0
    ? farm.logs.map((item) => `
        <div class="st-log-line ${item.level === 'ok' ? 'is-ok' : item.level === 'error' ? 'is-error' : ''}">
          <span class="st-log-time">${esc(item.time || '--:--')}</span>
          <span class="st-log-tag">${esc(item.tag)}</span>
          <span>${esc(item.message)}</span>
        </div>
      `).join('')
    : `
      <div class="st-log-line">
        <span class="st-log-time">--:--</span>
        <span class="st-log-tag">READY</span>
        <span>暂无运行日志。启动派片服务并接入 Colab 后，模型加载、分镜渲染与回传日志会实时显示在这里。</span>
      </div>
    `;

  container.innerHTML = `
    <div class="cf-colab-page" data-view="farm">
      <header class="cf-colab-head">
        <div>
          <h1 class="cf-colab-title">连接 Google Colab 云端算力</h1>
          <p class="cf-colab-sub">
            所有视频模型（MiniMax-H3 开源4步 / LTX-2.5 / V2V 换角）都在 Colab GPU 运行，本机只提供 Web 界面与视频管理。
          </p>
        </div>
        <div class="cf-colab-head-actions">
          <button type="button" class="st-mini-btn" id="fe-farm-refresh">
            ${ICONS.refresh}
            <span>刷新状态</span>
          </button>
          <a href="#studio" class="st-mini-btn is-gold">返回生成视频</a>
        </div>
      </header>

      <!-- Honest Live Status Summary (3 Clear Indicators) -->
      <section class="cf-colab-status-grid" aria-label="实时连接状态">
        <div class="cf-colab-stat-card ${farm.farmServerOnline ? 'is-ok' : ''}">
          <span class="cf-colab-stat-label">本机派片服务 (:${esc(farm.port)})</span>
          <div class="cf-colab-stat-val">
            <span class="status-dot ${farm.farmServerOnline ? 'online' : 'muted'}"></span>
            <span>${farm.farmServerOnline ? '已启动运行中' : '未启动'}</span>
          </div>
        </div>

        <div class="cf-colab-stat-card ${farm.colabConnected ? 'is-ok' : ''}">
          <span class="cf-colab-stat-label">在线 Colab GPU</span>
          <div class="cf-colab-stat-val">
            <span class="status-dot ${farm.colabConnected ? 'online' : 'muted'}"></span>
            <span>${farm.colabConnected ? `${farm.onlineGpuCount} 台在线` : '0 台 · 未连接'}</span>
          </div>
        </div>

        <div class="cf-colab-stat-card">
          <span class="cf-colab-stat-label">当前队列任务</span>
          <div class="cf-colab-stat-val">
            <span class="status-dot ${farm.activeTasksCount > 0 ? 'gold' : 'muted'}"></span>
            <span>${farm.activeTasksCount} 个进行中 / 排队中</span>
          </div>
        </div>
      </section>

      <!-- Step 1 & Step 2 -->
      <section class="cf-colab-steps" aria-label="两步接入指南">
        <article class="st-card cf-colab-step-card">
          <div class="cf-colab-step-head">
            <span class="cf-colab-step-num">第 1 步</span>
            <h2 class="cf-colab-step-title">在本机同时启动 Web 界面与派片服务</h2>
            <span class="st-badge ${farm.farmServerOnline ? 'is-emerald' : ''}">
              ${farm.farmServerOnline ? '已完成' : '待启动'}
            </span>
          </div>
          <p class="cf-colab-step-desc">
            在项目目录运行下面这一行命令，终端会自动打开公网临时隧道并打印 <code>FARM_URL</code> 与 <code>FARM_TOKEN</code>：
          </p>
          <div class="cf-colab-cmd-row">
            <code class="mono" id="cf-start-cmd">${esc(farm.startFarmCmd)}</code>
            <button type="button" class="st-mini-btn" id="cf-copy-start-cmd">
              ${ICONS.copy}
              <span>复制命令</span>
            </button>
          </div>
        </article>

        <article class="st-card cf-colab-step-card">
          <div class="cf-colab-step-head">
            <span class="cf-colab-step-num">第 2 步</span>
            <h2 class="cf-colab-step-title">打开 Google Colab 笔记本并运行</h2>
            <span class="st-badge ${farm.colabConnected ? 'is-emerald' : 'is-cyan'}">
              ${farm.colabConnected ? '已接入 GPU' : '推荐 A100 / H100 / G4'}
            </span>
          </div>
          <p class="cf-colab-step-desc">
            在 Colab 顶部选择 GPU 运行时，把第 1 步终端打印的 <code>FARM_URL</code> 和 <code>FARM_TOKEN</code> 填进单元格 1，选好模型（MiniMax-H3 开源4步 / LTX-2.5 / V2V）后依次点击运行。队列空闲 15 分钟自动释放显卡防扣费。
          </p>
          <div class="cf-colab-btn-row">
            <a
              href="${esc(farm.openColabUrl)}"
              target="_blank"
              rel="noopener noreferrer"
              class="btn btn-primary"
              id="fe-open-colab"
            >
              一键在 Google Colab 打开
            </a>
            <a
              href="${esc(farm.notebookUrl)}"
              download="CineForge_Colab_Worker.ipynb"
              class="st-mini-btn"
              id="fe-download-ipynb"
              data-colab-notebook-download="true"
            >
              ${ICONS.download}
              <span>下载 .ipynb 文件</span>
            </a>
          </div>
        </article>
      </section>

      <!-- Step 3: Real Connected GPUs + Real-Time Sanitized Logs -->
      <section class="cf-colab-live-grid" aria-label="在线节点与实时日志">
        <article class="st-card">
          <div class="st-section-head">
            <div class="st-section-title">
              <span>在线 GPU 节点</span>
              <span class="st-count-pill">${farm.liveWorkers.length}</span>
            </div>
            <span class="st-label-hint">每 4 秒自动刷新</span>
          </div>
          <div class="cf-colab-worker-list">${workersHtml}</div>
        </article>

        <article class="st-card">
          <div class="st-section-head">
            <div class="st-section-title">
              <span>实时运行日志（已自动脱敏）</span>
            </div>
            <span class="st-badge is-emerald">零密钥保护</span>
          </div>
          <div class="st-log-panel cf-colab-log-box" role="log" aria-label="脱敏运行日志">
            ${logsHtml}
          </div>
        </article>
      </section>

      <div class="cf-colab-footnote">${esc(farm.securityNote)}</div>
    </div>
  `;

  container.querySelector('#cf-copy-start-cmd')?.addEventListener('click', () => {
    copyText(farm.startFarmCmd, '已复制启动命令', ctx);
  });

  const refreshBtn = container.querySelector('#fe-farm-refresh');
  refreshBtn?.addEventListener('click', async () => {
    refreshBtn.disabled = true;
    try {
      const [latest, snap] = await Promise.all([
        ctx.api.farmStatus(),
        ctx.api.tasks().catch(() => null),
      ]);
      ctx.store?.set?.('farmStatus', latest);
      if (snap) ctx.store?.set?.('liveTasks', snap);
      renderColabContent(container, ctx, normalizeFarmData(latest, snap));
      notify(ctx, '状态已刷新', 'success');
    } catch (err) {
      notify(ctx, `刷新失败：${err?.message || '请检查本地服务'}`, 'error');
      refreshBtn.disabled = false;
    }
  });
}

export async function renderFarm(container, ctx) {
  destroy();
  container.innerHTML = `
    <div class="cf-colab-page">
      <div class="skeleton" style="height:64px;border-radius:14px;"></div>
      <div class="skeleton" style="height:220px;border-radius:16px;"></div>
    </div>
  `;

  let alive = true;
  registerCleanup(() => { alive = false; });

  async function loadAndRender() {
    try {
      const [raw, snap] = await Promise.all([
        ctx.api.farmStatus(),
        ctx.api.tasks().catch(() => null),
      ]);
      if (!alive) return;
      ctx.store?.set?.('farmStatus', raw);
      if (snap) ctx.store?.set?.('liveTasks', snap);
      renderColabContent(container, ctx, normalizeFarmData(raw, snap));
    } catch {
      if (!alive) return;
      renderColabContent(container, ctx, normalizeFarmData({}, null));
    }
  }

  await loadAndRender();

  const timer = setInterval(() => {
    if (alive) loadAndRender();
  }, 4000);
  registerCleanup(() => clearInterval(timer));
}

// ---------------------------------------------------------------------------
// VIEW 2: WHITE-COLLAR BETA EVALUATION HUB (#eval)
// ---------------------------------------------------------------------------

const ROLE_OPTIONS = [
  '产品/运营',
  '市场/设计',
  '行政/HR',
  '开发/技术',
  '视频爱好者',
];

const RATING_DIMENSIONS = [
  { key: 'aesthetic', label: '画面审美', shortLabel: '审美', desc: '光影、构图与电影感是否达到可分享水准' },
  { key: 'consistency', label: '角色与口型一致性', shortLabel: '一致', desc: '主角长相、服装画风、动作与原声是否连贯' },
  { key: 'ease_of_use', label: '操作易懂程度', shortLabel: '易用', desc: '不看教程能否看懂工作流步骤并顺利上手' },
  { key: 'value', label: '低价/免费性价比', shortLabel: '性价比', desc: '对比商用平台价格与内测免费体验是否划算' },
];

const SCORE_TEXTS = {
  1: '1 分 · 需改进',
  2: '2 分 · 较一般',
  3: '3 分 · 还不错',
  4: '4 分 · 很顺手',
  5: '5 分 · 惊艳！',
};

const DEFAULT_MISSIONS = [
  {
    id: 'mission_opener',
    title: '15 秒周报 / 团建电影感开场',
    desc: '输入一句部门亮点或团建主题，一键拆出电影开场分镜，体验 1 分钟从想法到预演成片。',
    estTime: '约 2 分钟',
    difficulty: '零门槛',
    tip: '重点观察：操作流程是否无需专业提示词，生成分镜是否可直接复用。',
    route: '#create?preset=office_opener&mode=original',
  },
  {
    id: 'mission_classics_cat',
    title: '经典名场面一键变猫咪',
    desc: '在灵感广场对比《三国演义》《西游记》《红楼梦》真人变猫左右对照版，或直接做同款 V2V。',
    estTime: '约 2 分钟',
    difficulty: '零门槛',
    tip: '重点观察：原声口型同步、字幕自动抹除与猫爪防穿帮效果。',
    route: '#discover',
  },
  {
    id: 'mission_pet_scifi',
    title: '把自家宠物变成科幻主角',
    desc: '上传一张主子照片（或用预设猫咪参考图），生成专属太空/赛博微短剧分镜看板。',
    estTime: '约 3 分钟',
    difficulty: '零门槛',
    tip: '重点观察：多镜头下宠物外观锁定效果与 6 步可视化工作流清晰度。',
    route: '#create?preset=pet_scifi&mode=original',
  },
];

function resolveMissionRoute(m, fallbackRoute) {
  const direct = m.route || m.href || m.target_hash || m.action_url || m.target;
  if (typeof direct === 'string' && direct.trim()) {
    return direct.trim().startsWith('#') ? direct.trim() : `#${direct.trim()}`;
  }
  const preset = m.preset_id || m.preset || m.clone_id || m.clone;
  const mode = m.mode;
  if (preset) {
    const qs = new URLSearchParams();
    qs.set('preset', String(preset));
    qs.set('clone', String(preset));
    if (mode) qs.set('mode', String(mode));
    return `#create?${qs.toString()}`;
  }
  if (mode === 'v2v') return '#create?mode=v2v';
  return fallbackRoute;
}

function normalizeEvalData(raw) {
  const d = raw && typeof raw === 'object' ? raw : {};

  const rawMissions = Array.isArray(d.missions) && d.missions.length > 0 ? d.missions : DEFAULT_MISSIONS;
  const missions = rawMissions.slice(0, 3).map((m, idx) => {
    const fb = DEFAULT_MISSIONS[idx] || DEFAULT_MISSIONS[0];
    return {
      id: m.id || fb.id,
      title: m.title || fb.title,
      desc: m.desc || m.description || m.subtitle || fb.desc,
      estTime: m.est_time || m.estTime || m.duration_label || m.time_label || fb.estTime,
      difficulty: m.difficulty || m.level || m.badge || fb.difficulty,
      tip: m.tip || m.focus || m.check_tip || fb.tip,
      route: resolveMissionRoute(m, fb.route),
    };
  });

  const rawReviews = Array.isArray(d.reviews) ? d.reviews : [];
  const reviews = rawReviews.map((r, idx) => {
    const aesthetic = Number(r.aesthetic ?? r.score_aesthetic ?? 5) || 5;
    const consistency = Number(r.consistency ?? r.score_consistency ?? 5) || 5;
    const ease = Number(r.ease_of_use ?? r.score_ease_of_use ?? 5) || 5;
    const value = Number(r.value ?? r.score_value ?? 5) || 5;
    const overall = Number(r.overall) || Number(((aesthetic + consistency + ease + value) / 4).toFixed(1));
    const wouldShare = r.would_share !== undefined
      ? Boolean(r.would_share)
      : r.recommend !== undefined
        ? Boolean(r.recommend)
        : true;
    const reviewerName = String(r.reviewer_name || r.name || '匿名体验官').trim();
    const isSample = Boolean(r.is_sample || r.is_example || r.sample || /示例/.test(reviewerName));
    return {
      id: r.id ?? `rev-${idx}`,
      reviewer_name: reviewerName,
      role: String(r.role || '视频爱好者'),
      work_title: String(r.work_title || r.project_title || ''),
      project_id: String(r.project_id || ''),
      aesthetic,
      consistency,
      ease_of_use: ease,
      value,
      overall,
      would_share: wouldShare,
      comment: String(r.comment || r.feedback || '').trim(),
      created_at: r.created_at || '',
      is_sample: isSample,
    };
  });

  const s = d.summary || {};
  const count = Number(s.count ?? s.total ?? reviews.length) || 0;
  const avgAesthetic = Number(s.avg_aesthetic ?? 0);
  const avgConsistency = Number(s.avg_consistency ?? 0);
  const avgEase = Number(s.avg_ease_of_use ?? 0);
  const avgValue = Number(s.avg_value ?? 0);
  const overallCalc = count > 0
    ? ((avgAesthetic + avgConsistency + avgEase + avgValue) / 4)
    : 0;
  const avgOverall = Number(s.avg_overall ?? s.overall ?? overallCalc) || 0;
  let recommendRate = Number(s.recommend_rate ?? s.share_rate ?? 0);
  if (recommendRate > 0 && recommendRate <= 1) {
    recommendRate = Math.round(recommendRate * 100);
  } else {
    recommendRate = Math.round(recommendRate);
  }

  return {
    missions,
    reviews,
    summary: {
      count,
      avg_aesthetic: avgAesthetic,
      avg_consistency: avgConsistency,
      avg_ease_of_use: avgEase,
      avg_value: avgValue,
      avg_overall: avgOverall,
      recommend_rate: recommendRate,
    },
  };
}

function buildWorkOptions(projects) {
  const options = [
    { project_id: '', title: '整站综合体验（灵感广场 + 创作台 + 工作流）' },
  ];
  const seen = new Set();
  if (Array.isArray(projects)) {
    for (const p of projects) {
      if (!p || !p.id || seen.has(p.id)) continue;
      seen.add(p.id);
      const label = p.title ? `《${p.title}》 (${p.id})` : p.id;
      options.push({ project_id: p.id, title: label });
    }
  }
  if (options.length === 1) {
    options.push(
      { project_id: 'classics', title: '《名场面猫咪重演》V2V 合集' },
      { project_id: 'starcore', title: '《星核黎明》30 分钟 AI 科幻电影' },
      { project_id: 'starlight_arm', title: '《第七号守夜人》1080p 电影版' },
      { project_id: 'catfilm', title: '《三花信号》萌宠微短剧' },
    );
  }
  return options;
}

function buildSummaryHtml(summary, esc) {
  const pct = (val) => Math.max(0, Math.min(100, Math.round((Number(val || 0) / 5) * 100)));
  const dims = [
    { label: '画面审美', val: summary.avg_aesthetic, emerald: false },
    { label: '角色一致性', val: summary.avg_consistency, emerald: false },
    { label: '小白上手度', val: summary.avg_ease_of_use, emerald: false },
    { label: '性价比与推荐', val: summary.avg_value, emerald: true },
  ];

  return `
    <div class="fe-score-top">
      <div>
        <div class="fe-score-badge">
          <span class="fe-score-big fe-num">${formatScore(summary.avg_overall)}</span>
          <span class="fe-score-outof fe-num">/ 5.0</span>
        </div>
        <div style="display:flex;align-items:center;gap:4px;margin-top:6px;color:var(--accent-gold,#F5B041);">
          ${Array.from({ length: 5 }, (_, i) => {
            const active = i + 1 <= Math.round(summary.avg_overall || 5);
            return `<span style="width:15px;height:15px;display:inline-flex;opacity:${active ? 1 : 0.22};">${ICONS.star.replace('<svg ', '<svg style="width:15px;height:15px;fill:currentColor;" ')}</span>`;
          }).join('')}
          <span style="font-size:12px;color:var(--text-secondary,#9CA3B5);margin-left:6px;">综合满意度</span>
        </div>
      </div>
      <div class="fe-score-meta">
        <span class="fe-score-count fe-num">${formatNumber(summary.count)} 位体验官已评测</span>
        <span class="fe-tag fe-tag--emerald fe-num">推荐分享率 ${summary.recommend_rate}%</span>
      </div>
    </div>

    <div class="fe-dim-bars">
      ${dims.map((d) => `
        <div class="fe-dim-row">
          <span class="fe-dim-name">${esc(d.label)}</span>
          <div class="fe-dim-track">
            <div class="fe-dim-fill ${d.emerald ? 'fe-dim-fill--emerald' : ''}" style="width:${pct(d.val)}%"></div>
          </div>
          <span class="fe-dim-val fe-num">${formatScore(d.val)}</span>
        </div>
      `).join('')}
    </div>
  `;
}

function buildReviewCardsHtml(reviews, filterMode, freshId, esc) {
  let list = reviews;
  if (filterMode === 'recommended') {
    list = reviews.filter((r) => r.would_share);
  }
  if (!list.length) {
    return `<div class="fe-empty">暂无符合筛选条件的评价，欢迎在上方提交第一条体验反馈！</div>`;
  }

  const avatarVariants = ['', 'fe-avatar--cyan', 'fe-avatar--emerald'];

  return list.map((r, idx) => {
    const initial = (r.reviewer_name || '体').slice(0, 1).toUpperCase();
    const avatarCls = avatarVariants[idx % avatarVariants.length];
    const isFresh = freshId !== null && String(r.id) === String(freshId);
    return `
      <article class="fe-review-card ${isFresh ? 'fe-review-card--fresh' : ''}" data-review-id="${esc(r.id)}">
        <div style="display:flex;flex-direction:column;gap:12px;">
          <div class="fe-review-top">
            <div class="fe-reviewer">
              <span class="fe-avatar ${avatarCls}" aria-hidden="true">${esc(initial)}</span>
              <div class="fe-reviewer-meta">
                <div class="fe-reviewer-name-row">
                  <span class="fe-reviewer-name">${esc(r.reviewer_name)}</span>
                  <span class="fe-tag">${esc(r.role)}</span>
                  ${r.is_sample ? `<span class="fe-tag fe-tag--cyan">示例体验官</span>` : ''}
                  ${isFresh ? `<span class="fe-tag fe-tag--gold">刚刚提交</span>` : ''}
                </div>
                ${r.work_title ? `<span class="fe-review-work">${ICONS.film} 评测作品：${esc(r.work_title)}</span>` : ''}
              </div>
            </div>
            <div class="fe-review-score-col">
              <span class="fe-review-overall fe-num">★ ${formatScore(r.overall)}</span>
              ${r.would_share ? `<span class="fe-tag fe-tag--emerald" style="font-size:11px;padding:2px 8px;">愿意安利同事</span>` : ''}
            </div>
          </div>

          <p class="fe-review-comment">${esc(r.comment || '体验流程很顺畅，画质和成本表现都很惊喜！')}</p>
        </div>

        <div class="fe-review-foot">
          <div class="fe-mini-ratings fe-num">
            <span class="fe-mini-rating">审美 <strong>${r.aesthetic}</strong></span>
            <span class="fe-mini-rating">一致 <strong>${r.consistency}</strong></span>
            <span class="fe-mini-rating">易用 <strong>${r.ease_of_use}</strong></span>
            <span class="fe-mini-rating">性价比 <strong>${r.value}</strong></span>
          </div>
          <span class="fe-review-time fe-num">${esc(formatTimeLabel(r.created_at))}</span>
        </div>
      </article>
    `;
  }).join('');
}

const DEFAULT_SHARE_INFO = {
  mode: 'host',
  invite_required: false,
  cloudflared_available: true,
  lan_cmd: 'python3 studio/server.py --host 0.0.0.0 --port 8866',
  public_cmd: 'bash studio/start.sh --public',
  guest_public_cmd: 'bash studio/start.sh --public --guest',
  invite_copy_zh:
    '🎬 邀请你 3 分钟体验「影铸 Studio」AI 视频工作流看板！\n无需装软件、不用背提示词，浏览器点开就能把一句话拍成电影分镜，还能把三国/西游/红楼名场面一键变猫咪（原声口型同步）。\n内测全程 ¥0 免费体验，体验完顺手在「评测中心」打个分告诉我哪一步最惊艳或最该改～',
};

function normalizeShareInfo(raw) {
  const d = raw && typeof raw === 'object' ? raw : {};
  return {
    mode: d.mode === 'guest' ? 'guest' : 'host',
    invite_required: Boolean(d.invite_required),
    cloudflared_available: d.cloudflared_available !== false,
    lan_cmd: redactSecrets(d.lan_cmd || DEFAULT_SHARE_INFO.lan_cmd),
    public_cmd: redactSecrets(d.public_cmd || DEFAULT_SHARE_INFO.public_cmd),
    guest_public_cmd: redactSecrets(d.guest_public_cmd || d.public_cmd || DEFAULT_SHARE_INFO.guest_public_cmd),
    invite_copy_zh: redactSecrets(d.invite_copy_zh || DEFAULT_SHARE_INFO.invite_copy_zh),
  };
}

function renderEvalContent(container, ctx, evalData, workOptions, shareInfo, state) {
  const esc = (v) => safeEsc(ctx, v);

  const lanCmd = shareInfo.lan_cmd;
  const guestPublicCmd = shareInfo.guest_public_cmd;
  const inviteCopyZh = shareInfo.invite_copy_zh;

  container.innerHTML = `
    <div class="fe-page" data-view="eval">
      <!-- 1. Top Welcome Banner + Live Aggregated Rating Board -->
      <section class="fe-eval-hero" aria-label="体验官欢迎与实时评分汇总">
        <div class="fe-hero-left">
          <span class="fe-eyebrow fe-eyebrow--emerald">${ICONS.spark} 白领内测体验官计划 · 全程 ¥0 免费开放</span>
          <h1 class="fe-hero-title">3 分钟上手电影级 AI 视频工作流，打个分帮我们打磨得更好</h1>
          <p class="fe-hero-desc">
            专为非技术同事设计的零门槛短片共创体验：不用背任何英文提示词，挑一个下方 3 分钟小任务实测一遍，再用 30 秒留下你的真实打分和吐槽。
          </p>
          <div class="fe-hero-actions">
            <button type="button" class="fe-btn fe-btn--gold" id="fe-jump-missions">
              ${ICONS.zap}
              <span>挑一个 3 分钟任务开拍</span>
            </button>
            <button type="button" class="fe-btn" id="fe-jump-discover">
              ${ICONS.film}
              <span>先去灵感广场看样片</span>
            </button>
          </div>
        </div>

        <div class="fe-score-board" id="fe-score-board" aria-live="polite">
          ${buildSummaryHtml(evalData.summary, esc)}
        </div>
      </section>

      <!-- 2. Three Guided White-Collar Missions -->
      <section aria-label="上班族 3 分钟快速评测任务">
        <div class="fe-panel-head" style="margin-bottom:14px;">
          <div class="fe-panel-title-wrap">
            <h2 class="fe-panel-title">${ICONS.spark} 上班族 3 分钟快速评测任务卡</h2>
            <p class="fe-panel-sub">任选一个场景点击直达，一键带入模板与参数，零基础也能立刻出分镜和预演成片</p>
          </div>
          <span class="fe-tag fe-tag--gold">推荐体验路径</span>
        </div>

        <div class="fe-missions-grid">
          ${evalData.missions.map((m, idx) => `
            <article class="fe-mission-card">
              <div style="display:flex;flex-direction:column;gap:12px;">
                <div class="fe-mission-top">
                  <span class="fe-mission-num">MISSION 0${idx + 1}</span>
                  <div class="fe-mission-pills">
                    <span class="fe-tag">${esc(m.estTime)}</span>
                    <span class="fe-tag fe-tag--emerald">${esc(m.difficulty)}</span>
                  </div>
                </div>
                <div class="fe-mission-body">
                  <h3 class="fe-mission-title">${esc(m.title)}</h3>
                  <p class="fe-mission-desc">${esc(m.desc)}</p>
                </div>
                <div class="fe-mission-tip">${esc(m.tip)}</div>
              </div>
              <button
                type="button"
                class="fe-btn fe-btn--gold fe-btn--full"
                data-mission-route="${esc(m.route)}"
              >
                <span>去体验这个任务</span>
                ${ICONS.arrowRight}
              </button>
            </article>
          `).join('')}
        </div>
      </section>

      <!-- 3. Interactive 4-Dimension Star Form + One-Click Team Share Panel -->
      <section class="fe-eval-split" aria-label="四维打分表单与同事分享入口">
        <div class="fe-panel">
          <div class="fe-panel-head">
            <div class="fe-panel-title-wrap">
              <h2 class="fe-panel-title">${ICONS.spark} 四维星级打分与体验反馈</h2>
              <p class="fe-panel-sub">提交后立即持久化保存，并实时刷新顶部评分板与下方评价墙</p>
            </div>
            <span class="fe-tag fe-tag--cyan">约 30 秒填完</span>
          </div>

          <form class="fe-form" id="fe-eval-form" novalidate>
            <div class="fe-form-row-2">
              <div class="fe-field">
                <label class="fe-label" for="fe-reviewer-name">
                  体验官昵称 <span class="fe-label-hint">（可填花名或部门昵称）</span>
                </label>
                <input
                  id="fe-reviewer-name"
                  name="reviewer_name"
                  class="fe-input"
                  type="text"
                  maxlength="40"
                  placeholder="例如：市场部小陈 / 摸鱼导演"
                  value="${esc(state.reviewerName)}"
                  required
                />
              </div>

              <div class="fe-field">
                <label class="fe-label" for="fe-work-select">本次评测作品</label>
                <select id="fe-work-select" name="work_title" class="fe-select">
                  ${workOptions.map((opt) => `
                    <option
                      value="${esc(opt.title)}"
                      data-project-id="${esc(opt.project_id)}"
                      ${opt.title === state.workTitle ? 'selected' : ''}
                    >${esc(opt.title)}</option>
                  `).join('')}
                </select>
              </div>
            </div>

            <div class="fe-field">
              <span class="fe-label">职业 / 部门角色</span>
              <div class="fe-role-pills" id="fe-role-pills" role="radiogroup" aria-label="选择职业角色">
                ${ROLE_OPTIONS.map((role) => `
                  <button
                    type="button"
                    role="radio"
                    class="fe-role-pill ${role === state.role ? 'is-selected' : ''}"
                    data-role="${esc(role)}"
                    aria-checked="${role === state.role ? 'true' : 'false'}"
                  >${esc(role)}</button>
                `).join('')}
              </div>
            </div>

            <div class="fe-field">
              <span class="fe-label">四维星级评分 <span class="fe-label-hint">（点击 1~5 星）</span></span>
              <div class="fe-stars-group" id="fe-stars-group">
                ${RATING_DIMENSIONS.map((dim) => {
                  const val = state.ratings[dim.key] || 5;
                  return `
                    <div class="fe-star-row" data-dim-row="${dim.key}">
                      <div class="fe-star-label-col">
                        <span class="fe-star-title">${esc(dim.label)}</span>
                        <span class="fe-star-sub">${esc(dim.desc)}</span>
                      </div>
                      <div class="fe-star-controls">
                        <div class="fe-star-btns" role="radiogroup" aria-label="${esc(dim.label)}评分">
                          ${[1, 2, 3, 4, 5].map((star) => `
                            <button
                              type="button"
                              class="fe-star-btn ${star <= val ? 'is-filled' : ''}"
                              data-dim="${dim.key}"
                              data-score="${star}"
                              aria-label="${esc(dim.label)} ${star} 星"
                              aria-pressed="${star === val ? 'true' : 'false'}"
                            >${ICONS.star}</button>
                          `).join('')}
                        </div>
                        <span class="fe-star-score-label fe-num" data-dim-label="${dim.key}">${esc(SCORE_TEXTS[val] || `${val} 分`)}</span>
                      </div>
                    </div>
                  `;
                }).join('')}
              </div>
            </div>

            <div class="fe-switch-row">
              <div class="fe-switch-copy">
                <span class="fe-switch-title">是否愿意分享给同事或朋友一起玩？</span>
                <span class="fe-switch-desc" id="fe-share-status-text">
                  ${state.wouldShare ? '愿意，这个画质和免费额度很适合发到办公群安利！' : '暂不推荐，还希望再优化部分体验细节。'}
                </span>
              </div>
              <label class="fe-switch" aria-label="是否愿意分享给同事或朋友">
                <input type="checkbox" id="fe-would-share" name="would_share" ${state.wouldShare ? 'checked' : ''} />
                <span class="fe-switch-track"></span>
              </label>
            </div>

            <div class="fe-field">
              <label class="fe-label" for="fe-comment">
                建议或吐槽 <span class="fe-label-hint">（说说最惊艳的点，或哪里还不够顺手）</span>
              </label>
              <textarea
                id="fe-comment"
                name="comment"
                class="fe-textarea"
                rows="3"
                maxlength="600"
                placeholder="例如：真人名场面变猫咪太好玩了，希望以后能一键加部门 Logo 水印..."
              >${esc(state.comment)}</textarea>
            </div>

            <div class="fe-form-footer">
              <span class="fe-form-note">评测数据仅用于打磨产品体验，保存在本地 SQLite 数据库。</span>
              <button type="submit" class="fe-btn fe-btn--gold" id="fe-submit-eval">
                ${ICONS.spark}
                <span>提交我的评测打分</span>
              </button>
            </div>
          </form>
        </div>

        <!-- Team Share Panel -->
        <aside class="fe-panel fe-share-panel host-only" aria-label="一键分享给同事评测">
          <div class="fe-panel-head" style="margin-bottom:4px;">
            <div class="fe-panel-title-wrap">
              <h2 class="fe-panel-title">${ICONS.share} 邀请同事评测 · 一键分享</h2>
              <p class="fe-panel-sub">免装软件、免注册账号，浏览器点开即刻共同体验与打分</p>
            </div>
            <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
              <span class="fe-tag fe-tag--emerald">${shareInfo.invite_required ? '口令保护模式' : '零门槛访客直达'}</span>
              ${shareInfo.cloudflared_available ? `<span class="fe-tag fe-tag--cyan">cloudflared 就绪</span>` : ''}
            </div>
          </div>

          <div class="fe-share-block">
            <div class="fe-share-block-head">
              <span class="fe-share-block-title">微信 / 飞书白领评测邀请文案</span>
              <span class="fe-tag fe-tag--gold">转发直邀</span>
            </div>
            <div class="fe-invite-quote" id="fe-invite-copy-preview">${esc(inviteCopyZh)}</div>
            <button
              type="button"
              class="fe-btn fe-btn--gold fe-btn--full"
              id="fe-copy-invite-copy"
              data-copy-cmd="${esc(inviteCopyZh)}"
              data-copy-label="微信/飞书白领评测邀请文案"
            >
              ${ICONS.chatCopy}
              <span>📋 一键复制微信/飞书白领评测邀请文案</span>
            </button>
          </div>

          <div class="fe-share-block">
            <div class="fe-share-block-head">
              <span class="fe-share-block-title">方式一 · 一键公网零安装体验隧道（推荐）</span>
              <span class="fe-tag fe-tag--gold">微信 / 飞书直发</span>
            </div>
            <p class="fe-share-block-desc">
              以零门槛访客模式启动并通过内置 <code>.runtime/cloudflared/cloudflared</code> 生成临时 HTTPS 链接，远程同事点开即玩，Ctrl+C 关闭即销毁。
            </p>
            <div class="fe-cmd-box">
              <code class="fe-cmd-code" id="fe-guest-public-cmd">${esc(guestPublicCmd)}</code>
              <button type="button" class="fe-btn fe-btn--sm fe-btn--gold-outline" data-copy-cmd="${esc(guestPublicCmd)}" data-copy-label="公网访客体验命令">
                ${ICONS.copy}
                <span>复制</span>
              </button>
            </div>
          </div>

          <div class="fe-share-block">
            <div class="fe-share-block-head">
              <span class="fe-share-block-title">方式二 · 办公室局域网直连</span>
              <span class="fe-tag fe-tag--cyan">同 Wi-Fi 秒开</span>
            </div>
            <p class="fe-share-block-desc">
              在终端执行以下命令监听局域网端口，同事访问 <code>http://&lt;本机IP&gt;:8866</code> 即可实时共用看板并提交评分。
            </p>
            <div class="fe-cmd-box">
              <code class="fe-cmd-code">${esc(lanCmd)}</code>
              <button type="button" class="fe-btn fe-btn--sm" data-copy-cmd="${esc(lanCmd)}" data-copy-label="局域网启动命令">
                ${ICONS.copy}
                <span>复制</span>
              </button>
            </div>
          </div>

          <div class="fe-security-note">
            ${ICONS.shield}
            <span>分享模式仅暴露评测画廊与工作流界面；本机 <code>.env</code> 密钥、模型 Token 与私有文件均受服务端白名单严格隔离。</span>
          </div>
        </aside>
      </section>

      <!-- 4. Live Review Wall -->
      <section class="fe-panel" aria-label="体验官真实评价墙">
        <div class="fe-review-wall-head" style="margin-bottom:18px;">
          <div class="fe-panel-title-wrap">
            <h2 class="fe-panel-title">体验官真实评价墙</h2>
            <p class="fe-panel-sub fe-num" id="fe-wall-count">共 ${formatNumber(evalData.reviews.length)} 条体验反馈 · 按提交时间倒序呈现</p>
          </div>
          <div class="fe-seg-group" id="fe-review-filters" role="tablist" aria-label="筛选评价">
            <button type="button" role="tab" class="fe-seg-btn ${state.filterMode === 'all' ? 'is-active' : ''}" data-filter="all" aria-selected="${state.filterMode === 'all' ? 'true' : 'false'}">全部评价</button>
            <button type="button" role="tab" class="fe-seg-btn ${state.filterMode === 'recommended' ? 'is-active' : ''}" data-filter="recommended" aria-selected="${state.filterMode === 'recommended' ? 'true' : 'false'}">愿意推荐</button>
          </div>
        </div>

        <div class="fe-reviews-grid" id="fe-reviews-grid">
          ${buildReviewCardsHtml(evalData.reviews, state.filterMode, state.freshReviewId, esc)}
        </div>
      </section>
    </div>
  `;

  // Hero jump actions
  const jumpMissionsBtn = container.querySelector('#fe-jump-missions');
  if (jumpMissionsBtn) {
    jumpMissionsBtn.addEventListener('click', () => {
      const target = container.querySelector('.fe-missions-grid');
      if (target) target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
  }
  const jumpDiscoverBtn = container.querySelector('#fe-jump-discover');
  if (jumpDiscoverBtn) {
    jumpDiscoverBtn.addEventListener('click', () => goRoute(ctx, '#discover'));
  }

  // Mission cards navigation
  container.querySelectorAll('[data-mission-route]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const route = btn.getAttribute('data-mission-route') || '#create';
      goRoute(ctx, route);
    });
  });

  // Share command copy buttons
  container.querySelectorAll('[data-copy-cmd]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const cmd = btn.getAttribute('data-copy-cmd') || '';
      const label = btn.getAttribute('data-copy-label') || '命令';
      const ok = await copyText(cmd, `已复制${label}`, ctx);
      if (ok) {
        const span = btn.querySelector('span');
        if (span) {
          const prev = span.textContent;
          span.textContent = '已复制';
          const t = setTimeout(() => {
            if (span.isConnected) span.textContent = prev;
          }, 1600);
          registerCleanup(() => clearTimeout(t));
        }
      }
    });
  });

  // Role pills
  const rolePills = container.querySelector('#fe-role-pills');
  if (rolePills) {
    rolePills.addEventListener('click', (e) => {
      const pill = e.target.closest('[data-role]');
      if (!pill) return;
      state.role = pill.getAttribute('data-role') || ROLE_OPTIONS[0];
      rolePills.querySelectorAll('[data-role]').forEach((el) => {
        const sel = el.getAttribute('data-role') === state.role;
        el.classList.toggle('is-selected', sel);
        el.setAttribute('aria-checked', sel ? 'true' : 'false');
      });
    });
  }

  // Interactive 4-dimension 5-star buttons
  const starsGroup = container.querySelector('#fe-stars-group');
  if (starsGroup) {
    const paintRow = (dimKey, score, hoverScore = 0) => {
      const row = starsGroup.querySelector(`[data-dim-row="${dimKey}"]`);
      if (!row) return;
      const shown = hoverScore || score;
      row.querySelectorAll('.fe-star-btn').forEach((btn) => {
        const s = Number(btn.getAttribute('data-score'));
        btn.classList.toggle('is-filled', s <= score);
        btn.classList.toggle('is-hover', hoverScore > 0 && s <= hoverScore);
        btn.setAttribute('aria-pressed', s === score ? 'true' : 'false');
      });
      const lbl = row.querySelector(`[data-dim-label="${dimKey}"]`);
      if (lbl) lbl.textContent = SCORE_TEXTS[shown] || `${shown} 分`;
    };

    starsGroup.addEventListener('click', (e) => {
      const btn = e.target.closest('.fe-star-btn');
      if (!btn) return;
      const dimKey = btn.getAttribute('data-dim');
      const score = Number(btn.getAttribute('data-score'));
      if (!dimKey || !score) return;
      state.ratings[dimKey] = score;
      paintRow(dimKey, score, 0);
    });

    starsGroup.addEventListener('mouseover', (e) => {
      const btn = e.target.closest('.fe-star-btn');
      if (!btn) return;
      const dimKey = btn.getAttribute('data-dim');
      const score = Number(btn.getAttribute('data-score'));
      if (dimKey && score) paintRow(dimKey, state.ratings[dimKey] || 5, score);
    });

    starsGroup.addEventListener('mouseout', (e) => {
      const row = e.target.closest('[data-dim-row]');
      if (!row) return;
      if (row.contains(e.relatedTarget)) return;
      const dimKey = row.getAttribute('data-dim-row');
      if (dimKey) paintRow(dimKey, state.ratings[dimKey] || 5, 0);
    });
  }

  // Would-share toggle
  const shareToggle = container.querySelector('#fe-would-share');
  const shareStatusText = container.querySelector('#fe-share-status-text');
  if (shareToggle) {
    shareToggle.addEventListener('change', () => {
      state.wouldShare = shareToggle.checked;
      if (shareStatusText) {
        shareStatusText.textContent = state.wouldShare
          ? '愿意，这个画质和免费额度很适合发到办公群安利！'
          : '暂不推荐，还希望再优化部分体验细节。';
      }
    });
  }

  // Review wall filter tabs
  const filterTabs = container.querySelector('#fe-review-filters');
  const reviewsGrid = container.querySelector('#fe-reviews-grid');
  if (filterTabs && reviewsGrid) {
    filterTabs.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-filter]');
      if (!btn) return;
      state.filterMode = btn.getAttribute('data-filter') || 'all';
      filterTabs.querySelectorAll('[data-filter]').forEach((el) => {
        const active = el.getAttribute('data-filter') === state.filterMode;
        el.classList.toggle('is-active', active);
        el.setAttribute('aria-selected', active ? 'true' : 'false');
      });
      reviewsGrid.innerHTML = buildReviewCardsHtml(evalData.reviews, state.filterMode, state.freshReviewId, esc);
    });
  }

  // Form submission
  const form = container.querySelector('#fe-eval-form');
  if (form) {
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const nameInput = form.querySelector('#fe-reviewer-name');
      const workSelect = form.querySelector('#fe-work-select');
      const commentInput = form.querySelector('#fe-comment');
      const submitBtn = form.querySelector('#fe-submit-eval');

      const reviewerName = (nameInput?.value || '').trim() || '匿名白领体验官';
      const comment = (commentInput?.value || '').trim();
      const selectedOpt = workSelect?.options?.[workSelect.selectedIndex];
      const workTitle = selectedOpt?.value || '';
      const projectId = selectedOpt?.getAttribute('data-project-id') || '';

      state.reviewerName = reviewerName;
      state.workTitle = workTitle;
      state.comment = comment;

      const payload = {
        reviewer_name: reviewerName,
        role: state.role,
        work_title: workTitle,
        project_id: projectId,
        aesthetic: Number(state.ratings.aesthetic) || 5,
        consistency: Number(state.ratings.consistency) || 5,
        ease_of_use: Number(state.ratings.ease_of_use) || 5,
        value: Number(state.ratings.value) || 5,
        would_share: Boolean(state.wouldShare),
        comment: comment || '画面很惊艳，工作流步骤一目了然！',
      };

      if (submitBtn) submitBtn.disabled = true;
      try {
        const res = await ctx.api.submitEvaluation(payload);
        const createdId = res?.review?.id ?? null;
        state.freshReviewId = createdId;
        state.comment = '';
        if (commentInput) commentInput.value = '';

        // Re-fetch authoritative list + summary from SQLite
        const refreshedRaw = await ctx.api.evaluations();
        const refreshed = normalizeEvalData(refreshedRaw);
        evalData.summary = refreshed.summary;
        evalData.reviews = refreshed.reviews;

        const scoreBoard = container.querySelector('#fe-score-board');
        if (scoreBoard) scoreBoard.innerHTML = buildSummaryHtml(evalData.summary, esc);

        const wallCount = container.querySelector('#fe-wall-count');
        if (wallCount) wallCount.textContent = `共 ${formatNumber(evalData.reviews.length)} 条体验反馈 · 按提交时间倒序呈现`;

        if (reviewsGrid) {
          reviewsGrid.innerHTML = buildReviewCardsHtml(evalData.reviews, state.filterMode, state.freshReviewId, esc);
        }

        notify(ctx, '感谢评测！你的四维打分已实时同步至评价墙 🎉', 'success');
      } catch (err) {
        notify(ctx, `提交失败：${err?.message || '请检查网络后重试'}`, 'error');
      } finally {
        if (submitBtn) submitBtn.disabled = false;
      }
    });
  }
}

export async function renderEval(container, ctx) {
  destroy();
  container.innerHTML = `
    <div class="fe-page">
      <div class="fe-loading">
        <div class="fe-skel" style="height:210px;"></div>
        <div class="fe-missions-grid">
          <div class="fe-skel" style="height:210px;"></div>
          <div class="fe-skel" style="height:210px;"></div>
          <div class="fe-skel" style="height:210px;"></div>
        </div>
        <div class="fe-skel" style="height:320px;"></div>
      </div>
    </div>
  `;

  let alive = true;
  registerCleanup(() => { alive = false; });

  const state = {
    reviewerName: '',
    role: ROLE_OPTIONS[0],
    workTitle: '',
    ratings: {
      aesthetic: 5,
      consistency: 5,
      ease_of_use: 5,
      value: 5,
    },
    wouldShare: true,
    comment: '',
    filterMode: 'all',
    freshReviewId: null,
  };

  const [evalRes, projRes, shareRes] = await Promise.allSettled([
    ctx.api.evaluations(),
    typeof ctx.api.projects === 'function' ? ctx.api.projects() : Promise.resolve({ projects: [] }),
    typeof ctx.api.shareInfo === 'function' ? ctx.api.shareInfo() : Promise.resolve(DEFAULT_SHARE_INFO),
  ]);

  if (!alive) return;

  const evalData = normalizeEvalData(evalRes.status === 'fulfilled' ? evalRes.value : {});
  const projects = projRes.status === 'fulfilled' ? (projRes.value?.projects || []) : [];
  const shareInfo = normalizeShareInfo(shareRes.status === 'fulfilled' ? shareRes.value : {});
  const workOptions = buildWorkOptions(projects);
  state.workTitle = workOptions[0]?.title || '';

  if (evalRes.status === 'rejected') {
    notify(ctx, `加载评测数据失败，已展示离线默认面板`, 'info');
  }

  renderEvalContent(container, ctx, evalData, workOptions, shareInfo, state);

  // Live SSE sync when another colleague submits an evaluation
  if (ctx?.store && typeof ctx.store.subscribe === 'function') {
    const unsub = ctx.store.subscribe('sse:evaluation_added', async () => {
      if (!alive) return;
      try {
        const refreshedRaw = await ctx.api.evaluations();
        if (!alive) return;
        const refreshed = normalizeEvalData(refreshedRaw);
        evalData.summary = refreshed.summary;
        evalData.reviews = refreshed.reviews;
        const esc = (v) => safeEsc(ctx, v);
        const scoreBoard = container.querySelector('#fe-score-board');
        if (scoreBoard) scoreBoard.innerHTML = buildSummaryHtml(evalData.summary, esc);
        const wallCount = container.querySelector('#fe-wall-count');
        if (wallCount) wallCount.textContent = `共 ${formatNumber(evalData.reviews.length)} 条体验反馈 · 按提交时间倒序呈现`;
        const grid = container.querySelector('#fe-reviews-grid');
        if (grid) grid.innerHTML = buildReviewCardsHtml(evalData.reviews, state.filterMode, state.freshReviewId, esc);
      } catch {
        // ignore transient refresh failure
      }
    });
    registerCleanup(unsub);
  }
}
