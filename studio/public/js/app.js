/**
 * CineForge Studio (影铸) — SPA Hash Router, App Shell & Global Cinema Video Modal
 */

import {
  api,
  store,
  connectEvents,
  toast,
  escHtml,
  formatSec,
  colabNotebookUrl,
  setInviteCode,
} from '/js/api.js';

const ROUTE_META = {
  discover: {
    title: '灵感广场',
    subtitle: '精选样片与名场面换角',
    module: '/js/views/discover.js',
    exportName: 'render',
  },
  create: {
    title: '创作台',
    subtitle: '零门槛三步启动 AI 影片',
    module: '/js/views/create.js',
    exportName: 'render',
  },
  workflow: {
    title: '工作流看板',
    subtitle: '6步可视化制片流水线',
    module: '/js/views/kanban.js',
    exportName: 'render',
  },
  farm: {
    title: '算力工坊',
    subtitle: '低成本云端算力与成本对比',
    module: '/js/views/farm_eval.js',
    exportName: 'renderFarm',
  },
  eval: {
    title: '评测中心',
    subtitle: '白领体验官 3 分钟测评',
    module: '/js/views/farm_eval.js',
    exportName: 'renderEval',
  },
};

const moduleCache = new Map();
let activeDestroy = null;
let renderSeq = 0;
let sseConn = null;

/* ==========================================================================
   Hash Parsing & Navigation
   ========================================================================== */
function parseHash(rawHash) {
  const cleaned = (rawHash || '').replace(/^#\/?/, '');
  const qIdx = cleaned.indexOf('?');
  const pathPart = qIdx >= 0 ? cleaned.slice(0, qIdx) : cleaned;
  const queryPart = qIdx >= 0 ? cleaned.slice(qIdx + 1) : '';

  const segments = pathPart.split('/').filter(Boolean);
  const rawRoute = (segments[0] || 'discover').toLowerCase();
  const route = ROUTE_META[rawRoute] ? rawRoute : 'discover';

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
   Global Cinema Video Lightbox Modal
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
        // ignore seek error before metadata
      }
      if (wasPlaying) {
        els.player.play().catch(() => {});
      }
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
      if (typeof b === 'string') {
        return `<span class="badge">${escHtml(b)}</span>`;
      }
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
    if (ev.target === els.root) {
      closeVideoModal();
    }
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
    if (fn) {
      fn();
    } else if (cq) {
      navigate(`#create?${cq.replace(/^\?/, '')}`);
    }
  });

  els.workflowBtn?.addEventListener('click', () => {
    const fn = modalState.onWorkflow;
    const pid = modalState.projectId;
    closeVideoModal();
    if (fn) {
      fn();
    } else if (pid) {
      navigate(`#workflow/${encodeURIComponent(pid)}`);
    }
  });

  window.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape' && modalState.open) {
      closeVideoModal();
    }
  });
}

/* ==========================================================================
   Guest Perspective Preview & External Share Modal
   ========================================================================== */
const DEFAULT_SHARE_INFO = {
  mode: 'host',
  invite_required: false,
  cloudflared_available: false,
  lan_cmd: 'python3 studio/server.py --host 0.0.0.0 --port 8866',
  public_cmd: 'bash studio/start.sh --public',
  guest_public_cmd: 'bash studio/start.sh --public --guest',
  invite_copy_zh:
    '🎬 邀请体验「影铸 Studio」AI 影片可视化工作流！\n打开即用、免装环境：支持一句话生成分镜大片，也支持经典影视名场面一键变猫咪（原声口型同步 + 自动去字幕）。\n评测期间免费体验，欢迎点击左侧「评测中心」花 2 分钟留下四维打分与建议！',
};

let shareModalOpen = false;
let currentShareInfo = { ...DEFAULT_SHARE_INFO };

async function copyText(text, successMsg = '已复制到剪贴板') {
  const val = String(text || '');
  if (!val) return false;
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(val);
      toast(successMsg, 'success');
      return true;
    }
  } catch {
    // Fallback below for non-HTTPS local / headless contexts
  }
  try {
    const ta = document.createElement('textarea');
    ta.value = val;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    ta.style.pointerEvents = 'none';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    ta.remove();
    toast(successMsg, 'success');
    return true;
  } catch {
    toast('复制失败，请手动选中复制', 'warning');
    return false;
  }
}

