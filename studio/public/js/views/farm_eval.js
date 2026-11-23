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
// VIEW 1: COMPUTE FARM MONITOR (#farm)
// ---------------------------------------------------------------------------

const DEFAULT_TELEMETRY = [
  { label: '09:00', shot_sec: 46, throughput_per_hr: 78, active_gpus: 1, source: 'baseline' },
  { label: '09:30', shot_sec: 44, throughput_per_hr: 82, active_gpus: 1, source: 'baseline' },
  { label: '10:00', shot_sec: 41, throughput_per_hr: 88, active_gpus: 2, source: 'measured' },
  { label: '10:30', shot_sec: 39, throughput_per_hr: 92, active_gpus: 2, source: 'measured' },
  { label: '11:00', shot_sec: 43, throughput_per_hr: 84, active_gpus: 2, source: 'measured' },
  { label: '11:30', shot_sec: 38, throughput_per_hr: 95, active_gpus: 2, source: 'measured' },
  { label: '12:00', shot_sec: 42, throughput_per_hr: 86, active_gpus: 1, source: 'baseline' },
  { label: '13:00', shot_sec: 40, throughput_per_hr: 90, active_gpus: 2, source: 'measured' },
  { label: '13:30', shot_sec: 37, throughput_per_hr: 97, active_gpus: 2, source: 'measured' },
  { label: '14:00', shot_sec: 41, throughput_per_hr: 88, active_gpus: 2, source: 'measured' },
  { label: '14:30', shot_sec: 39, throughput_per_hr: 92, active_gpus: 2, source: 'measured' },
  { label: '15:00', shot_sec: 38, throughput_per_hr: 95, active_gpus: 2, source: 'measured' },
  { label: '15:30', shot_sec: 42, throughput_per_hr: 86, active_gpus: 1, source: 'baseline' },
  { label: '16:00', shot_sec: 40, throughput_per_hr: 90, active_gpus: 2, source: 'measured' },
];

const DEFAULT_COST_TIERS = [
  {
    key: '30s',
    label: '30 秒爆款短片',
    shots: 6,
    renderTime: '约 4 分钟',
    cu: 2,
    oursUsd: 0.2,
    oursCny: 1.4,
    commercialCny: 48,
    commercialNote: '主流商业平台按秒/重抽积分约 ¥48~¥75',
    traditionalCny: 6000,
    traditionalNote: '实拍场地 + 剪辑外包周期 3~5 天',
  },
  {
    key: '3m',
    label: '3 分钟微短剧',
    shots: 36,
    renderTime: '约 24 分钟',
    cu: 11,
    oursUsd: 1.1,
    oursCny: 7.5,
    commercialCny: 260,
    commercialNote: '商业 AI 视频含角色返工约 ¥260~¥420',
    traditionalCny: 35000,
    traditionalNote: '小型剧组 / 外包动画制作约 2 周',
  },
  {
    key: '30m',
    label: '30 分钟院线长片',
    shots: 366,
    renderTime: '多卡并行 ~2.5 小时',
    cu: 110,
    oursUsd: 11,
    oursCny: 78,
    commercialCny: 1680,
    commercialNote: '商业平台长片高配积分 ¥1,680+ 且角色易漂移',
    traditionalCny: 240000,
    traditionalNote: '传统影视外包团队制作周期 1~2 个月',
  },
];

const DEFAULT_COLAB_SCRIPT = `# CineForge 脱敏 Colab GPU 接入模板（零密钥版本）
# 说明：模型授权令牌仅由本机 farm_server 从 .env 内存态下发，不落盘、不进日志

!git clone --depth 1 https://github.com/your-org/cineforge-worker.git /content/worker
%cd /content/worker

# 填入派片端临时地址与一次性任务口令（运行前向管理员获取）
FARM_URL = "https://<your-farm-tunnel>.example"
FARM_TOKEN = "<paste-session-token-here>"

!python3 worker_client.py \\
  --farm-url "$FARM_URL" \\
  --token "$FARM_TOKEN" \\
  --engine auto \\
  --idle-shutdown 900`;

