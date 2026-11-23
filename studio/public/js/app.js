/**
 * CineForge Studio — Minimal 3-Tab Router, Honest Live Status Pill & Video Lightbox
 */

import {
  api,
  store,
  connectEvents,
  toast,
  escHtml,
  formatSec,
  setInviteCode,
} from '/js/api.js';

const ROUTE_META = {
  studio: {
    title: '生成视频',
    module: '/js/views/studio.js',
    exportName: 'render',
  },
  create: {
    title: '生成视频',
    module: '/js/views/studio.js',
    exportName: 'render',
  },
  workflow: {
    title: '工作流',
    module: '/js/views/kanban.js',
    exportName: 'render',
  },
  farm: {
    title: '连接 Colab',
    module: '/js/views/farm_eval.js',
    exportName: 'renderFarm',
  },
  discover: {
    title: '样片库',
    module: '/js/views/discover.js',
    exportName: 'render',
  },
  eval: {
    title: '体验反馈',
    module: '/js/views/farm_eval.js',
    exportName: 'renderEval',
  },
};

const moduleCache = new Map();
let activeDestroy = null;
let renderSeq = 0;
let sseConn = null;
let statusTimer = null;

function parseHash(rawHash) {
  const cleaned = (rawHash || '').replace(/^#\/?/, '');
  const qIdx = cleaned.indexOf('?');
  const pathPart = qIdx >= 0 ? cleaned.slice(0, qIdx) : cleaned;
  const queryPart = qIdx >= 0 ? cleaned.slice(qIdx + 1) : '';

  const segments = pathPart.split('/').filter(Boolean);
  const rawRoute = (segments[0] || 'studio').toLowerCase();
  const route = ROUTE_META[rawRoute] ? rawRoute : 'studio';

  const query = {};
  if (queryPart) {
    const sp = new URLSearchParams(queryPart);
    for (const [k, v] of sp.entries()) {
      query[k] = v;
    }
  }

  let projectId = null;
  if (route === 'workflow') {
    if (segments[1]) {
      try {
        projectId = decodeURIComponent(segments[1]);
      } catch {
        projectId = segments[1];
      }
    } else if (query.project) {
      projectId = query.project;
    }
  }

  return { route, projectId, query };
}

export function navigate(target) {
  if (!target) return;
  const normalized = target.startsWith('#') ? target : `#${target.replace(/^\/+/, '')}`;
  if (window.location.hash === normalized) {
    renderCurrentRoute();
  } else {
    window.location.hash = normalized;
  }
}

/* ==========================================================================
   Global Video Lightbox Modal
   ========================================================================== */
const modalState = {
  open: false,
  videoUrl: '',
  sideBySideUrl: '',
  posterUrl: '',
  mode: 'clean',
  onClone: null,
  cloneQuery: null,
  onWorkflow: null,
  projectId: null,
};

function getModalEls() {
  return {
    root: document.getElementById('video-modal'),
    title: document.getElementById('video-modal-title'),
    subtitle: document.getElementById('video-modal-subtitle'),
    badges: document.getElementById('video-modal-badges'),
    player: document.getElementById('video-modal-player'),
    modeChip: document.getElementById('video-modal-mode-chip'),
    modeSwitch: document.getElementById('video-modal-mode-switch'),
    closeBtn: document.getElementById('video-modal-close'),
    cloneBtn: document.getElementById('video-modal-clone-btn'),
    workflowBtn: document.getElementById('video-modal-workflow-btn'),
  };
}

function applyVideoMode(mode, preserveTime = false) {
  const els = getModalEls();
  if (!els.player) return;

  const hasSide = Boolean(modalState.sideBySideUrl);
  const nextMode = mode === 'side_by_side' && hasSide ? 'side_by_side' : 'clean';
  modalState.mode = nextMode;

  const targetUrl =
    nextMode === 'side_by_side'
      ? modalState.sideBySideUrl
      : modalState.videoUrl || modalState.sideBySideUrl;

  const prevTime = preserveTime && Number.isFinite(els.player.currentTime) ? els.player.currentTime : 0;
  const wasPlaying = preserveTime ? !els.player.paused : true;

  if (modalState.posterUrl) {
    els.player.setAttribute('poster', modalState.posterUrl);
  } else {
    els.player.removeAttribute('poster');
  }

  if (targetUrl && els.player.getAttribute('src') !== targetUrl) {
    els.player.setAttribute('src', targetUrl);
    els.player.load();
  }

  if (preserveTime && prevTime > 0) {
    const restore = () => {
      try {
        if (Number.isFinite(els.player.duration) && prevTime < els.player.duration) {
          els.player.currentTime = prevTime;
        }
      } catch {
        // ignore
      }
      if (wasPlaying) els.player.play().catch(() => {});
    };
    els.player.addEventListener('loadedmetadata', restore, { once: true });
  } else if (targetUrl) {
    els.player.play().catch(() => {});
  }

  if (els.modeSwitch) {
    els.modeSwitch.hidden = !hasSide;
    els.modeSwitch.querySelectorAll('[data-video-mode]').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.videoMode === nextMode);
    });
  }
  if (els.modeChip) {
    els.modeChip.hidden = !hasSide;
    els.modeChip.textContent = nextMode === 'side_by_side' ? '左右原片对照版' : '纯净成片版';
  }
}