function syncGuestPreviewUI(isGuest) {
  const active = Boolean(isGuest);
  document.body.classList.toggle('is-guest-preview', active);
  store.set('guestPreview', active);

  const toggleBtn = document.getElementById('topbar-guest-toggle');
  const toggleLabel = document.getElementById('topbar-guest-label');
  const sideDot = document.getElementById('sidebar-mode-dot');
  const sideText = document.getElementById('sidebar-mode-text');
  const modalGuestBtn = document.getElementById('share-modal-guest-btn');

  if (toggleBtn) {
    toggleBtn.classList.toggle('active', active);
    toggleBtn.setAttribute('aria-checked', String(active));
  }
  if (toggleLabel) {
    toggleLabel.textContent = active ? '访客视角 · 开' : '访客视角';
  }
  if (sideDot) {
    sideDot.className = `status-dot ${active ? 'cyan' : 'gold'}`;
  }
  if (sideText) {
    sideText.textContent = active ? '外部访客体验视角' : '站主模式';
  }
  if (modalGuestBtn) {
    modalGuestBtn.textContent = active ? '退出访客视角（切回站主）' : '切换访客视角预览';
  }
}

function applyShareModalData(info) {
  const data = { ...DEFAULT_SHARE_INFO, ...(info || {}) };
  currentShareInfo = data;
  store.set('shareInfo', data);

  const modeBadge = document.getElementById('share-modal-mode-badge');
  const tunnelBadge = document.getElementById('share-tunnel-badge');
  const guestCmdEl = document.getElementById('share-guest-cmd');
  const lanCmdEl = document.getElementById('share-lan-cmd');
  const inviteEl = document.getElementById('share-invite-copy');
  const dlLink = document.getElementById('share-colab-download');

  if (modeBadge) {
    const isGuestServer = data.mode === 'guest';
    modeBadge.className = `badge ${isGuestServer ? 'badge-cyan' : 'badge-emerald'}`;
    modeBadge.textContent = data.invite_required
      ? '已启用访客口令保护'
      : isGuestServer
        ? '外部访客模式运行中'
        : '零门槛免登录';
  }

  if (tunnelBadge) {
    const ready = Boolean(data.cloudflared_available);
    tunnelBadge.className = `badge ${ready ? 'badge-emerald' : 'badge-cyan'}`;
    tunnelBadge.textContent = ready ? 'cloudflared 隧道已就绪' : '支持 Cloudflare 临时公网';
  }

  if (guestCmdEl) {
    guestCmdEl.textContent = data.guest_public_cmd || DEFAULT_SHARE_INFO.guest_public_cmd;
  }
  if (lanCmdEl) {
    lanCmdEl.textContent = data.lan_cmd || DEFAULT_SHARE_INFO.lan_cmd;
  }
  if (inviteEl) {
    inviteEl.textContent = data.invite_copy_zh || DEFAULT_SHARE_INFO.invite_copy_zh;
  }
  if (dlLink) {
    dlLink.setAttribute('href', colabNotebookUrl);
  }
}

export async function openShareModal() {
  const modal = document.getElementById('share-modal');
  if (!modal) return;

  shareModalOpen = true;
  applyShareModalData(currentShareInfo);
  modal.classList.add('open');
  modal.setAttribute('aria-hidden', 'false');
  document.body.style.overflow = 'hidden';

  try {
    const fresh = await api.shareInfo();
    if (fresh) {
      applyShareModalData(fresh);
    }
  } catch {
    // Keep clean default instructions if share endpoint is temporarily unavailable
  }
}

export function closeShareModal() {
  if (!shareModalOpen) return;
  const modal = document.getElementById('share-modal');
  shareModalOpen = false;
  if (modal) {
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
  }
  if (!modalState.open) {
    document.body.style.overflow = '';
  }
}