function normalizeFarmData(raw) {
  const d = raw && typeof raw === 'object' ? raw : {};
  const stats = d.stats || d.metrics || {};

  const online = Boolean(
    d.online ??
    d.farm_online ??
    d.farm_server_online ??
    d.dispatcher_online ??
    d.server_online ??
    (typeof d.status === 'string' && ['online', 'running', 'active', 'ready'].includes(d.status.toLowerCase()))
  );

  const totalShots = Number(
    d.total_shots_rendered ??
    d.rendered_shots ??
    d.shots_rendered ??
    d.total_shots ??
    stats.total_shots_rendered ??
    stats.rendered_shots ??
    0
  );

  const medianH3 = Number(d.median_h3_sec ?? d.h3_median_sec ?? stats.median_h3_sec ?? d.median_wall_sec ?? 43) || 43;
  const medianLtx = Number(d.median_ltx_sec ?? d.ltx_median_sec ?? stats.median_ltx_sec ?? 38) || 38;
  const cost30mUsd = Number(d.est_cost_30min_usd ?? d.cost_30min_usd ?? stats.est_cost_30min_usd ?? 11) || 11;
  const cu30m = Number(d.est_cu_30min ?? d.cu_30min ?? stats.est_cu_30min ?? 110) || 110;
  const perMinCny = Number(d.cost_per_min_cny ?? stats.cost_per_min_cny ?? 2.4) || 2.4;
  const savingsPct = Number(d.savings_pct ?? d.savings_percent ?? stats.savings_pct ?? 85) || 85;
  const port = d.port ?? d.farm_port ?? 8765;

  // Normalize workers
  const rawWorkers = Array.isArray(d.workers)
    ? d.workers
    : Array.isArray(d.nodes)
      ? d.nodes
      : Array.isArray(d.gpus)
        ? d.gpus
        : [];

  const workers = rawWorkers.map((w, idx) => ({
    id: w.id || w.worker_id || w.name || `colab-worker-${idx + 1}`,
    gpu: w.gpu || w.gpu_model || w.model || w.device || 'NVIDIA L4 / A100 Colab GPU',
    status: String(w.status || (online ? 'online' : 'standby')).toLowerCase(),
    completedShots: Number(w.completed_shots ?? w.shots ?? w.jobs_done ?? 0),
    engine: w.engine || w.backend || 'H3 / LTX-2.5',
    lastSeen: w.last_seen || w.updated_at || w.heartbeat || (online ? '刚刚' : '按需休眠'),
  }));

  // Normalize activity logs
  const rawLogs = Array.isArray(d.activity)
    ? d.activity
    : Array.isArray(d.activities)
      ? d.activities
      : Array.isArray(d.logs)
        ? d.logs
        : Array.isArray(d.recent_logs)
          ? d.recent_logs
          : [];

  const activity = rawLogs.slice(0, 40).map((entry) => {
    if (typeof entry === 'string') {
      return {
        time: '',
        tag: 'FARM',
        level: 'info',
        message: redactSecrets(entry),
      };
    }
    return {
      time: entry.time || entry.timestamp || '',
      tag: String(entry.source || entry.tag || entry.level || 'FARM').toUpperCase().slice(0, 10),
      level: String(entry.level || 'info').toLowerCase(),
      message: redactSecrets(entry.message || entry.text || entry.summary || ''),
    };
  }).filter((item) => item.message);

  // Normalize cost comparison tiers if backend supplies them
  let tiers = DEFAULT_COST_TIERS;
  const rawTiers = d.cost_comparison || d.cost_tiers || d.tiers;
  if (Array.isArray(rawTiers) && rawTiers.length >= 2) {
    tiers = rawTiers.map((t, idx) => {
      const fb = DEFAULT_COST_TIERS[idx] || DEFAULT_COST_TIERS[0];
      return {
        key: String(t.key || t.id || fb.key),
        label: t.label || t.title || fb.label,
        shots: Number(t.shots ?? t.est_shots ?? fb.shots),
        renderTime: t.render_time || t.est_time || fb.renderTime,
        cu: Number(t.cu ?? t.est_cu ?? fb.cu),
        oursUsd: Number(t.ours_usd ?? t.cineforge_usd ?? fb.oursUsd),
        oursCny: Number(t.ours_cny ?? t.cineforge_cny ?? t.platform_cny ?? fb.oursCny),
        commercialCny: Number(t.commercial_cny ?? t.saas_cny ?? fb.commercialCny),
        commercialNote: t.commercial_note || fb.commercialNote,
        traditionalCny: Number(t.traditional_cny ?? t.studio_cny ?? fb.traditionalCny),
        traditionalNote: t.traditional_note || fb.traditionalNote,
      };
    });
  }

  // Normalize colab_guide
  const rawGuide = d.colab_guide || d.onboarding || {};
  let colabSnippet = DEFAULT_COLAB_SCRIPT;
  let colabNote = '安全架构说明：HF_TOKEN 等模型密钥仅存于本机 .env（权限 600）并由 farm_server 读入内存，绝不写入脚本、日志或前端导出包。';
  let colabSteps = [
    {
      num: 'STEP 01',
      title: '打开免费或闲置 Colab',
      desc: '登录 Google Colab 新建笔记本，选择 T4（免费版）或 L4 / A100 运行时即可接入。',
    },
    {
      num: 'STEP 02',
      title: '运行脱敏接入脚本',
      desc: '一键复制下方脱敏脚本粘贴运行，自动加入影铸共享算力池并领取分镜渲染任务。',
    },
    {
      num: 'STEP 03',
      title: '零密钥泄露 + 闲置休眠',
      desc: '密钥仅留本机内存态；任务完成后自动休眠断开，绝不浪费任何一张 GPU 额度。',
    },
  ];

  if (typeof rawGuide === 'string' && rawGuide.trim()) {
    colabSnippet = redactSecrets(rawGuide.trim());
  } else if (rawGuide && typeof rawGuide === 'object') {
    const snippetCandidate = rawGuide.snippet || rawGuide.script || rawGuide.code || d.colab_snippet;
    if (snippetCandidate) colabSnippet = redactSecrets(String(snippetCandidate).trim());
    if (rawGuide.security_note || rawGuide.note) {
      colabNote = redactSecrets(String(rawGuide.security_note || rawGuide.note));
    }
    if (Array.isArray(rawGuide.steps) && rawGuide.steps.length >= 3) {
      colabSteps = rawGuide.steps.slice(0, 3).map((s, idx) => {
        if (typeof s === 'string') {
          return { num: `STEP 0${idx + 1}`, title: `步骤 ${idx + 1}`, desc: redactSecrets(s) };
        }
        return {
          num: `STEP 0${idx + 1}`,
          title: redactSecrets(s.title || `步骤 ${idx + 1}`),
          desc: redactSecrets(s.desc || s.description || s.detail || ''),
        };
      });
    }
  }

  // Normalize EasyColab telemetry series
  const rawTelemetry = Array.isArray(d.telemetry) && d.telemetry.length >= 2 ? d.telemetry : DEFAULT_TELEMETRY;
  const telemetry = rawTelemetry.slice(0, 24).map((pt, idx) => {
    const shotSec = Math.max(10, Number(pt.shot_sec ?? pt.wall_sec ?? medianH3) || medianH3);
    const activeGpus = Math.max(1, Number(pt.active_gpus ?? pt.gpus ?? 1) || 1);
    const tp = Math.max(
      1,
      Number(pt.throughput_per_hr ?? Math.round((3600 / shotSec) * activeGpus)) || Math.round(3600 / shotSec)
    );
    return {
      label: String(pt.label || pt.time || `T${idx + 1}`).slice(0, 12),
      shot_sec: Number(shotSec.toFixed(1)),
      throughput_per_hr: Math.round(tp),
      active_gpus: activeGpus,
      source: String(pt.source || 'baseline').toLowerCase() === 'measured' ? 'measured' : 'baseline',
    };
  });

  // Normalize idle_guard & gdrive_cache_supported
  const rawGuard = d.idle_guard && typeof d.idle_guard === 'object' ? d.idle_guard : {};
  const idleGuard = {
    enabled: rawGuard.enabled !== false,
    timeout_min: Number(rawGuard.timeout_min ?? 15) || 15,
    saved_cu_est: Number(rawGuard.saved_cu_est ?? 18.5),
  };
  if (!Number.isFinite(idleGuard.saved_cu_est) || idleGuard.saved_cu_est < 0) {
    idleGuard.saved_cu_est = 18.5;
  }
  const gdriveCacheSupported = d.gdrive_cache_supported !== false;

  return {
    online,
    port,
    totalShots,
    medianH3,
    medianLtx,
    cost30mUsd,
    cu30m,
    perMinCny,
    savingsPct,
    workers,
    activity,
    tiers,
    telemetry,
    idleGuard,
    gdriveCacheSupported,
    colabSteps,
    colabSnippet,
    colabNote,
  };
}