export function openVideoModal(opts = {}) {
  const {
    title = '成片播放',
    subtitle = '',
    videoUrl = '',
    sideBySideUrl = '',
    posterUrl = '',
    badges = [],
    onClone = null,
    cloneQuery = null,
    projectId = null,
    onWorkflow = null,
    initialMode = 'clean',
  } = opts;

  const els = getModalEls();
  if (!els.root) return;

  if (!videoUrl && !sideBySideUrl) {
    toast('当前影片暂未生成可播放视频文件', 'warning');
    return;
  }

  modalState.open = true;
  modalState.videoUrl = videoUrl || '';
  modalState.sideBySideUrl = sideBySideUrl || '';
  modalState.posterUrl = posterUrl || '';
  modalState.onClone = typeof onClone === 'function' ? onClone : null;
  modalState.cloneQuery = cloneQuery || null;
  modalState.projectId = projectId || null;
  modalState.onWorkflow = typeof onWorkflow === 'function' ? onWorkflow : null;

  els.title.textContent = title;
  els.subtitle.textContent = subtitle || '';
  els.subtitle.hidden = !subtitle;

  const badgeItems = Array.isArray(badges) ? badges : [];
  els.badges.innerHTML = badgeItems
    .map((b) => {
      if (typeof b === 'string') return `<span class="badge">${escHtml(b)}</span>`;
      const cls = b.variant ? `badge badge-${escHtml(b.variant)}` : 'badge';
      return `<span class="${cls}">${escHtml(b.label || b.text || '')}</span>`;
    })
    .join('');
  els.badges.hidden = badgeItems.length === 0;

  els.cloneBtn.hidden = !(modalState.onClone || modalState.cloneQuery);
  els.workflowBtn.hidden = !(modalState.onWorkflow || modalState.projectId);

  els.root.classList.add('open');
  els.root.setAttribute('aria-hidden', 'false');
  document.body.style.overflow = 'hidden';

  applyVideoMode(initialMode, false);
}

export function closeVideoModal() {
  if (!modalState.open) return;
  const els = getModalEls();
  modalState.open = false;

  if (els.player) {
    try {
      els.player.pause();
      els.player.removeAttribute('src');
      els.player.load();
    } catch {
      // ignore
    }
  }
  if (els.root) {
    els.root.classList.remove('open');
    els.root.setAttribute('aria-hidden', 'true');
  }
  document.body.style.overflow = '';
}

function setupVideoModal() {
  const els = getModalEls();
  if (!els.root) return;

  els.closeBtn?.addEventListener('click', closeVideoModal);
  els.root.addEventListener('click', (ev) => {
    if (ev.target === els.root) closeVideoModal();
  });

  els.modeSwitch?.addEventListener('click', (ev) => {
    const btn = ev.target.closest('[data-video-mode]');
    if (!btn) return;
    applyVideoMode(btn.dataset.videoMode, true);
  });

  els.cloneBtn?.addEventListener('click', () => {
    const fn = modalState.onClone;
    const cq = modalState.cloneQuery;
    closeVideoModal();
    if (fn) fn();
    else if (cq) navigate(`#studio?${cq.replace(/^\?/, '')}`);
  });

  els.workflowBtn?.addEventListener('click', () => {
    const fn = modalState.onWorkflow;
    const pid = modalState.projectId;
    closeVideoModal();
    if (fn) fn();
    else if (pid) navigate(`#workflow/${encodeURIComponent(pid)}`);
  });

  window.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape' && modalState.open) closeVideoModal();
  });
}