function setupGuestAndShareShell() {
  const guestToggle = document.getElementById('topbar-guest-toggle');
  const shareBtn = document.getElementById('topbar-share-btn');
  const modal = document.getElementById('share-modal');
  const closeBtn = document.getElementById('share-modal-close');
  const doneBtn = document.getElementById('share-modal-done-btn');
  const copyGuestCmdBtn = document.getElementById('share-copy-guest-cmd');
  const copyLanCmdBtn = document.getElementById('share-copy-lan-cmd');
  const copyInviteBtn = document.getElementById('share-copy-invite-btn');
  const modalGuestBtn = document.getElementById('share-modal-guest-btn');

  const toggleGuestPreview = () => {
    const next = !document.body.classList.contains('is-guest-preview');
    syncGuestPreviewUI(next);
    toast(
      next
        ? '已切换至外部访客体验视角（白领打开链接所见效果）'
        : '已切回站主工作模式',
      'info'
    );
  };

  guestToggle?.addEventListener('click', toggleGuestPreview);
  modalGuestBtn?.addEventListener('click', () => {
    toggleGuestPreview();
    closeShareModal();
  });

  shareBtn?.addEventListener('click', () => {
    openShareModal();
  });

  closeBtn?.addEventListener('click', closeShareModal);
  doneBtn?.addEventListener('click', closeShareModal);
  modal?.addEventListener('click', (ev) => {
    if (ev.target === modal) {
      closeShareModal();
    }
  });

  copyGuestCmdBtn?.addEventListener('click', () => {
    copyText(currentShareInfo.guest_public_cmd, '已复制一键公网访客命令');
  });

  copyLanCmdBtn?.addEventListener('click', () => {
    copyText(currentShareInfo.lan_cmd, '已复制局域网启动命令');
  });

  copyInviteBtn?.addEventListener('click', () => {
    copyText(currentShareInfo.invite_copy_zh, '已复制微信 / 飞书白领评测邀请文案');
  });

  window.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape' && shareModalOpen) {
      closeShareModal();
    }
  });

  syncGuestPreviewUI(false);
}