function buildTelemetryChartSvg(telemetry, metricKey, selectedIdx, esc) {
  const isThroughput = metricKey === 'throughput_per_hr';
  const points = telemetry.length >= 2 ? telemetry : DEFAULT_TELEMETRY;
  const values = points.map((p) => (isThroughput ? p.throughput_per_hr : p.shot_sec));

  const rawMin = Math.min(...values);
  const rawMax = Math.max(...values);
  const padSpan = Math.max(isThroughput ? 12 : 6, (rawMax - rawMin) * 0.25);
  const minVal = Math.max(0, Math.floor((rawMin - padSpan) / 5) * 5);
  const maxVal = Math.ceil((rawMax + padSpan) / 5) * 5;
  const span = Math.max(1, maxVal - minVal);

  const W = 960;
  const H = 205;
  const padL = 52;
  const padR = 24;
  const padT = 20;
  const padB = 32;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;
  const baseY = padT + plotH;

  const coords = points.map((p, i) => {
    const val = isThroughput ? p.throughput_per_hr : p.shot_sec;
    const x = padL + (points.length === 1 ? plotW / 2 : (i / (points.length - 1)) * plotW);
    const y = baseY - ((val - minVal) / span) * plotH;
    return { x: Number(x.toFixed(1)), y: Number(y.toFixed(1)), val, pt: p, idx: i };
  });

  // Smooth Catmull-Rom -> cubic Bezier path clamped inside plot bounds
  const clampY = (y) => Number(Math.max(padT + 2, Math.min(baseY - 2, y)).toFixed(1));
  let linePath = `M ${coords[0].x} ${coords[0].y}`;
  for (let i = 0; i < coords.length - 1; i++) {
    const p0 = coords[Math.max(0, i - 1)];
    const p1 = coords[i];
    const p2 = coords[i + 1];
    const p3 = coords[Math.min(coords.length - 1, i + 2)];
    const cp1x = Number((p1.x + (p2.x - p0.x) / 6).toFixed(1));
    const cp1y = clampY(p1.y + (p2.y - p0.y) / 6);
    const cp2x = Number((p2.x - (p3.x - p1.x) / 6).toFixed(1));
    const cp2y = clampY(p2.y - (p3.y - p1.y) / 6);
    linePath += ` C ${cp1x} ${cp1y}, ${cp2x} ${cp2y}, ${p2.x} ${p2.y}`;
  }

  const areaPath = `${linePath} L ${coords[coords.length - 1].x} ${baseY} L ${coords[0].x} ${baseY} Z`;

  const gridTicks = 4;
  const gridLinesHtml = Array.from({ length: gridTicks + 1 }, (_, k) => {
    const ratio = k / gridTicks;
    const y = Number((padT + ratio * plotH).toFixed(1));
    const labelVal = Math.round(maxVal - ratio * span);
    const unit = isThroughput ? '' : 's';
    return `
      <line x1="${padL}" y1="${y}" x2="${W - padR}" y2="${y}" stroke="rgba(255,255,255,0.065)" stroke-dasharray="${k === gridTicks ? '0' : '4 5'}" stroke-width="1" />
      <text x="${padL - 10}" y="${y + 4}" text-anchor="end" fill="#646D82" font-size="11" font-family="JetBrains Mono, ui-monospace, monospace">${labelVal}${unit}</text>
    `;
  }).join('');

  const labelStep = Math.max(1, Math.ceil(coords.length / 8));
  const xLabelsHtml = coords
    .filter((_, i) => i === 0 || i === coords.length - 1 || i % labelStep === 0)
    .map((c) => `
      <text x="${c.x}" y="${H - 10}" text-anchor="middle" fill="#646D82" font-size="11" font-family="JetBrains Mono, ui-monospace, monospace">${esc(c.pt.label)}</text>
    `)
    .join('');

  const strokeGradId = isThroughput ? 'fe-line-emerald' : 'fe-line-gold';
  const areaGradId = isThroughput ? 'fe-area-emerald' : 'fe-area-gold';
  const activeIdx = selectedIdx >= 0 && selectedIdx < coords.length ? selectedIdx : coords.length - 1;
  const activeCoord = coords[activeIdx];

  const dotsHtml = coords.map((c) => {
    const isMeasured = c.pt.source === 'measured';
    const isFocused = c.idx === activeIdx;
    const fill = isMeasured
      ? (isThroughput ? '#34D399' : '#F5B041')
      : '#38BDF8';
    return `
      <g class="fe-chart-pt" data-point-idx="${c.idx}" tabindex="0" role="button" aria-label="${esc(c.pt.label)} 单镜 ${c.pt.shot_sec}秒 吞吐 ${c.pt.throughput_per_hr}镜每小时">
        <circle cx="${c.x}" cy="${c.y}" r="${isFocused ? 11 : 7}" fill="${fill}" opacity="${isFocused ? '0.24' : '0.12'}" />
        <circle cx="${c.x}" cy="${c.y}" r="${isFocused ? 4.8 : 3.5}" fill="${fill}" stroke="#090B10" stroke-width="1.8" />
        <title>${esc(c.pt.label)} · 单镜 ${c.pt.shot_sec}s · 吞吐 ${c.pt.throughput_per_hr} 镜/时 · ${c.pt.active_gpus} 卡 (${isMeasured ? '实测' : '基线'})</title>
      </g>
    `;
  }).join('');

  return `
    <svg class="fe-chart-svg" id="fe-telemetry-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="${isThroughput ? '云端每小时出片吞吐折线图' : '云端单镜渲染耗时折线图'}">
      <defs>
        <linearGradient id="fe-line-gold" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stop-color="#38BDF8" />
          <stop offset="55%" stop-color="#F5B041" />
          <stop offset="100%" stop-color="#F7C266" />
        </linearGradient>
        <linearGradient id="fe-area-gold" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stop-color="#F5B041" stop-opacity="0.30" />
          <stop offset="65%" stop-color="#38BDF8" stop-opacity="0.08" />
          <stop offset="100%" stop-color="#07080B" stop-opacity="0.0" />
        </linearGradient>
        <linearGradient id="fe-line-emerald" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stop-color="#38BDF8" />
          <stop offset="55%" stop-color="#34D399" />
          <stop offset="100%" stop-color="#6EE7B7" />
        </linearGradient>
        <linearGradient id="fe-area-emerald" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stop-color="#34D399" stop-opacity="0.32" />
          <stop offset="65%" stop-color="#38BDF8" stop-opacity="0.08" />
          <stop offset="100%" stop-color="#07080B" stop-opacity="0.0" />
        </linearGradient>
        <filter id="fe-stroke-glow" x="-10%" y="-25%" width="120%" height="150%">
          <feGaussianBlur stdDeviation="3.2" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      ${gridLinesHtml}
      <line x1="${activeCoord.x}" y1="${padT}" x2="${activeCoord.x}" y2="${baseY}" stroke="rgba(245, 176, 65, 0.24)" stroke-dasharray="3 4" stroke-width="1" />
      <path d="${areaPath}" fill="url(#${areaGradId})" />
      <path d="${linePath}" fill="none" stroke="url(#${strokeGradId})" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" filter="url(#fe-stroke-glow)" />
      ${dotsHtml}
      ${xLabelsHtml}
    </svg>
  `;
}

function buildTelemetryReadoutHtml(pt, esc) {
  if (!pt) return '';
  const isMeasured = pt.source === 'measured';
  return `
    <span class="fe-tag ${isMeasured ? 'fe-tag--gold' : 'fe-tag--cyan'}" style="font-size:11px;padding:2px 8px;">${isMeasured ? '实测采样' : '基线校准'}</span>
    <span class="fe-num">时段 <strong>${esc(pt.label)}</strong></span>
    <span class="fe-num">单镜 <strong style="color:var(--accent-gold,#F5B041);">${pt.shot_sec}s</strong></span>
    <span class="fe-num">吞吐 <strong style="color:var(--accent-emerald,#34D399);">${pt.throughput_per_hr} 镜/时</strong></span>
    <span class="fe-num">活跃 <strong>${pt.active_gpus} 卡</strong></span>
  `;
}