/* ==========================================================================
   Honest Live Status Pill & Session Sync
   ========================================================================== */
function applySessionUI(sess) {
  if (!sess || typeof sess !== 'object') return;
  store.set('session', sess);
  const isGuestServer = sess.mode === 'guest' || Boolean(sess.guest_mode);
  if (isGuestServer) {
    document.body.classList.add('is-server-guest');
  }
  const rem = Number.isFinite(Number(sess.remaining_cloud_jobs)) ? Number(sess.remaining_cloud_jobs) : 3;
  const maxJobs = Number.isFinite(Number(sess.max_guest_jobs)) ? Number(sess.max_guest_jobs) : 3;
  const topQuota = document.getElementById('topbar-guest-quota');
  if (topQuota) {
    topQuota.textContent = `免费额度 ${rem}/${maxJobs}`;
  }
}

function applyLiveTopbarStatus(snapshot) {
  const pill = document.getElementById('topbar-farm-pill');
  const dot = document.getElementById('topbar-farm-dot');
  const text = document.getElementById('topbar-farm-text');
  if (!pill || !dot || !text) return;

  const tasks = Array.isArray(snapshot?.tasks) ? snapshot.tasks : [];
  const activeTask = tasks.find((t) =>
    ['rendering', 'assembling', 'previewing', 'queued'].includes(t.overall_status)
  );
  const queuedOffline = tasks.find((t) => t.overall_status === 'queued_offline');
  const colabConnected = Boolean(snapshot?.colab_connected);
  const gpuCount = Number(snapshot?.online_gpu_count || 0);
  const farmOnline = Boolean(snapshot?.farm_server_online ?? snapshot?.online ?? snapshot?.farm_online);

  pill.classList.remove('is-online', 'is-busy', 'is-waiting');

  if (activeTask) {
    pill.classList.add('is-busy');
    pill.setAttribute('href', '#studio');
    dot.className = 'status-dot gold';
    text.textContent = `生成中 ${activeTask.overall_progress || 0}%`;
  } else if (colabConnected) {
    pill.classList.add('is-online');
    pill.setAttribute('href', '#farm');
    dot.className = 'status-dot online';
    text.textContent = `Colab 在线 (${gpuCount} GPU)`;
  } else if (queuedOffline) {
    pill.classList.add('is-waiting');
    pill.setAttribute('href', '#farm');
    dot.className = 'status-dot cyan';
    text.textContent = '任务排队中 · 请连接 Colab';
  } else if (farmOnline) {
    pill.classList.add('is-waiting');
    pill.setAttribute('href', '#farm');
    dot.className = 'status-dot cyan';
    text.textContent = '派片就绪 · 等待 Colab';
  } else {
    pill.setAttribute('href', '#farm');
    dot.className = 'status-dot muted';
    text.textContent = 'Colab 未连接';
  }
}

async function refreshGlobalStatus() {
  try {
    const snap = await api.tasks();
    store.set('liveTasks', snap);
    applyLiveTopbarStatus(snap);
  } catch {
    // Keep last known status silently
  }
}

async function hydrateSession(force = false) {
  try {
    const sess = await store.getOrFetch('session', () => api.session(), { force, ttlMs: 10000 });
    applySessionUI(sess);
    return sess;
  } catch {
    return null;
  }
}