function applySessionUI(sess) {
  if (!sess || typeof sess !== 'object') return;
  store.set('session', sess);
  const isGuestServer = sess.mode === 'guest' || Boolean(sess.guest_mode);
  if (isGuestServer) {
    document.body.classList.add('is-server-guest');
    syncGuestPreviewUI(true);
    document.getElementById('share-modal')?.remove();
  }
  const rem = Number.isFinite(Number(sess.remaining_cloud_jobs)) ? Number(sess.remaining_cloud_jobs) : 3;
  const maxJobs = Number.isFinite(Number(sess.max_guest_jobs)) ? Number(sess.max_guest_jobs) : 3;
  const topQuota = document.getElementById('topbar-guest-quota');
  const sideQuota = document.getElementById('sidebar-guest-quota');
  const sideLabel = document.getElementById('sidebar-guest-farm-label');
  const sideDot = document.getElementById('sidebar-guest-dot');
  if (topQuota) {
    topQuota.textContent = `🎁 免费成片额度 ${rem}/${maxJobs}`;
  }
  if (sideQuota) {
    sideQuota.textContent = `★ 免费体验额度 ${rem}/${maxJobs}`;
  }
  if (sideLabel) {
    sideLabel.textContent = sess.farm_online ? '共享影棚算力 · 在线加速' : '共享影棚 · 排队/预演就绪';
  }
  if (sideDot) {
    sideDot.className = `status-dot ${sess.farm_online ? 'online' : 'cyan'}`;
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

async function hydrateShareInfo() {
  try {
    const info = await store.getOrFetch('shareInfo', () => api.shareInfo(), { ttlMs: 30000 });
    if (info) {
      applyShareModalData(info);
      if (info.mode === 'guest') {
        document.body.classList.add('is-server-guest');
        if (!document.body.classList.contains('is-guest-preview')) {
          syncGuestPreviewUI(true);
        }
      }
    }
  } catch {
    // Non-fatal during startup
  }
}

/* ==========================================================================
   Sidebar, Topbar, Project Switcher & Compute Status Sync
   ========================================================================== */
function setupSidebarMobile() {
  const sidebar = document.getElementById('app-sidebar');
  const backdrop = document.getElementById('sidebar-backdrop');
  const toggleBtn = document.getElementById('sidebar-toggle');

  const closeSidebar = () => {
    sidebar?.classList.remove('open');
    backdrop?.classList.remove('open');
    toggleBtn?.setAttribute('aria-expanded', 'false');
  };

  toggleBtn?.addEventListener('click', () => {
    const willOpen = !sidebar?.classList.contains('open');
    sidebar?.classList.toggle('open', willOpen);
    backdrop?.classList.toggle('open', willOpen);
    toggleBtn.setAttribute('aria-expanded', String(willOpen));
  });

  backdrop?.addEventListener('click', closeSidebar);
  sidebar?.addEventListener('click', (ev) => {
    if (ev.target.closest('a')) {
      closeSidebar();
    }
  });
}

function updateActiveShellUI(route, projectId) {
  const meta = ROUTE_META[route] || ROUTE_META.discover;
  const titleEl = document.getElementById('topbar-title');
  const subtitleEl = document.getElementById('topbar-subtitle');

  if (titleEl) titleEl.textContent = meta.title;
  if (subtitleEl) {
    let sub = meta.subtitle;
    if (route === 'workflow' && projectId) {
      const projects = store.get('projects') || [];
      const found = projects.find((p) => p.id === projectId);
      sub = found ? `${found.title} (${found.rendered_shots || 0}/${found.total_shots || 0} 镜)` : projectId;
    }
    subtitleEl.textContent = sub;
  }

  document.querySelectorAll('.sidebar-nav .nav-item').forEach((link) => {
    const isActive = link.dataset.route === route;
    link.classList.toggle('active', isActive);
    if (isActive) {
      link.setAttribute('aria-current', 'page');
    } else {
      link.removeAttribute('aria-current');
    }
  });

  const labelEl = document.getElementById('topbar-project-label');
  if (labelEl) {
    const projects = store.get('projects') || [];
    const activeId = projectId || store.get('currentProjectId');
    const found = projects.find((p) => p.id === activeId);
    labelEl.textContent = found ? found.title : '切换项目';
  }
}

function renderProjectSwitcherMenu(projects = []) {
  const menu = document.getElementById('topbar-project-menu');
  if (!menu) return;

  const currentId = store.get('currentProjectId');

  if (!projects.length) {
    menu.innerHTML = `
      <div class="switcher-menu-header">
        <span>影片项目</span>
        <span>0 个</span>
      </div>
      <div style="padding: 14px 10px; font-size: 12px; color: var(--text-muted); text-align: center;">
        暂无项目，点击右上角新建影片
      </div>
    `;
    return;
  }

  const rows = projects
    .map((p) => {
      const isCurrent = p.id === currentId;
      const modeLabel = p.mode === 'v2v' ? 'V2V 换角' : '原创影片';
      const sourceLabel = p.source === 'studio' ? '我的新建' : '示范片库';
      const rendered = p.rendered_shots ?? 0;
      const total = p.total_shots ?? 0;
      return `
        <button type="button" class="switcher-item ${isCurrent ? 'active' : ''}" role="menuitem" data-project-id="${escHtml(p.id)}">
          <span class="switcher-item-main">
            <span class="switcher-item-title">${escHtml(p.title || p.id)}</span>
            <span class="switcher-item-sub">${escHtml(modeLabel)} · ${escHtml(sourceLabel)}</span>
          </span>
          <span class="switcher-item-stat">${rendered}/${total}</span>
        </button>
      `;
    })
    .join('');

  menu.innerHTML = `
    <div class="switcher-menu-header">
      <span>快速进入项目工作流</span>
      <span>${projects.length} 部</span>
    </div>
    ${rows}
  `;
}

function setupProjectSwitcher() {
  const btn = document.getElementById('topbar-project-switcher');
  const menu = document.getElementById('topbar-project-menu');
  const wrap = document.getElementById('project-switcher');
  if (!btn || !menu || !wrap) return;

  const setOpen = (open) => {
    menu.classList.toggle('open', open);
    btn.setAttribute('aria-expanded', String(open));
  };

  btn.addEventListener('click', (ev) => {
    ev.stopPropagation();
    const willOpen = !menu.classList.contains('open');
    if (willOpen) {
      renderProjectSwitcherMenu(store.get('projects') || []);
      refreshProjectsCache().catch(() => {});
    }
    setOpen(willOpen);
  });

  menu.addEventListener('click', (ev) => {
    const item = ev.target.closest('[data-project-id]');
    if (!item) return;
    const pid = item.dataset.projectId;
    setOpen(false);
    navigate(`#workflow/${encodeURIComponent(pid)}`);
  });

  document.addEventListener('click', (ev) => {
    if (!wrap.contains(ev.target)) {
      setOpen(false);
    }
  });

  window.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape') {
      setOpen(false);
    }
  });
}