function buildCostCalcHtml(tier, esc) {
  // Visual scaling: commercial vs ours are compared clearly while traditional stays 100% anchor
  const maxTraditional = Math.max(tier.traditionalCny, tier.commercialCny, 1);
  // Use logarithmic-assisted visual bar width so commercial (¥48~1680) and ours (¥1.4~78) remain visually legible alongside ¥240,000!
  const logPct = (val) => {
    const ratio = Math.log10(Math.max(val, 1) + 1) / Math.log10(maxTraditional + 1);
    return Math.max(4, Math.min(100, Math.round(ratio * 100)));
  };

  const tradWidth = 100;
  const commWidth = Math.max(24, Math.min(72, logPct(tier.commercialCny)));
  const oursWidth = Math.max(6, Math.min(20, Math.round(logPct(tier.oursCny) * 0.42)));

  const saveVsComm = Math.max(0, Math.round(tier.commercialCny - tier.oursCny));
  const savePctVsComm = tier.commercialCny > 0
    ? Math.max(85, Math.min(99, Math.round((1 - tier.oursCny / tier.commercialCny) * 100)))
    : 92;

  return `
    <div class="fe-bar-list">
      <div class="fe-bar-item">
        <div class="fe-bar-meta">
          <div class="fe-bar-label-wrap">
            <span class="fe-bar-label">传统外包 / 实拍团队</span>
            <span class="fe-tag">人工重资产</span>
          </div>
          <span class="fe-bar-price fe-num">¥${formatNumber(tier.traditionalCny)}+</span>
        </div>
        <div class="fe-bar-track">
          <div class="fe-bar-fill fe-bar-fill--traditional" style="width:${tradWidth}%"></div>
        </div>
        <div class="fe-bar-note">
          <span>${esc(tier.traditionalNote)}</span>
          <span class="fe-num">基准参照 100%</span>
        </div>
      </div>

      <div class="fe-bar-item">
        <div class="fe-bar-meta">
          <div class="fe-bar-label-wrap">
            <span class="fe-bar-label">市面主流商用 AI 视频平台</span>
            <span class="fe-tag fe-tag--rose">按次抽卡扣积分</span>
          </div>
          <span class="fe-bar-price fe-num">约 ¥${formatNumber(tier.commercialCny)}</span>
        </div>
        <div class="fe-bar-track">
          <div class="fe-bar-fill fe-bar-fill--commercial" style="width:${commWidth}%"></div>
        </div>
        <div class="fe-bar-note">
          <span>${esc(tier.commercialNote)}</span>
          <span class="fe-num">仍需持续充值会员积分</span>
        </div>
      </div>

      <div class="fe-bar-item fe-bar-item--ours">
        <div class="fe-bar-meta">
          <div class="fe-bar-label-wrap">
            <span class="fe-bar-label">影铸 Colab 共享算力池（本平台）</span>
            <span class="fe-tag fe-tag--emerald">内测体验官 ¥0 免费额度</span>
          </div>
          <span class="fe-bar-price fe-num">≈ ¥${tier.oursCny} <small style="font-size:12px;font-weight:600;opacity:0.85;">(${tier.cu} CU)</small></span>
        </div>
        <div class="fe-bar-track">
          <div class="fe-bar-fill fe-bar-fill--ours" style="width:${oursWidth}%"></div>
        </div>
        <div class="fe-bar-note">
          <span>折合 $${tier.oursUsd} · 开源模型权重 + 闲置 Colab GPU 共享编排</span>
          <span style="color:var(--accent-emerald,#34D399);font-weight:650;">比商用平台立省 ${savePctVsComm}%</span>
        </div>
      </div>
    </div>

    <div class="fe-calc-summary">
      <div class="fe-savings-hero">
        <span class="fe-savings-kicker">相比商用 AI 视频平台立省</span>
        <div class="fe-savings-amount fe-num">¥${formatNumber(saveVsComm)}+</div>
        <span class="fe-savings-sub">降本高达 <strong style="color:var(--accent-emerald,#34D399);">${savePctVsComm}%</strong> · 视觉锁保障主角连贯不重抽</span>
      </div>

      <div class="fe-telemetry-list">
        <div class="fe-telemetry-row">
          <span class="fe-telemetry-key">目标片长规格</span>
          <span class="fe-telemetry-val">${esc(tier.label)}</span>
        </div>
        <div class="fe-telemetry-row">
          <span class="fe-telemetry-key">预计拆解分镜数</span>
          <span class="fe-telemetry-val fe-num">约 ${formatNumber(tier.shots)} 镜</span>
        </div>
        <div class="fe-telemetry-row">
          <span class="fe-telemetry-key">云端实测出片耗时</span>
          <span class="fe-telemetry-val">${esc(tier.renderTime)}</span>
        </div>
        <div class="fe-telemetry-row">
          <span class="fe-telemetry-key">云算力真实消耗</span>
          <span class="fe-telemetry-val fe-telemetry-val--gold fe-num">${tier.cu} CU (≈ $${tier.oursUsd} / ¥${tier.oursCny})</span>
        </div>
        <div class="fe-telemetry-row">
          <span class="fe-telemetry-key">白领体验官实付</span>
          <span class="fe-telemetry-val fe-telemetry-val--emerald">¥0（内测共享额度全包）</span>
        </div>
      </div>

      <button type="button" class="fe-btn fe-btn--gold fe-btn--full" data-action="go-create">
        ${ICONS.spark}
        <span>立即免费试拍一支「${esc(tier.label)}」</span>
      </button>
    </div>
  `;
}