function updateActiveNav(route) {
  const navRoute = route === 'create' ? 'studio' : route;
  document.querySelectorAll('.topnav .topnav-item').forEach((link) => {
    const isActive = link.dataset.route === navRoute;
    link.classList.toggle('active', isActive);
    if (isActive) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
}

/* ==========================================================================
   View Loader & Router
   ========================================================================== */
function renderLoadingSkeleton(container) {
  container.innerHTML = `
    <div class="flex-col gap-4" aria-busy="true">
      <div class="skeleton" style="height: 44px; width: 280px; border-radius: 12px;"></div>
      <div class="skeleton" style="height: 360px; width: 100%; border-radius: 16px;"></div>
    </div>
  `;
}

function renderViewError(container, err) {
  container.innerHTML = `
    <div class="empty-state">
      <div class="empty-state-title">页面加载失败</div>
      <div class="empty-state-desc">${escHtml(err?.message || '请检查本地服务是否正在运行')}</div>
      <button type="button" class="btn btn-primary btn-sm" id="view-retry-btn">重新加载</button>
    </div>
  `;
  container.querySelector('#view-retry-btn')?.addEventListener('click', () => renderCurrentRoute());
}

async function loadViewModule(modulePath) {
  if (moduleCache.has(modulePath)) return moduleCache.get(modulePath);
  const mod = await import(modulePath);
  moduleCache.set(modulePath, mod);
  return mod;
}

async function renderCurrentRoute() {
  const container = document.getElementById('app-main');
  if (!container) return;

  const seq = ++renderSeq;
  const { route, projectId, query } = parseHash(window.location.hash);
  const meta = ROUTE_META[route] || ROUTE_META.studio;

  store.set('activeRoute', route);
  if (projectId) store.set('currentProjectId', projectId);
  updateActiveNav(route);

  if (typeof activeDestroy === 'function') {
    try {
      activeDestroy();
    } catch {
      // ignore
    }
    activeDestroy = null;
  }

  if (route === 'farm' && document.body.classList.contains('is-server-guest')) {
    container.innerHTML = `
      <div class="guest-farm-redirect-card">
        <span class="badge badge-emerald">云端算力已自动托管</span>
        <h2>无需自行配置显卡，直接生成视频</h2>
        <p>当前为共享体验模式。在「生成视频」页输入画面描述或上传素材即可自动排队生成，完成后可直接播放与下载 MP4。</p>
        <div class="flex-wrap" style="justify-content:center; gap: 10px; margin-top: 6px;">
          <a href="#studio" class="btn btn-primary">去生成视频</a>
        </div>
      </div>
    `;
    return;
  }

  if (!moduleCache.has(meta.module)) {
    renderLoadingSkeleton(container);
  }

  try {
    const mod = await loadViewModule(meta.module);
    if (seq !== renderSeq) return;
    const renderFn = mod[meta.exportName] || mod.render || mod.default;
    if (typeof renderFn !== 'function') {
      throw new Error(`模块 ${meta.module} 未导出 ${meta.exportName}`);
    }

    container.innerHTML = '';
    container.classList.remove('view-enter');
    void container.offsetWidth;
    container.classList.add('view-enter');

    const ctx = {
      api,
      store,
      navigate,
      openVideoModal,
      toast,
      escHtml,
      formatSec,
      projectId,
      query,
      refreshGlobalStatus,
    };

    activeDestroy = typeof mod.destroy === 'function' ? mod.destroy : null;
    await renderFn(container, ctx);

    if (seq !== renderSeq) return;
    window.scrollTo({ top: 0, behavior: 'instant' });
  } catch (err) {
    if (seq !== renderSeq) return;
    renderViewError(container, err);
  }
}

async function boot() {
  try {
    const urlParams = new URLSearchParams(window.location.search || '');
    const code = urlParams.get('invite') || urlParams.get('invite_code');
    if (code) setInviteCode(code);
  } catch {
    // ignore
  }

  setupVideoModal();

  store.subscribe('change:liveTasks', (snap) => {
    if (snap) applyLiveTopbarStatus(snap);
  });
  store.subscribe('change:farmStatus', (data) => {
    if (data) {
      const prev = store.get('liveTasks') || {};
      applyLiveTopbarStatus({
        ...prev,
        farm_server_online: data.farm_server_online ?? data.online,
        colab_connected: data.colab_connected,
        online_gpu_count: data.online_gpu_count,
      });
    }
  });

  sseConn = connectEvents((evt) => {
    if (
      evt.type === 'project_created' ||
      evt.type === 'cloud_queue_updated' ||
      evt.type === 'job_progress' ||
      evt.type === 'dispatch_created'
    ) {
      store.invalidate('projectsResponse');
      refreshGlobalStatus();
      hydrateSession(true);
      store.emit(evt.type, evt.data);
    } else if (evt.type === 'farm_status') {
      store.set('farmStatus', evt.data);
    }
  });

  window.addEventListener('hashchange', renderCurrentRoute);
  window.addEventListener('beforeunload', () => {
    sseConn?.close();
    if (statusTimer) clearInterval(statusTimer);
  });

  // Default bare URL lands straight on #studio (Video Generation Workspace)
  if (!window.location.hash || window.location.hash === '#' || window.location.hash === '#/') {
    window.history.replaceState(null, '', '#studio');
  }

  await hydrateSession();
  refreshGlobalStatus();
  statusTimer = setInterval(refreshGlobalStatus, 5000);
  renderCurrentRoute();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}