async function refreshProjectsCache(force = false) {
  try {
    const res = await store.getOrFetch('projectsResponse', () => api.projects(), {
      force,
      ttlMs: 12000,
    });
    const list = Array.isArray(res?.projects) ? res.projects : [];
    store.set('projects', list);
    renderProjectSwitcherMenu(list);
    const parsed = parseHash(window.location.hash);
    updateActiveShellUI(parsed.route, parsed.projectId);
    return list;
  } catch {
    return store.get('projects') || [];
  }
}

function applyFarmStatusUI(statusData) {
  const topDot = document.getElementById('topbar-farm-dot');
  const topText = document.getElementById('topbar-farm-text');
  const sideDot = document.getElementById('sidebar-farm-dot');
  const sideLabel = document.getElementById('sidebar-farm-label');
  const sideSub = document.getElementById('sidebar-farm-sub');

  const isOnline = Boolean(
    statusData &&
      (statusData.online === true ||
        statusData.farm_online === true ||
        statusData.server_online === true ||
        statusData.farm_server_online === true ||
        statusData.status === 'online')
  );

  const renderedCount =
    statusData?.total_shots_rendered ??
    statusData?.rendered_shots ??
    statusData?.stats?.total_shots_rendered ??
    null;

  if (topDot) {
    topDot.className = `status-dot ${isOnline ? 'online' : 'cyan'}`;
  }
  if (topText) {
    topText.textContent = isOnline ? 'Colab 在线' : '本地预演就绪';
  }
  if (sideDot) {
    sideDot.className = `status-dot ${isOnline ? 'online' : 'cyan'}`;
  }
  if (sideLabel) {
    sideLabel.textContent = isOnline ? 'Colab 共享算力在线' : '云端算力按需待命';
  }
  if (sideSub) {
    sideSub.textContent =
      renderedCount !== null
        ? `已累计出片 ${renderedCount} 镜 · 单镜约 41 秒`
        : '本地故事板与预演随时可用';
  }
}

async function refreshFarmStatus(force = false) {
  try {
    const data = await store.getOrFetch('farmStatus', () => api.farmStatus(), {
      force,
      ttlMs: 20000,
    });
    applyFarmStatusUI(data);
  } catch {
    applyFarmStatusUI(null);
  }
}

/* ==========================================================================
   View Loader & Router Execution
   ========================================================================== */
function renderLoadingSkeleton(container) {
  container.innerHTML = `
    <div class="flex-col gap-4" aria-busy="true">
      <div class="skeleton" style="height: 44px; width: 320px; border-radius: 12px;"></div>
      <div class="skeleton" style="height: 280px; width: 100%; border-radius: 20px;"></div>
      <div class="kpi-grid">
        <div class="skeleton" style="height: 110px; border-radius: 16px;"></div>
        <div class="skeleton" style="height: 110px; border-radius: 16px;"></div>
        <div class="skeleton" style="height: 110px; border-radius: 16px;"></div>
        <div class="skeleton" style="height: 110px; border-radius: 16px;"></div>
      </div>
    </div>
  `;
}