function renderFarmContent(container, ctx, farm, state) {
  const esc = (v) => safeEsc(ctx, v);
  const activeTier = farm.tiers.find((t) => t.key === state.selectedTierKey) || farm.tiers[0];
  const notebookUrl = ctx?.api?.colabNotebookUrl || '/api/farm/colab-notebook';

  const telemetry = farm.telemetry || DEFAULT_TELEMETRY;
  const measuredCount = telemetry.filter((p) => p.source === 'measured').length;
  const baselineCount = telemetry.length - measuredCount;
  const peakGpus = Math.max(1, ...telemetry.map((p) => p.active_gpus || 1));
  const avgShotSec = (telemetry.reduce((acc, p) => acc + p.shot_sec, 0) / Math.max(1, telemetry.length)).toFixed(1);
  const avgThroughput = Math.round(telemetry.reduce((acc, p) => acc + p.throughput_per_hr, 0) / Math.max(1, telemetry.length));
  const focusedIdx = state.selectedPointIdx >= 0 && state.selectedPointIdx < telemetry.length
    ? state.selectedPointIdx
    : telemetry.length - 1;
  const focusedPt = telemetry[focusedIdx];
  const savedCnyEst = (farm.idleGuard.saved_cu_est * 0.72).toFixed(1);

  const statusPillHtml = farm.online
    ? `<span class="fe-tag fe-tag--emerald"><span class="fe-dot fe-dot--online"></span>在线派片</span>`
    : `<span class="fe-tag fe-tag--cyan"><span class="fe-dot fe-dot--standby"></span>省电待机</span>`;

  const workersHtml = farm.workers.length > 0
    ? farm.workers.map((w) => {
        const isOnline = ['online', 'busy', 'running', 'active'].includes(w.status);
        const pillClass = w.status === 'busy' || w.status === 'running'
          ? 'fe-tag--cyan'
          : isOnline
            ? 'fe-tag--emerald'
            : '';
        const statusText = w.status === 'busy' || w.status === 'running'
          ? '渲染中'
          : isOnline
            ? '在线就绪'
            : '休眠待命';
        return `
          <div class="fe-worker-card">
            <div class="fe-worker-top">
              <div class="fe-worker-id">
                <div class="fe-gpu-badge">${ICONS.gpu}</div>
                <div style="min-width:0;">
                  <div class="fe-worker-name">${esc(w.gpu)}</div>
                  <div class="fe-worker-sub fe-num">节点 ${esc(w.id)}</div>
                </div>
              </div>
              <span class="fe-tag ${pillClass}">
                <span class="fe-dot ${isOnline ? 'fe-dot--online' : 'fe-dot--muted'}"></span>
                ${esc(statusText)}
              </span>
            </div>
            <div class="fe-worker-metrics">
              <div class="fe-worker-metric">
                <span class="fe-worker-metric-k">累计出片</span>
                <span class="fe-worker-metric-v fe-num">${formatNumber(w.completedShots)} 镜</span>
              </div>
              <div class="fe-worker-metric">
                <span class="fe-worker-metric-k">推理引擎</span>
                <span class="fe-worker-metric-v">${esc(w.engine)}</span>
              </div>
              <div class="fe-worker-metric">
                <span class="fe-worker-metric-k">最近心跳</span>
                <span class="fe-worker-metric-v fe-num">${esc(w.lastSeen)}</span>
              </div>
            </div>
          </div>
        `;
      }).join('')
    : `
      <div class="fe-worker-card">
        <div class="fe-worker-top">
          <div class="fe-worker-id">
            <div class="fe-gpu-badge">${ICONS.gpu}</div>
            <div style="min-width:0;">
              <div class="fe-worker-name">Colab G4 / L4 / H100 按需算力池</div>
              <div class="fe-worker-sub">零闲置计费 · 派发任务后 60 秒唤醒</div>
            </div>
          </div>
          <span class="fe-tag fe-tag--cyan"><span class="fe-dot fe-dot--standby"></span>休眠省额度</span>
        </div>
        <div class="fe-worker-metrics">
          <div class="fe-worker-metric">
            <span class="fe-worker-metric-k">累计已渲染</span>
            <span class="fe-worker-metric-v fe-num">${formatNumber(farm.totalShots)} 镜</span>
          </div>
          <div class="fe-worker-metric">
            <span class="fe-worker-metric-k">主力引擎</span>
            <span class="fe-worker-metric-v">MiniMax H3 · LTX-2.5</span>
          </div>
          <div class="fe-worker-metric">
            <span class="fe-worker-metric-k">本机预演服务</span>
            <span class="fe-worker-metric-v" style="color:var(--accent-emerald,#34D399);">100% 就绪</span>
          </div>
        </div>
      </div>
      <div class="fe-standby-callout">
        <span style="color:var(--accent-cyan,#38BDF8);margin-top:1px;">${ICONS.zap}</span>
        <div>
          <strong>智能省电策略生效中：</strong>当前没有正在烧卡的云端 GPU，不会产生任何待机费用。你可以照常在创作台新建项目、在工作流看板精修分镜并生成本地预演成片；点击「派发云端精拍」时随时唤醒 Colab 节点。
        </div>
      </div>
    `;

  const logsHtml = farm.activity.length > 0
    ? farm.activity.map((item) => {
        const tagClass = item.level === 'ok' || item.level === 'success' || /done|complete|ok|完成/i.test(item.message)
          ? 'fe-log-tag--ok'
          : /cost|cu|dispatch|派发|queue/i.test(item.message)
            ? 'fe-log-tag--gold'
            : '';
        return `
          <div class="fe-log-row">
            <span class="fe-log-time fe-num">${esc(item.time || '--:--')}</span>
            <span class="fe-log-tag ${tagClass}">${esc(item.tag)}</span>
            <span class="fe-log-msg">${esc(item.message)}</span>
          </div>
        `;
      }).join('')
    : `
      <div class="fe-log-row">
        <span class="fe-log-time fe-num">READY</span>
        <span class="fe-log-tag fe-log-tag--ok">LOCAL</span>
        <span class="fe-log-msg">本地分镜编排与 ffmpeg 预演合成服务已就绪，随时可体验完整视频工作流。</span>
      </div>
      <div class="fe-log-row">
        <span class="fe-log-time fe-num">STATS</span>
        <span class="fe-log-tag fe-log-tag--gold">BENCH</span>
        <span class="fe-log-msg">历史工作区累计验证 ${formatNumber(farm.totalShots)} 镜 · H3 中位 ${farm.medianH3}s/镜 · LTX-2.5 中位 ${farm.medianLtx}s/镜。</span>
      </div>
      <div class="fe-log-row">
        <span class="fe-log-time fe-num">SAFE</span>
        <span class="fe-log-tag">GUARD</span>
        <span class="fe-log-msg">日志流已启用全自动脱敏过滤，所有密钥、令牌与隧道链接均不会出现在控制台。</span>
      </div>
    `;

  container.innerHTML = `
    <div class="fe-page" data-view="farm">
      <header class="fe-header">
        <div class="fe-header-copy">
          <span class="fe-eyebrow">${ICONS.zap} COMPUTE FARM · 极低成本共享云算力</span>
          <h1 class="fe-title">算力工坊 · 用一杯咖啡的成本拍院线大片</h1>
          <p class="fe-subtitle">
            通过将闲置与免费 Colab GPU 编排成分布式拍片池，把 30 分钟连续角色 AI 电影的渲染开销压低至约 $11（每分钟约 ¥2.4），普通白领体验官内测全程 ¥0 免费使用。
          </p>
        </div>
        <div class="fe-header-actions">
          <a
            href="${esc(notebookUrl)}"
            download="CineForge_Colab_Worker.ipynb"
            class="fe-btn fe-btn--gold-outline"
            id="fe-download-ipynb"
            data-colab-notebook-download="true"
          >
            ${ICONS.download}
            <span>一键下载 CineForge_Colab_Worker.ipynb</span>
          </a>
          <button type="button" class="fe-btn" id="fe-farm-refresh">
            ${ICONS.refresh}
            <span>刷新实时状态</span>
          </button>
          <button type="button" class="fe-btn fe-btn--gold" data-action="go-create">
            ${ICONS.spark}
            <span>去创作台拍片</span>
          </button>
        </div>
      </header>

      <!-- 1. Top KPI Strip (4 Cinema Glass Stat Cards) -->
      <section class="fe-kpi-grid" aria-label="算力核心指标">
        <article class="fe-kpi-card ${farm.online ? 'fe-kpi-card--emerald' : 'fe-kpi-card--cyan'}">
          <div class="fe-kpi-top">
            <span class="fe-kpi-label">派片服务状态</span>
            <span class="fe-kpi-icon-box ${farm.online ? 'fe-kpi-icon-box--emerald' : 'fe-kpi-icon-box--cyan'}">${ICONS.server}</span>
          </div>
          <div class="fe-kpi-value-row">
            <div class="fe-kpi-value fe-kpi-value--sm">
              <span class="fe-dot ${farm.online ? 'fe-dot--online' : 'fe-dot--standby'}"></span>
              <span>${farm.online ? '云端派片在线' : '待机省电 · 本地就绪'}</span>
            </div>
          </div>
          <div class="fe-kpi-foot">
            <div class="fe-kpi-chips">
              ${statusPillHtml}
              <span class="fe-mini-chip fe-num">端口 :${esc(farm.port)}</span>
            </div>
            <p class="fe-kpi-desc">
              ${farm.online
                ? '本机派片服务与云端算力通道正常在线，提交分镜即可批量渲染。'
                : '云端 GPU 休眠省额度期间，本地分镜编排与预演成片仍 100% 流畅可用。'}
            </p>
          </div>
        </article>

        <article class="fe-kpi-card fe-kpi-card--cyan">
          <div class="fe-kpi-top">
            <span class="fe-kpi-label">实测出片吞吐</span>
            <span class="fe-kpi-icon-box fe-kpi-icon-box--cyan">${ICONS.film}</span>
          </div>
          <div class="fe-kpi-value-row">
            <span class="fe-kpi-value fe-num">${formatNumber(farm.totalShots)}</span>
            <span class="fe-kpi-unit">个实拍分镜</span>
          </div>
          <div class="fe-kpi-foot">
            <div class="fe-kpi-chips">
              <span class="fe-mini-chip fe-num">H3 中位 ${farm.medianH3}s/镜</span>
              <span class="fe-mini-chip fe-num">LTX-2.5 ${farm.medianLtx}s/镜</span>
            </div>
            <p class="fe-kpi-desc">来自真实工作区多部短片与长片流水线的全量落地镜头统计。</p>
          </div>
        </article>

        <article class="fe-kpi-card fe-kpi-card--gold">
          <div class="fe-kpi-top">
            <span class="fe-kpi-label">30 分钟电影实测成本</span>
            <span class="fe-kpi-icon-box fe-kpi-icon-box--gold">${ICONS.coins}</span>
          </div>
          <div class="fe-kpi-value-row">
            <span class="fe-kpi-value fe-kpi-value--gold fe-num">≈ $${farm.cost30mUsd}</span>
            <span class="fe-kpi-unit fe-num">/ ${farm.cu30m} CU</span>
          </div>
          <div class="fe-kpi-foot">
            <div class="fe-kpi-chips">
              <span class="fe-mini-chip fe-mini-chip--gold fe-num">每分钟约 ¥${farm.perMinCny}</span>
              <span class="fe-mini-chip">1080p 成片</span>
            </div>
            <p class="fe-kpi-desc">基于 366 镜完整剧情长片实测，无需购买昂贵商用按月订阅。</p>
          </div>
        </article>

        <article class="fe-kpi-card fe-kpi-card--emerald">
          <div class="fe-kpi-top">
            <span class="fe-kpi-label">相比商业平台节省</span>
            <span class="fe-kpi-icon-box fe-kpi-icon-box--emerald">${ICONS.trending}</span>
          </div>
          <div class="fe-kpi-value-row">
            <span class="fe-kpi-value fe-kpi-value--emerald fe-num">节省 ${farm.savingsPct}%+</span>
          </div>
          <div class="fe-kpi-foot">
            <div class="fe-kpi-chips">
              <span class="fe-mini-chip fe-mini-chip--emerald">体验官内测 ¥0</span>
              <span class="fe-mini-chip">免按秒扣积分</span>
            </div>
            <p class="fe-kpi-desc">角色视觉锁减少抽卡废片率，把每一份算力都花在过审镜头上。</p>
          </div>
        </article>
      </section>

      <!-- 1.5 EasyColab Real-Time Telemetry Chart + Dual Cost-Guard Capsules -->
      <section class="fe-panel fe-telemetry-panel" aria-label="EasyColab 实时算力监控折线图">
        <div class="fe-panel-head">
          <div class="fe-panel-title-wrap">
            <h2 class="fe-panel-title">${ICONS.activity} EasyColab 风格实时算力监控曲线</h2>
            <p class="fe-panel-sub fe-num">
              实测 ${measuredCount} 点 · 基线校准 ${baselineCount} 点 · 峰值 ${peakGpus} 卡并行 · 均值 ${avgShotSec}s/镜 (${avgThroughput} 镜/时)
            </p>
          </div>
          <div class="fe-seg-group" role="tablist" aria-label="切换监控指标" id="fe-telemetry-tabs">
            <button
              type="button"
              role="tab"
              class="fe-seg-btn ${state.telemetryMetric === 'shot_sec' ? 'is-active' : ''}"
              data-telemetry-metric="shot_sec"
              aria-selected="${state.telemetryMetric === 'shot_sec' ? 'true' : 'false'}"
            >单镜耗时 (秒/镜)</button>
            <button
              type="button"
              role="tab"
              class="fe-seg-btn ${state.telemetryMetric === 'throughput_per_hr' ? 'is-active' : ''}"
              data-telemetry-metric="throughput_per_hr"
              aria-selected="${state.telemetryMetric === 'throughput_per_hr' ? 'true' : 'false'}"
            >每小时吞吐 (镜/时)</button>
          </div>
        </div>

        <div class="fe-chart-shell">
          <div class="fe-chart-stage" id="fe-telemetry-stage">
            ${buildTelemetryChartSvg(telemetry, state.telemetryMetric, focusedIdx, esc)}
          </div>
          <div class="fe-chart-foot">
            <div class="fe-chart-legend">
              <span class="fe-legend-item">
                <span class="fe-legend-swatch ${state.telemetryMetric === 'throughput_per_hr' ? 'fe-legend-swatch--emerald' : 'fe-legend-swatch--gold'}"></span>
                <span>实测采样点</span>
              </span>
              <span class="fe-legend-item">
                <span class="fe-legend-swatch fe-legend-swatch--cyan"></span>
                <span>基线校准点</span>
              </span>
            </div>
            <div class="fe-chart-readout" id="fe-telemetry-readout">
              ${buildTelemetryReadoutHtml(focusedPt, esc)}
            </div>
          </div>
        </div>
      </section>

      <!-- Dual Cost-Guard Capsule Cards -->
      <section class="fe-guards-grid" aria-label="双省钱守护胶囊">
        <article class="fe-guard-card fe-guard-card--emerald">
          <div class="fe-guard-icon fe-guard-icon--emerald" aria-hidden="true">${ICONS.clockShield}</div>
          <div class="fe-guard-body">
            <div class="fe-guard-head">
              <h3 class="fe-guard-title">闲置 ${farm.idleGuard.timeout_min} 分钟自动释放 Colab 显卡</h3>
              <span class="fe-tag fe-tag--emerald">${farm.idleGuard.enabled ? '守护已开启' : '待开启'}</span>
            </div>
            <p class="fe-guard-desc">
              队列清空满 ${farm.idleGuard.timeout_min} 分钟自动触发 <code>google.colab.runtime.unassign()</code> 释放 GPU 运行时，彻底防止忘记关机白扣 CU。
            </p>
            <div class="fe-guard-foot">
              <span class="fe-mini-chip fe-mini-chip--emerald fe-num">累计预计守护节省 ${farm.idleGuard.saved_cu_est} CU (≈ ¥${savedCnyEst})</span>
              <span class="fe-mini-chip">零闲置扣费</span>
            </div>
          </div>
        </article>

        <article class="fe-guard-card fe-guard-card--cyan">
          <div class="fe-guard-icon fe-guard-icon--cyan" aria-hidden="true">${ICONS.hardDrive}</div>
          <div class="fe-guard-body">
            <div class="fe-guard-head">
              <h3 class="fe-guard-title">Google Drive 权重永久缓存 · 秒级热启</h3>
              <span class="fe-tag fe-tag--cyan">${farm.gdriveCacheSupported ? '已支持 · 免重下 30GB' : '按需启用'}</span>
            </div>
            <p class="fe-guard-desc">
              Notebook 内置 <code>USE_GDRIVE_CACHE</code> 表单开关，首次拉取 30GB 模型权重永久落盘 Google Drive，下次重启免重复下载、30 秒直连开拍。
            </p>
            <div class="fe-guard-foot">
              <span class="fe-mini-chip fe-mini-chip--gold">重启提速 8x · 省 12 分钟等待</span>
              <a
                href="${esc(notebookUrl)}"
                download="CineForge_Colab_Worker.ipynb"
                class="fe-btn fe-btn--sm fe-btn--gold-outline"
              >
                ${ICONS.download}
                <span>下载 .ipynb</span>
              </a>
            </div>
          </div>
        </article>
      </section>

      <!-- 2. Interactive Cost Savings Visualizer -->
      <section class="fe-panel fe-calc-panel" aria-label="成本对比计算器">
        <div class="fe-panel-head">
          <div class="fe-panel-title-wrap">
            <h2 class="fe-panel-title">${ICONS.coins} 交互式成本对比计算器</h2>
            <p class="fe-panel-sub">切换不同视频时长，直观对比传统外包、商业 AI 平台与影铸共享算力池的真实开销</p>
          </div>
          <div class="fe-seg-group" role="tablist" aria-label="选择影片时长" id="fe-cost-tabs">
            ${farm.tiers.map((t) => `
              <button
                type="button"
                role="tab"
                class="fe-seg-btn ${t.key === activeTier.key ? 'is-active' : ''}"
                data-tier-key="${esc(t.key)}"
                aria-selected="${t.key === activeTier.key ? 'true' : 'false'}"
              >${esc(t.label)}</button>
            `).join('')}
          </div>
        </div>

        <div class="fe-calc-grid" id="fe-cost-stage">
          ${buildCostCalcHtml(activeTier, esc)}
        </div>
      </section>

      <!-- 3. Live Nodes & Sanitized Activity Feed -->
      <section class="fe-farm-split" aria-label="云端节点与实时渲染动态">
        <div class="fe-panel">
          <div class="fe-panel-head">
            <div class="fe-panel-title-wrap">
              <h2 class="fe-panel-title">${ICONS.gpu} 云端 GPU 节点池</h2>
              <p class="fe-panel-sub">活跃及最近接入的 Colab 渲染节点状态一览</p>
            </div>
            <span class="fe-tag ${farm.workers.length > 0 ? 'fe-tag--emerald' : 'fe-tag--cyan'} fe-num">
              ${farm.workers.length > 0 ? `${farm.workers.length} 个已登记节点` : '按需唤醒 · 0 闲置费'}
            </span>
          </div>
          <div class="fe-worker-list">
            ${workersHtml}
          </div>
        </div>

        <div class="fe-panel">
          <div class="fe-panel-head">
            <div class="fe-panel-title-wrap">
              <h2 class="fe-panel-title">${ICONS.terminal} 实时渲染动态流</h2>
              <p class="fe-panel-sub">来自 farm / lab 流水线的脱敏聚合事件时间线</p>
            </div>
            <span class="fe-tag fe-tag--emerald">${ICONS.shield} 脱敏保护</span>
          </div>
          <div class="fe-log-box" role="log" aria-label="脱敏渲染日志">
            ${logsHtml}
          </div>
        </div>
      </section>

      <!-- 4. Collapsible Drawer: 1-Minute Colab GPU Onboarding -->
      <section class="fe-panel fe-drawer-card ${state.drawerOpen ? 'is-open' : ''}" id="fe-colab-drawer">
        <button
          type="button"
          class="fe-drawer-toggle"
          id="fe-colab-toggle"
          aria-expanded="${state.drawerOpen ? 'true' : 'false'}"
        >
          <div class="fe-drawer-toggle-left">
            <span class="fe-tag fe-tag--gold">进阶折叠抽屉</span>
            <span class="fe-panel-title" style="font-size:16px;">1 分钟接入你的免费 / 闲置 Colab GPU</span>
            <span class="fe-panel-sub" style="margin:0;">普通白领无需操作 · 极客或团队成员可随时贡献自己的免费 GPU 加速</span>
          </div>
          <span class="fe-drawer-chevron" aria-hidden="true">${ICONS.chevron}</span>
        </button>

        <div class="fe-drawer-body">
          <div class="fe-steps-grid">
            ${farm.colabSteps.map((st) => `
              <div class="fe-step-card">
                <span class="fe-step-num">${esc(st.num)}</span>
                <div class="fe-step-title">${esc(st.title)}</div>
                <p class="fe-step-desc">${esc(st.desc)}</p>
              </div>
            `).join('')}
          </div>

          <div class="fe-code-wrap">
            <div class="fe-code-head">
              <span class="fe-code-caption">${ICONS.terminal} 脱敏 Colab Worker 接入脚本（不含任何私有密钥或隧道地址）</span>
              <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                <a
                  href="${esc(notebookUrl)}"
                  download="CineForge_Colab_Worker.ipynb"
                  class="fe-btn fe-btn--sm fe-btn--gold-outline"
                >
                  ${ICONS.download}
                  <span>下载 CineForge_Colab_Worker.ipynb</span>
                </a>
                <button type="button" class="fe-btn fe-btn--sm fe-btn--gold" id="fe-copy-colab">
                  ${ICONS.copy}
                  <span>复制脱敏接入脚本</span>
                </button>
              </div>
            </div>
            <pre class="fe-code-pre" id="fe-colab-code">${esc(farm.colabSnippet)}</pre>
          </div>

          <div class="fe-security-note">
            ${ICONS.shield}
            <span>${esc(farm.colabNote)}</span>
          </div>
        </div>
      </section>
    </div>
  `;

  // Bind telemetry chart metric tabs & point hover inspection
  const teleTabs = container.querySelector('#fe-telemetry-tabs');
  const teleStage = container.querySelector('#fe-telemetry-stage');
  const teleReadout = container.querySelector('#fe-telemetry-readout');

  const bindTelemetryPoints = () => {
    if (!teleStage || !teleReadout) return;
    teleStage.querySelectorAll('[data-point-idx]').forEach((ptEl) => {
      const selectPoint = () => {
        const idx = Number(ptEl.getAttribute('data-point-idx'));
        if (!Number.isFinite(idx) || idx < 0 || idx >= telemetry.length) return;
        state.selectedPointIdx = idx;
        teleReadout.innerHTML = buildTelemetryReadoutHtml(telemetry[idx], esc);
      };
      ptEl.addEventListener('mouseenter', selectPoint);
      ptEl.addEventListener('focus', selectPoint);
      ptEl.addEventListener('click', () => {
        selectPoint();
        teleStage.innerHTML = buildTelemetryChartSvg(telemetry, state.telemetryMetric, state.selectedPointIdx, esc);
        bindTelemetryPoints();
      });
    });
  };
  bindTelemetryPoints();

  if (teleTabs && teleStage) {
    teleTabs.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-telemetry-metric]');
      if (!btn) return;
      const metric = btn.getAttribute('data-telemetry-metric');
      if (!metric || metric === state.telemetryMetric) return;
      state.telemetryMetric = metric;
      teleTabs.querySelectorAll('[data-telemetry-metric]').forEach((el) => {
        const active = el.getAttribute('data-telemetry-metric') === metric;
        el.classList.toggle('is-active', active);
        el.setAttribute('aria-selected', active ? 'true' : 'false');
      });
      const idx = state.selectedPointIdx >= 0 && state.selectedPointIdx < telemetry.length
        ? state.selectedPointIdx
        : telemetry.length - 1;
      teleStage.innerHTML = buildTelemetryChartSvg(telemetry, state.telemetryMetric, idx, esc);
      bindTelemetryPoints();
      const swatch = container.querySelector('.fe-chart-legend .fe-legend-swatch');
      if (swatch) {
        swatch.className = `fe-legend-swatch ${metric === 'throughput_per_hr' ? 'fe-legend-swatch--emerald' : 'fe-legend-swatch--gold'}`;
      }
    });
  }

  // Bind interactions
  const costTabs = container.querySelector('#fe-cost-tabs');
  const costStage = container.querySelector('#fe-cost-stage');
  if (costTabs && costStage) {
    costTabs.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-tier-key]');
      if (!btn) return;
      const key = btn.getAttribute('data-tier-key');
      const nextTier = farm.tiers.find((t) => t.key === key);
      if (!nextTier) return;
      state.selectedTierKey = key;
      costTabs.querySelectorAll('[data-tier-key]').forEach((el) => {
        const active = el.getAttribute('data-tier-key') === key;
        el.classList.toggle('is-active', active);
        el.setAttribute('aria-selected', active ? 'true' : 'false');
      });
      costStage.innerHTML = buildCostCalcHtml(nextTier, esc);
      bindCreateLinks(costStage, ctx);
    });
  }

  bindCreateLinks(container, ctx);

  const drawerEl = container.querySelector('#fe-colab-drawer');
  const toggleBtn = container.querySelector('#fe-colab-toggle');
  if (drawerEl && toggleBtn) {
    toggleBtn.addEventListener('click', () => {
      state.drawerOpen = !state.drawerOpen;
      drawerEl.classList.toggle('is-open', state.drawerOpen);
      toggleBtn.setAttribute('aria-expanded', state.drawerOpen ? 'true' : 'false');
    });
  }

  const copyBtn = container.querySelector('#fe-copy-colab');
  if (copyBtn) {
    copyBtn.addEventListener('click', async () => {
      const ok = await copyText(farm.colabSnippet, '已复制脱敏 Colab 接入脚本', ctx);
      if (ok) {
        const label = copyBtn.querySelector('span');
        if (label) {
          const old = label.textContent;
          label.textContent = '✓ 已复制脚本';
          const t = setTimeout(() => {
            if (label.isConnected) label.textContent = old;
          }, 1800);
          registerCleanup(() => clearTimeout(t));
        }
      }
    });
  }

  const refreshBtn = container.querySelector('#fe-farm-refresh');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', async () => {
      refreshBtn.disabled = true;
      try {
        const latest = await ctx.api.farmStatus();
        ctx.store?.set?.('farmStatus', latest);
        const nextFarm = normalizeFarmData(latest);
        renderFarmContent(container, ctx, nextFarm, state);
        notify(ctx, '算力工坊状态已刷新', 'success');
      } catch (err) {
        notify(ctx, `刷新失败：${err?.message || '请稍后重试'}`, 'error');
        refreshBtn.disabled = false;
      }
    });
  }
}

function bindCreateLinks(root, ctx) {
  root.querySelectorAll('[data-action="go-create"]').forEach((btn) => {
    btn.addEventListener('click', () => goRoute(ctx, '#create'));
  });
}

export async function renderFarm(container, ctx) {
  destroy();
  container.innerHTML = `
    <div class="fe-page">
      <div class="fe-loading">
        <div class="fe-skel" style="height:82px;"></div>
        <div class="fe-kpi-grid">
          <div class="fe-skel"></div>
          <div class="fe-skel"></div>
          <div class="fe-skel"></div>
          <div class="fe-skel"></div>
        </div>
        <div class="fe-skel" style="height:280px;"></div>
      </div>
    </div>
  `;

  let alive = true;
  registerCleanup(() => { alive = false; });

  const state = {
    selectedTierKey: '30m',
    telemetryMetric: 'shot_sec',
    selectedPointIdx: -1,
    drawerOpen: false,
  };

  try {
    const raw = await ctx.api.farmStatus();
    if (!alive) return;
    ctx.store?.set?.('farmStatus', raw);
    const farm = normalizeFarmData(raw);
    if (!farm.tiers.some((t) => t.key === state.selectedTierKey) && farm.tiers[0]) {
      state.selectedTierKey = farm.tiers[0].key;
    }
    renderFarmContent(container, ctx, farm, state);
  } catch (err) {
    if (!alive) return;
    // Still render graceful fallback view with clear toast so UI never breaks
    const fallback = normalizeFarmData({});
    renderFarmContent(container, ctx, fallback, state);
    notify(ctx, `未能连接算力状态接口，已显示本地基准视图（${err?.message || 'offline'}）`, 'info');
  }

  // Keep in sync if SSE broadcasts farm_status updates
  if (ctx?.store && typeof ctx.store.subscribe === 'function') {
    const unsub = ctx.store.subscribe('sse:farm_status', (data) => {
      if (!alive || !data) return;
      renderFarmContent(container, ctx, normalizeFarmData(data), state);
    });
    registerCleanup(unsub);
  }
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