function renderViewError(container, err) {
  container.innerHTML = `
    <div class="empty-state">
      <div class="empty-state-icon">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="9"/>
          <path d="M12 8v5M12 16h.01"/>
        </svg>
      </div>
      <div class="empty-state-title">视图加载遇到一点问题</div>
      <div class="empty-state-desc">${escHtml(err?.message || '请检查本地服务状态后重试')}</div>
      <button type="button" class="btn btn-primary btn-sm" id="view-retry-btn">重新加载</button>
    </div>
  `;
  const retryBtn = container.querySelector('#view-retry-btn');
  retryBtn?.addEventListener('click', () => renderCurrentRoute());
}

async function loadViewModule(modulePath) {
  if (moduleCache.has(modulePath)) {
    return moduleCache.get(modulePath);
  }
  const mod = await import(modulePath);
  moduleCache.set(modulePath, mod);
  return mod;
}

async function renderCurrentRoute() {
  const container = document.getElementById('app-main');
  if (!container) return;

  const seq = ++renderSeq;
  const { route, projectId, query } = parseHash(window.location.hash);
  const meta = ROUTE_META[route] || ROUTE_META.discover;

  store.set('activeRoute', route);
  if (projectId) {
    store.set('currentProjectId', projectId);
  }

  updateActiveShellUI(route, projectId);

  if (typeof activeDestroy === 'function') {
    try {
      activeDestroy();
    } catch {
      // ignore cleanup error
    }
    activeDestroy = null;
  }

  if (route === 'farm' && document.body.classList.contains('is-server-guest')) {
    container.innerHTML = `
      <div class="guest-farm-redirect-card">
        <span class="badge badge-emerald">共享影棚算力已自动托管</span>
        <h2>无需自己配显卡，写完想法就能生成</h2>
        <p>您当前正在使用影铸共享云端影棚。只需在「一键做视频」填写故事灵感或上传一段视频，系统会自动为您排入共享显卡队列，生成后可直接在页面内播放和下载 MP4 成片。</p>
        <div class="flex-wrap" style="justify-content:center; gap: 10px; margin-top: 6px;">
          <a href="#create" class="btn btn-primary">✨ 立即免费做视频</a>
          <a href="#discover" class="btn btn-secondary">🎬 看真实样片对比</a>
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

/* ==========================================================================
   Bootstrap
   ========================================================================== */
async function boot() {
  // Optional invite code passthrough from URL search params (default: none / zero-friction)
  try {
    const urlParams = new URLSearchParams(window.location.search || '');
    const code = urlParams.get('invite') || urlParams.get('invite_code');
    if (code) {
      setInviteCode(code);
    }
  } catch {
    // ignore
  }

  setupSidebarMobile();
  setupVideoModal();
  setupGuestAndShareShell();
  setupProjectSwitcher();

  // Keep shell header & farm status synchronized with store updates
  store.subscribe('change:currentProjectId', (pid) => {
    const parsed = parseHash(window.location.hash);
    updateActiveShellUI(parsed.route, pid || parsed.projectId);
    renderProjectSwitcherMenu(store.get('projects') || []);
  });
  store.subscribe('change:farmStatus', (data) => {
    if (data) applyFarmStatusUI(data);
  });

  // Connect global SSE stream once for all views
  sseConn = connectEvents((evt) => {
    if (evt.type === 'project_created') {
      store.invalidate('projectsResponse');
      refreshProjectsCache(true);
      hydrateSession(true);
    } else if (evt.type === 'cloud_queue_updated' || evt.type === 'dispatch_created') {
      store.invalidate('projectsResponse');
      refreshProjectsCache(true);
      hydrateSession(true);
      store.emit(evt.type, evt.data);
    } else if (evt.type === 'farm_status') {
      store.set('farmStatus', evt.data);
      applyFarmStatusUI(evt.data);
    }
  });

  window.addEventListener('hashchange', renderCurrentRoute);
  window.addEventListener('beforeunload', () => {
    sseConn?.close();
  });

  // Normalize bare URL to #discover without extra history noise
  if (!window.location.hash || window.location.hash === '#' || window.location.hash === '#/') {
    window.history.replaceState(null, '', '#discover');
  }

  // Hydrate session BEFORE initial route render so guest mode & studio_sid cookie are established
  await hydrateSession();
  refreshProjectsCache();
  refreshFarmStatus();
  hydrateShareInfo();
  renderCurrentRoute();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}
