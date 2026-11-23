// CineForge Studio — Workflow Kanban, 6-Stage Pipeline, Shot Inspector & Storyboard
// Linear/Notion Kanban + 即梦 Storyboard + DaVinci Cut Studio

import { renderDag } from './dag.js';

const DEFAULT_STAGES = [
  { key: 'script', index: 1, title: '写清创意与剧本', subtitle: '剧情大纲与场次节奏', tip: '确认本片核心想法、画幅和场次划分，无需写复杂代码即可启动全片制作。' },
  { key: 'refs', index: 2, title: '锁定角色画风', subtitle: '视觉锁与定妆参考图', tip: '先锁定主角与场景参考图，后续几十到几百个分镜都会自动对齐同一张脸。' },
  { key: 'storyboard', index: 3, title: '拆解逐镜分镜', subtitle: '逐镜画面与台词脚本', tip: '点击下方任意镜头卡片可修改画面描述、台词和提示词，满意后即可批量派拍。' },
  { key: 'render', index: 4, title: '云端低价拍摄', subtitle: 'Colab 农场并行出片', tip: '点击顶部「派发云端精拍」即可写入 CineForge 任务清单，单镜约 40 秒、成本极低。' },
  { key: 'qa', index: 5, title: '逐镜抽检重拍', subtitle: '过审把关与单镜重拍', tip: '在「待抽检/需重拍」列点击镜头直接播放检查，满意点过审，瑕疵可单镜打回重拍。' },
  { key: 'master', index: 6, title: '自动配乐合成', subtitle: '精剪转场与母版交付', tip: '点击顶部「一键合成预演片」即可由本地 FFmpeg 自动合成可播放 MP4 成片。' },
];

const STATUS_LABELS = {
  draft: '待定稿',
  rendering: '云端拍摄中',
  review: '待抽检',
  retake: '需重拍',
  approved: '已过审成片',
};

const COLUMNS = [
  { key: 'draft', title: '待定稿', statuses: ['draft'], emptyHint: '暂无待定稿分镜' },
  { key: 'rendering', title: '云端拍摄中', statuses: ['rendering'], emptyHint: '派发云端后镜头会进入这里' },
  { key: 'review', title: '待抽检 / 需重拍', statuses: ['retake', 'review'], emptyHint: '云端出片后会等待导演抽检' },
  { key: 'approved', title: '已过审成片', statuses: ['approved'], emptyHint: '点击镜头「✓ 过审」即可收入成片池' },
];

let activeCleanup = null;
let renderGeneration = 0;

function fallbackEsc(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function fallbackFormatSec(sec) {
  const n = Number(sec);
  if (!Number.isFinite(n) || n <= 0) return '0s';
  if (n < 60) return `${Math.round(n * 10) / 10}s`;
  const m = Math.floor(n / 60);
  const s = Math.round(n % 60);
  return s ? `${m}m${s}s` : `${m}m`;
}

function isValidUrl(val) {
  return typeof val === 'string' && val.trim().length > 0 && (val.startsWith('/') || val.startsWith('http://') || val.startsWith('https://') || val.startsWith('data:image/'));
}

function normalizeDialogueLines(dialogue) {
  if (!dialogue) return [];
  if (typeof dialogue === 'string') {
    return dialogue.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
  }
  if (Array.isArray(dialogue)) {
    return dialogue
      .map((item) => {
        if (typeof item === 'string') return item.trim();
        if (item && typeof item === 'object') {
          const text = item.text || item.line || item.content || '';
          const speaker = item.speaker || item.character || item.role || '';
          if (speaker && text) return `${speaker}：${text}`;
          return String(text || speaker).trim();
        }
        return '';
      })
      .filter(Boolean);
  }
  return [];
}

function resolveShotRefUrls(shot, projectRefs) {
  const refMap = new Map();
  (projectRefs || []).forEach((r) => {
    if (r?.id && isValidUrl(r.url)) refMap.set(r.id, r.url);
    if (r?.name && isValidUrl(r.url)) refMap.set(r.name, r.url);
  });

  const urls = [];
  const raw = Array.isArray(shot?.refs) ? shot.refs : [];
  for (const item of raw) {
    if (typeof item === 'string') {
      if (isValidUrl(item)) urls.push(item);
      else if (refMap.has(item)) urls.push(refMap.get(item));
    } else if (item && typeof item === 'object') {
      if (isValidUrl(item.url)) urls.push(item.url);
      else if (item.id && refMap.has(item.id)) urls.push(refMap.get(item.id));
    }
  }
  return [...new Set(urls)];
}

function getShotThumbUrl(shot, projectRefs) {
  if (isValidUrl(shot?.thumb_url)) return shot.thumb_url;
  const resolved = resolveShotRefUrls(shot, projectRefs);
  if (resolved.length > 0) return resolved[0];
  return '';
}

function formatCost(cny) {
  const n = Number(cny);
  if (!Number.isFinite(n) || n <= 0) return '约 ¥0.5 · 内测免费';
  if (n < 1) return `约 ¥${n.toFixed(1)}`;
  return `约 ¥${Math.round(n)}`;
}

function copyText(text) {
  if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
    return navigator.clipboard.writeText(text).catch(() => legacyCopy(text));
  }
  return Promise.resolve(legacyCopy(text));
}

function legacyCopy(text) {
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.select();
  try {
    document.execCommand('copy');
  } catch {
    // ignore
  }
  ta.remove();
}

export function destroy() {
  renderGeneration += 1;
  if (typeof activeCleanup === 'function') {
    activeCleanup();
    activeCleanup = null;
  }
}

export async function render(container, ctx) {
  destroy();
  const gen = renderGeneration;

  const esc = ctx?.escHtml || fallbackEsc;
  const formatSec = ctx?.formatSec || fallbackFormatSec;
  const toast = ctx?.toast || (() => {});
  const api = ctx?.api;

  const state = {
    projects: [],
    projectId: ctx?.projectId || '',
    detail: null,
    activeView: ['kanban', 'dag', 'storyboard'].includes(ctx?.query?.view) ? ctx.query.view : 'kanban',
    selectedScene: ctx?.query?.scene || '',
    selectedStageKey: '',
    inspectorShotId: null,
    inspectorMediaMode: 'output', // 'output' | 'control'
    retakeOpen: false,
    dispatchModal: null,
    refLightbox: null,
    previewJob: null, // { id, status, progress, message, videoUrl }
    directorExpanded: true,
    directorUserToggled: false,
    finalPlayerMode: 'clean', // 'clean' | 'side_by_side'
    busy: {
      advancing: false,
      dispatching: false,
      renderingPreview: false,
      savingShot: false,
    },
  };

  let pollTimer = null;
  let cloudPollTimer = null;
  let dagHandle = null;
  const storeListeners = [];

  function clearPoll() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function clearCloudPoll() {
    if (cloudPollTimer) {
      clearInterval(cloudPollTimer);
      cloudPollTimer = null;
    }
  }

  function isStale() {
    return gen !== renderGeneration;
  }

  // Capture-phase image error handler so ZERO visible broken <img> ever remains
  const onMediaError = (e) => {
    const target = e.target;
    if (target && target.tagName === 'IMG') {
      target.style.display = 'none';
      const fallback = target.parentElement?.querySelector('.wf-thumb-fallback');
      if (fallback) fallback.classList.remove('is-hidden');
    }
  };
  container.addEventListener('error', onMediaError, true);

  // Keyboard ESC handler for drawer & modals
  const onKeyDown = (e) => {
    if (e.key !== 'Escape') return;
    if (state.refLightbox) {
      state.refLightbox = null;
      renderModals();
    } else if (state.dispatchModal) {
      state.dispatchModal = null;
      renderModals();
    } else if (state.inspectorShotId) {
      state.inspectorShotId = null;
      state.retakeOpen = false;
      renderModals();
    }
  };
  window.addEventListener('keydown', onKeyDown);

  // Subscribe to SSE events via ctx.store if available
  const onJobProgressEvent = (ev) => {
    const data = ev?.detail || ev;
    if (!data) return;
    const jobId = data.job_id || data.id;
    const matchesJob = state.previewJob && jobId && state.previewJob.id === jobId;
    const matchesProject = data.project_id && data.project_id === state.projectId && (data.kind === 'render_preview' || !data.kind);
    if (!matchesJob && !matchesProject) return;

    const pct = Number.isFinite(Number(data.progress)) ? Math.min(100, Math.max(0, Number(data.progress))) : (state.previewJob?.progress || 15);
    const status = data.status || (pct >= 100 ? 'completed' : 'running');
    const videoUrl = data.video_url || data.preview_video_url || data.output_url || data.result?.video_url || data.result?.preview_video_url || state.previewJob?.videoUrl || '';

    state.previewJob = {
      id: jobId || state.previewJob?.id || 'preview',
      status,
      progress: status === 'completed' || status === 'done' ? 100 : pct,
      message: data.message || (status === 'completed' || status === 'done' ? '预演成片合成完成！' : '正在使用 FFmpeg 合成预演影片...'),
      videoUrl,
    };

    if (status === 'completed' || status === 'done') {
      clearPoll();
      state.busy.renderingPreview = false;
      if (videoUrl && state.detail?.project) {
        state.detail.project.preview_video_url = videoUrl;
      }
      toast('预演片合成完成，可立即点击观看！', 'success');
      refreshDetailSilent();
    } else if (status === 'failed' || status === 'error') {
      clearPoll();
      state.busy.renderingPreview = false;
      toast(data.message || '预演片合成失败', 'error');
    }
    updateHeaderProgressOnly();
  };

  const onShotUpdatedEvent = (ev) => {
    const data = ev?.detail || ev;
    if (!data || data.project_id !== state.projectId) return;
    if (data.shot && state.detail?.shots) {
      const idx = state.detail.shots.findIndex((s) => s.id === data.shot.id);
      if (idx >= 0) {
        state.detail.shots[idx] = { ...state.detail.shots[idx], ...data.shot };
        renderWorkspace();
      }
    }
  };

  const onCloudQueueEvent = (ev) => {
    const data = ev?.detail || ev;
    if (!data) return;
    const pid = data.project_id || data.job?.project_id;
    if (pid && pid === state.projectId) {
      if (data.job && state.detail) {
        state.detail.cloud_job = data.job;
      }
      if (['completed', 'failed', 'canceled', 'cancelled'].includes(data.job?.status)) {
        clearCloudPoll();
      }
      refreshDetailSilent();
    }
  };

  if (ctx?.store && typeof ctx.store.addEventListener === 'function') {
    ['job_progress', 'sse:job_progress'].forEach((evt) => {
      ctx.store.addEventListener(evt, onJobProgressEvent);
      storeListeners.push([evt, onJobProgressEvent]);
    });
    ['shot_updated', 'sse:shot_updated'].forEach((evt) => {
      ctx.store.addEventListener(evt, onShotUpdatedEvent);
      storeListeners.push([evt, onShotUpdatedEvent]);
    });
    ['cloud_queue_updated', 'sse:cloud_queue_updated'].forEach((evt) => {
      ctx.store.addEventListener(evt, onCloudQueueEvent);
      storeListeners.push([evt, onCloudQueueEvent]);
    });
  }

  activeCleanup = () => {
    clearPoll();
    clearCloudPoll();
    if (dagHandle) {
      dagHandle.destroy();
      dagHandle = null;
    }
    container.removeEventListener('error', onMediaError, true);
    container.removeEventListener('change', onContainerChange);
    container.removeEventListener('click', onContainerClick);
    window.removeEventListener('keydown', onKeyDown);
    if (ctx?.store && typeof ctx.store.removeEventListener === 'function') {
      for (const [evt, fn] of storeListeners) {
        ctx.store.removeEventListener(evt, fn);
      }
    }
    const overlayRoot = document.getElementById('wf-overlay-root');
    if (overlayRoot) overlayRoot.remove();
  };

  // Render sleek skeleton immediately while fetching
  container.innerHTML = `
    <div class="wf-shell wf-loading-shell">
      <div class="wf-skel" style="height:76px;"></div>
      <div class="wf-skel" style="height:126px;"></div>
      <div class="wf-kanban-grid">
        <div class="wf-skel" style="height:360px;"></div>
        <div class="wf-skel" style="height:360px;"></div>
        <div class="wf-skel" style="height:360px;"></div>
        <div class="wf-skel" style="height:360px;"></div>
      </div>
    </div>
  `;

  async function loadInitialData() {
    try {
      const listResp = await api.projects();
      if (isStale()) return;
      const projects = Array.isArray(listResp?.projects) ? listResp.projects : [];
      state.projects = projects;

      if (!projects.length) {
        container.innerHTML = `
          <div class="wf-error-box">
            <div style="font-size:16px;font-weight:700;">还没有可视化影片工作流</div>
            <div style="color:var(--text-secondary);font-size:13px;">去创作台输入一句话想法，3 秒自动生成 6 步工作流与逐镜看板。</div>
            <button type="button" class="wf-btn wf-btn-gold" data-go-create>✨ 去创作台新建影片</button>
          </div>
        `;
        container.querySelector('[data-go-create]')?.addEventListener('click', () => ctx.navigate('#create'));
        return;
      }

      // Resolve projectId cleanly
      let targetId = state.projectId;
      if (!targetId || !projects.some((p) => p.id === targetId)) {
        const preferred = projects.find((p) => p.id === 'starcore')
          || projects.find((p) => p.id === 'classics')
          || projects[0];
        targetId = preferred.id;
        state.projectId = targetId;
        try {
          window.history.replaceState(null, '', `#workflow/${encodeURIComponent(targetId)}`);
        } catch {
          // ignore
        }
      }
      ctx?.store?.set?.('projects', projects);
      ctx?.store?.set?.('currentProjectId', targetId);

      await fetchProjectDetail(targetId, state.selectedScene);
    } catch (err) {
      if (isStale()) return;
      container.innerHTML = `
        <div class="wf-error-box">
          <div style="font-size:16px;font-weight:700;">工作流数据加载失败</div>
          <div style="color:var(--text-secondary);font-size:13px;">${esc(err?.message || '请确认本地 CineForge Studio 服务正常运行')}</div>
          <button type="button" class="wf-btn wf-btn-surface" data-retry>重试加载</button>
        </div>
      `;
      container.querySelector('[data-retry]')?.addEventListener('click', () => loadInitialData());
    }
  }

  function syncCloudPolling() {
    const cq = state.detail?.cloud_job;
    const isActive = cq && ['queued', 'staging', 'rendering', 'assembling'].includes(cq.status);
    if (isActive && !cloudPollTimer) {
      cloudPollTimer = setInterval(() => {
        if (!isStale()) refreshDetailSilent();
      }, 2200);
    } else if (!isActive && cloudPollTimer) {
      clearCloudPoll();
    }
  }

  async function fetchProjectDetail(projectId, scene = '') {
    const params = { limit: 80 };
    if (scene) params.scene = scene;
    const detail = await api.projectDetail(projectId, params);
    if (isStale()) return;

    state.detail = detail;
    const isGuestServer = document.body.classList.contains('is-server-guest');
    const isStudioProj = detail?.project?.source === 'studio' || String(projectId).startsWith('studio_');
    if (!state.directorUserToggled) {
      state.directorExpanded = !(isGuestServer && isStudioProj);
    }
    const stages = getMergedStages();
    if (!state.selectedStageKey || !stages.some((s) => s.key === state.selectedStageKey)) {
      const activeSt = stages.find((s) => s.status === 'active') || stages[stages.length - 1] || stages[0];
      state.selectedStageKey = activeSt?.key || 'script';
    }
    syncCloudPolling();
    renderAll();
  }

  async function refreshDetailSilent() {
    try {
      const params = { limit: 80 };
      if (state.selectedScene) params.scene = state.selectedScene;
      const [listResp, detail] = await Promise.all([
        api.projects().catch(() => null),
        api.projectDetail(state.projectId, params),
      ]);
      if (isStale()) return;
      if (Array.isArray(listResp?.projects)) state.projects = listResp.projects;
      state.detail = detail;
      syncCloudPolling();
      renderAll();
    } catch {
      // ignore silent refresh error
    }
  }

  function getMergedStages() {
    const apiStages = Array.isArray(state.detail?.stages) ? state.detail.stages : [];
    const byKey = new Map(apiStages.map((s) => [s.key, s]));
    return DEFAULT_STAGES.map((def, i) => {
      const match = byKey.get(def.key) || apiStages[i] || {};
      return {
        ...def,
        ...match,
        key: match.key || def.key,
        index: i + 1,
        title: match.title || def.title,
        subtitle: match.subtitle || def.subtitle,
        status: match.status || 'pending',
        metric: match.metric || '',
        tip: match.tip || def.tip,
      };
    });
  }

  function getWatchableVideoUrl() {
    const proj = state.detail?.project || {};
    return proj.final_video_url || state.previewJob?.videoUrl || proj.preview_video_url || '';
  }

  function renderHeaderHtml() {
    const proj = state.detail?.project || {};
    const isV2V = proj.mode === 'v2v';
    const totalShots = proj.total_shots ?? (state.detail?.shots?.length || 0);
    const renderedShots = proj.rendered_shots ?? 0;
    const approvedShots = proj.approved_shots ?? 0;
    const watchUrl = getWatchableVideoUrl();

    const studioProjects = state.projects.filter((p) => p.source === 'studio' || String(p.id).startsWith('studio_'));
    const workspaceProjects = state.projects.filter((p) => !studioProjects.includes(p));

    const renderOptions = (list) => list.map((p) => {
      const label = `${p.title || p.id} (${p.rendered_shots ?? 0}/${p.total_shots ?? 0}镜)`;
      return `<option value="${esc(p.id)}" ${p.id === state.projectId ? 'selected' : ''}>${esc(label)}</option>`;
    }).join('');

    const selectInner = studioProjects.length
      ? `<optgroup label="✨ 我的新建影片">${renderOptions(studioProjects)}</optgroup>
         <optgroup label="🎬 平台实拍示范项目">${renderOptions(workspaceProjects)}</optgroup>`
      : renderOptions(state.projects);

    return `
      <section class="wf-header" data-wf-header>
        <div class="wf-header-top">
          <div class="wf-header-left">
            <div class="wf-project-picker">
              <select class="wf-project-select" data-project-select aria-label="切换影片项目">
                ${selectInner}
              </select>
              <span class="wf-picker-chevron" aria-hidden="true">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="m6 9 6 6 6-6"/></svg>
              </span>
            </div>

            <div class="wf-meta-badges">
              <span class="wf-chip ${isV2V ? 'wf-chip-cyan' : 'wf-chip-gold'}">
                ${isV2V ? '🐱 V2V 换角' : '🎬 原创电影'}
              </span>
              <span class="wf-chip ${renderedShots > 0 ? 'wf-chip-emerald' : ''}">
                已完成 ${esc(renderedShots)}/${esc(totalShots)} 镜${approvedShots ? ` · ${esc(approvedShots)} 过审` : ''}
              </span>
              <span class="wf-chip wf-chip-emerald">
                预计成本 ${esc(formatCost(proj.est_cost_cny))}
              </span>
              ${proj.style ? `<span class="wf-chip">${esc(proj.style)}</span>` : ''}
            </div>
          </div>

          <div class="wf-header-actions">
            ${!String(proj.id || '').startsWith('studio_') && proj.source !== 'studio' ? `<span class="wf-chip guest-only">示范项目 · 只读浏览</span>` : ''}
            <button
              type="button"
              class="wf-btn wf-btn-surface ${!String(proj.id || '').startsWith('studio_') && proj.source !== 'studio' ? 'wf-readonly-hide' : ''}"
              data-action="render-preview"
              ${state.busy.renderingPreview ? 'disabled' : ''}
            >
              🎬 ${state.busy.renderingPreview ? '合成预演中...' : '一键合成预演片'}
            </button>
            <button
              type="button"
              class="wf-btn wf-btn-cyan ${!String(proj.id || '').startsWith('studio_') && proj.source !== 'studio' ? 'wf-readonly-hide' : ''}"
              data-action="dispatch-cloud"
              ${state.busy.dispatching ? 'disabled' : ''}
            >
              ⚡ ${state.busy.dispatching ? '正在派发...' : '派发云端精拍'}
            </button>
            <button
              type="button"
              class="wf-btn wf-btn-gold"
              data-action="watch-film"
              ${watchUrl ? '' : 'disabled title="请先点击「一键合成预演片」或等待云端出片"'}
            >
              ▶ ${proj.final_video_url ? '观看电影成片' : '观看预演成片'}
            </button>
          </div>
        </div>

        <div data-header-progress-slot>
          ${renderProgressBannerHtml()}
        </div>
      </section>
    `;
  }

  function renderProgressBannerHtml() {
    const job = state.previewJob;
    if (!job) return '';
    const isDone = job.status === 'completed' || job.status === 'done';
    const isErr = job.status === 'failed' || job.status === 'error';
    const pct = Math.min(100, Math.max(0, Math.round(Number(job.progress) || 0)));

    return `
      <div class="wf-render-progress ${isDone ? 'is-done' : isErr ? 'is-error' : ''}">
        <div class="wf-progress-row">
          <span class="wf-progress-label">
            <span>${isDone ? '✓' : isErr ? '!' : '⚡'}</span>
            <span>${esc(job.message || '正在合成可播放 MP4 预演成片...')}</span>
          </span>
          <div style="display:flex;align-items:center;gap:10px;">
            <span class="wf-progress-pct">${pct}%</span>
            ${isDone && getWatchableVideoUrl() ? `<button type="button" class="wf-btn wf-btn-emerald wf-btn-sm" data-action="watch-film">▶ 立即观看预演片</button>` : ''}
          </div>
        </div>
        <div class="wf-progress-track">
          <div class="wf-progress-fill" style="width:${pct}%;"></div>
        </div>
      </div>
    `;
  }

  function updateHeaderProgressOnly() {
    const slot = container.querySelector('[data-header-progress-slot]');
    if (slot) slot.innerHTML = renderProgressBannerHtml();

    const watchBtn = container.querySelector('[data-action="watch-film"]');
    if (watchBtn && getWatchableVideoUrl()) {
      watchBtn.disabled = false;
      watchBtn.removeAttribute('title');
    }
    const renderBtn = container.querySelector('[data-action="render-preview"]');
    if (renderBtn) {
      renderBtn.disabled = state.busy.renderingPreview;
      renderBtn.textContent = state.busy.renderingPreview ? '🎬 合成预演中...' : '🎬 一键合成预演片';
    }
  }

  function renderPipelineHtml() {
    const stages = getMergedStages();
    const selected = stages.find((s) => s.key === state.selectedStageKey) || stages[0];

    return `
      <section class="wf-pipeline" aria-label="6步可视化制片流水线">
        <div class="wf-stage-grid">
          ${stages.map((st, idx) => {
            const num = st.index || idx + 1;
            const iconHtml = st.status === 'done'
              ? `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`
              : String(num);
            const stateText = st.status === 'done' ? '已完成' : st.status === 'active' ? '当前步骤' : '待进行';
            return `
              <button
                type="button"
                class="wf-stage-card status-${esc(st.status)} ${st.key === selected.key ? 'is-selected' : ''}"
                data-select-stage="${esc(st.key)}"
                title="${esc(st.tip)}"
              >
                <div class="wf-stage-head">
                  <span class="wf-stage-dot">${iconHtml}</span>
                  <span class="wf-stage-state">${stateText}</span>
                </div>
                <div class="wf-stage-title">${esc(st.title)}</div>
                <div class="wf-stage-metric">${esc(st.metric || st.subtitle)}</div>
              </button>
            `;
          }).join('')}
        </div>

        <div class="wf-stage-tipbar">
          <div class="wf-stage-tip-left">
            <span class="wf-stage-tip-badge">步骤 ${esc(selected.index)} · ${esc(selected.title)}</span>
            <span class="wf-stage-tip-text"><strong>引导说明：</strong>${esc(selected.tip)}</span>
          </div>
          <div class="wf-stage-tip-actions">
            ${selected.key === 'refs' ? `<button type="button" class="wf-btn wf-btn-ghost wf-btn-sm" data-switch-view="storyboard">查看角色定妆卡</button>` : ''}
            ${selected.key === 'render' ? `<button type="button" class="wf-btn wf-btn-cyan wf-btn-sm" data-action="dispatch-cloud">⚡ 立即派发云端</button>` : ''}
            ${selected.key === 'master' ? `<button type="button" class="wf-btn wf-btn-surface wf-btn-sm" data-action="render-preview">🎬 合成预演片</button>` : ''}
            ${selected.status !== 'done' ? `
              <button
                type="button"
                class="wf-btn wf-btn-gold wf-btn-sm"
                data-advance-stage="${esc(selected.key)}"
                ${state.busy.advancing ? 'disabled' : ''}
              >
                ✓ ${state.busy.advancing ? '推进中...' : '确认推进'}
              </button>
            ` : `<span class="wf-chip wf-chip-emerald">✓ 本阶段已确认完成</span>`}
          </div>
        </div>
      </section>
    `;
  }

  function renderToolbarHtml() {
    const scenes = Array.isArray(state.detail?.scenes) ? state.detail.scenes : [];
    const shots = Array.isArray(state.detail?.shots) ? state.detail.shots : [];
    const totalShots = state.detail?.project?.total_shots ?? shots.length;

    return `
      <section class="wf-toolbar">
        <div class="wf-view-tabs" role="tablist" aria-label="工作流视图切换">
          <button
            type="button"
            role="tab"
            aria-selected="${state.activeView === 'kanban'}"
            class="wf-tab-btn ${state.activeView === 'kanban' ? 'is-active' : ''}"
            data-switch-view="kanban"
            data-testid="tab-kanban"
          >
            📋 制片看板
          </button>
          <button
            type="button"
            role="tab"
            aria-selected="${state.activeView === 'dag'}"
            class="wf-tab-btn ${state.activeView === 'dag' ? 'is-active' : ''}"
            data-switch-view="dag"
            data-testid="tab-dag"
          >
            🔀 Workflow 节点图
          </button>
          <button
            type="button"
            role="tab"
            aria-selected="${state.activeView === 'storyboard'}"
            class="wf-tab-btn ${state.activeView === 'storyboard' ? 'is-active' : ''}"
            data-switch-view="storyboard"
            data-testid="tab-storyboard"
          >
            🎞️ 故事板与角色资产
          </button>
        </div>

        ${state.activeView !== 'dag' ? `
          <div class="wf-scene-bar">
            <div class="wf-scene-pills" role="group" aria-label="场次筛选">
              <button
                type="button"
                class="wf-scene-pill ${!state.selectedScene ? 'is-active' : ''}"
                data-filter-scene=""
              >
                全部场次
              </button>
              ${scenes.map((sc) => `
                <button
                  type="button"
                  class="wf-scene-pill ${state.selectedScene === sc.id ? 'is-active' : ''}"
                  data-filter-scene="${esc(sc.id)}"
                  title="${esc(sc.title || sc.id)}"
                >
                  ${esc(sc.id)}${sc.shot_count ? ` · ${esc(sc.shot_count)}镜` : ''}
                </button>
              `).join('')}
            </div>
            <span class="wf-scene-count">当前显示 ${shots.length} / ${totalShots} 镜</span>
          </div>
        ` : `
          <div class="wf-scene-bar">
            <span class="wf-scene-count">实时映射底层 CineForge 引擎拓扑</span>
          </div>
        `}
      </section>
    `;
  }

  function renderThumbMediaHtml(shot, projectRefs) {
    const thumbUrl = getShotThumbUrl(shot, projectRefs);
    const engineLabel = shot.engine || (state.detail?.project?.mode === 'v2v' ? 'V2V' : 'H3');
    const isV2VEngine = /v2v|ltx/i.test(engineLabel);
    const hasVideo = isValidUrl(shot.video_url);

    return `
      <div class="wf-shot-thumb">
        ${thumbUrl ? `<img src="${esc(thumbUrl)}" alt="${esc(shot.id)}" loading="lazy" />` : ''}
        <div class="wf-thumb-fallback ${thumbUrl ? 'is-hidden' : ''}">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" opacity="0.7">
            <rect x="2" y="4" width="20" height="16" rx="2"/>
            <path d="M7 4v16M17 4v16M2 12h20"/>
          </svg>
          <span>${esc(shot.id)}</span>
        </div>
        <div class="wf-thumb-scrim"></div>
        <span class="wf-shot-top-left">${esc(shot.id)}</span>
        <div class="wf-shot-top-right">
          <span class="wf-pill-mini">${esc(formatSec(shot.seconds || 5))}</span>
          <span class="wf-pill-mini ${isV2VEngine ? 'wf-pill-v2v' : 'wf-pill-engine'}">${esc(engineLabel)}</span>
        </div>
        ${shot.status === 'retake' ? `<span class="wf-retake-tag">↻ 需重拍</span>` : ''}
        ${hasVideo ? `<span class="wf-shot-play-badge">▶ 可播放</span>` : ''}
      </div>
    `;
  }

  function renderShotCardHtml(shot, projectRefs) {
    const lines = normalizeDialogueLines(shot.dialogue);
    const firstLine = lines[0] || '';
    const summary = shot.summary_zh || shot.prompt || '点击查看分镜详情并编辑画面描述';
    const isRetake = shot.status === 'retake';
    const isSelected = shot.id === state.inspectorShotId;

    return `
      <article
        class="wf-shot-card ${isRetake ? 'is-retake' : ''} ${isSelected ? 'is-selected' : ''}"
        data-open-shot="${esc(shot.id)}"
      >
        ${renderThumbMediaHtml(shot, projectRefs)}
        <div class="wf-shot-body">
          <div class="wf-shot-summary" title="${esc(summary)}">${esc(summary)}</div>
          ${firstLine ? `<div class="wf-shot-dialogue" title="${esc(firstLine)}">「${esc(firstLine)}」</div>` : ''}
          <div class="wf-shot-footer">
            <span class="wf-shot-meta">
              ${shot.scene ? esc(shot.scene) : `#${esc(shot.index || 1)}`}${shot.wall_sec ? ` · ${Math.round(shot.wall_sec)}s出片` : ''}
            </span>
            <div class="wf-card-actions">
              ${shot.status !== 'approved' ? `<button type="button" class="wf-icon-btn ok" data-quick-approve="${esc(shot.id)}" title="一键过审">✓ 过审</button>` : ''}
              <button type="button" class="wf-icon-btn retake" data-quick-retake="${esc(shot.id)}" title="打回重拍">↻</button>
              <button type="button" class="wf-icon-btn" data-open-shot="${esc(shot.id)}" title="打开精修抽屉">精修</button>
            </div>
          </div>
        </div>
      </article>
    `;
  }

  function renderKanbanHtml() {
    const shots = Array.isArray(state.detail?.shots) ? state.detail.shots : [];
    const refs = Array.isArray(state.detail?.refs) ? state.detail.refs : [];

    return `
      <section class="wf-kanban-grid" aria-label="四列制片看板">
        ${COLUMNS.map((col) => {
          const colShots = shots
            .filter((s) => col.statuses.includes(s.status || 'draft'))
            .sort((a, b) => {
              // Prioritize retake cards at the top of the review column
              if (col.key === 'review') {
                if (a.status === 'retake' && b.status !== 'retake') return -1;
                if (b.status === 'retake' && a.status !== 'retake') return 1;
              }
              return (a.index || 0) - (b.index || 0);
            });

          return `
            <div class="wf-col" data-col="${esc(col.key)}">
              <div class="wf-col-head">
                <div class="wf-col-title-wrap">
                  <span class="wf-col-dot"></span>
                  <span class="wf-col-title">${esc(col.title)}</span>
                </div>
                <span class="wf-col-count">${colShots.length}</span>
              </div>
              <div class="wf-col-body">
                ${colShots.length
                  ? colShots.map((shot) => renderShotCardHtml(shot, refs)).join('')
                  : `<div class="wf-col-empty"><span>${esc(col.emptyHint)}</span></div>`}
              </div>
            </div>
          `;
        }).join('')}
      </section>
    `;
  }

  function renderStoryboardHtml() {
    const shots = Array.isArray(state.detail?.shots) ? state.detail.shots : [];
    const refs = Array.isArray(state.detail?.refs) ? state.detail.refs : [];

    return `
      <section class="wf-storyboard-wrap">
        <div class="wf-refs-panel">
          <div class="wf-section-head">
            <span class="wf-section-title">🎭 角色与场景定妆卡（Visual Locks）</span>
            <span class="wf-section-sub">全片自动绑定以下视觉锚点，确保长篇连贯不换脸、不跑风</span>
          </div>
          ${refs.length ? `
            <div class="wf-refs-strip">
              ${refs.map((ref, idx) => {
                const hasUrl = isValidUrl(ref.url);
                return `
                  <article class="wf-ref-card" data-open-ref="${idx}">
                    <div class="wf-ref-img-wrap">
                      ${hasUrl ? `<img src="${esc(ref.url)}" alt="${esc(ref.name || ref.id)}" loading="lazy" />` : ''}
                      <div class="wf-thumb-fallback ${hasUrl ? 'is-hidden' : ''}"><span>${esc(ref.name || ref.id || 'REF')}</span></div>
                    </div>
                    <div class="wf-ref-meta">
                      <span class="wf-ref-name">${esc(ref.name || ref.id || `参考图 ${idx + 1}`)}</span>
                      <span class="wf-ref-prompt" title="${esc(ref.prompt || '')}">${esc(ref.prompt || '已锁定为一致性锚点')}</span>
                    </div>
                  </article>
                `;
              }).join('')}
            </div>
          ` : `
            <div class="wf-col-empty" style="padding:18px;">
              <span>当前项目暂无独立定妆参考图，可在「创作台」上传主角照片锁定一致性。</span>
            </div>
          `}
        </div>

        <div class="wf-section-head">
          <span class="wf-section-title">🎞️ 院线级逐镜故事板（Contact Sheet）</span>
          <span class="wf-section-sub">共 ${shots.length} 个镜头 · 点击任意画面进入精修与播放抽屉</span>
        </div>

        <div class="wf-sb-grid">
          ${shots.map((shot, idx) => {
            const lines = normalizeDialogueLines(shot.dialogue);
            const subtitleText = lines[0] || shot.summary_zh || shot.prompt || '暂无台词';
            return `
              <article class="wf-sb-card" data-open-shot="${esc(shot.id)}">
                ${renderThumbMediaHtml(shot, refs)}
                <div class="wf-sb-caption">
                  <div class="wf-shot-footer" style="border-top:none;padding-top:0;">
                    <span class="wf-shot-meta">#${String(idx + 1).padStart(2, '0')} · ${esc(shot.scene || 'S01')} · ${esc(STATUS_LABELS[shot.status] || shot.status)}</span>
                    <span class="wf-chip ${shot.status === 'approved' ? 'wf-chip-emerald' : shot.status === 'retake' ? 'wf-chip-rose' : ''}" style="height:22px;font-size:10.5px;">
                      ${esc(STATUS_LABELS[shot.status] || '待定稿')}
                    </span>
                  </div>
                  <div class="wf-shot-summary" style="min-height:auto;">${esc(shot.summary_zh || shot.prompt || '')}</div>
                  <div class="wf-sb-subbar" title="${esc(subtitleText)}">${lines.length ? `「${esc(lines[0])}」` : esc(subtitleText)}</div>
                </div>
              </article>
            `;
          }).join('')}
        </div>
      </section>
    `;
  }

  function renderNovicePanelHtml() {
    const proj = state.detail?.project || {};
    const cq = state.detail?.cloud_job || null;
    const isStudioProj = proj.source === 'studio' || String(proj.id || '').startsWith('studio_');
    if (!isStudioProj && !cq) return '';

    const hasFinal = Boolean(proj.final_video_url);
    const hasSbs = Boolean(proj.side_by_side_url);
    const isV2V = proj.mode === 'v2v';
    const showSbs = hasSbs && state.finalPlayerMode === 'side_by_side';
    const playerUrl = showSbs ? proj.side_by_side_url : (proj.final_video_url || proj.preview_video_url || '');

    const st = cq?.status || (hasFinal ? 'completed' : 'idle');
    const step2Done = ['rendering', 'assembling', 'completed'].includes(st) || hasFinal;
    const step2Active = ['queued', 'staging'].includes(st);
    const step3Done = ['assembling', 'completed'].includes(st) || hasFinal;
    const step3Active = st === 'rendering';
    const step4Done = st === 'completed' || hasFinal;
    const step4Active = st === 'assembling';

    const pct = hasFinal ? 100 : Math.min(100, Math.max(0, Number(cq?.progress ?? (proj.preview_video_url ? 25 : 8))));
    const queuePos = Number(cq?.queue_pos || 0);

    return `
      <section class="wf-novice-panel" id="wf-novice-panel" aria-label="小白实时生成与成片区">
        <div class="wf-novice-steps">
          <div class="wf-nstep is-done">1. 故事与素材已拆镜</div>
          <div class="wf-nstep ${step2Done ? 'is-done' : step2Active ? 'is-active' : ''}">
            2. ${queuePos > 1 ? `排队第 ${queuePos} 位` : '共享算力排队'}
          </div>
          <div class="wf-nstep ${step3Done ? 'is-done' : step3Active ? 'is-active' : ''}">
            3. 云端显卡逐镜生成 (${esc(cq?.done_shots ?? proj.rendered_shots ?? 0)}/${esc(cq?.total_shots ?? proj.total_shots ?? 0)})
          </div>
          <div class="wf-nstep ${step4Done ? 'is-done' : step4Active ? 'is-active' : ''}">
            4. 自动合成可下载成片
          </div>
        </div>

        ${hasFinal ? `
          <div class="wf-final-result-box" id="wf-final-result-box">
            <div class="wf-final-head">
              <div>
                <span class="wf-chip wf-chip-emerald">🎉 云端成片已生成</span>
                <span class="wf-final-sub">${isV2V ? '主角已成功换猫并保留原声节奏' : '所有分镜已自动剪辑合成可播 MP4'}</span>
              </div>
              ${hasSbs ? `
                <div class="wf-seg-group" role="group" aria-label="切换成片视角">
                  <button type="button" class="wf-btn wf-btn-sm ${!showSbs ? 'wf-btn-gold' : 'wf-btn-surface'}" data-final-mode="clean">🐱 纯净猫咪版</button>
                  <button type="button" class="wf-btn wf-btn-sm ${showSbs ? 'wf-btn-gold' : 'wf-btn-surface'}" data-final-mode="side_by_side">🎞️ 左右原片对照版</button>
                </div>
              ` : ''}
            </div>
            <div class="wf-final-video-wrap">
              <video
                id="wf-final-player"
                class="wf-final-video"
                controls
                playsinline
                preload="metadata"
                src="${esc(playerUrl)}"
                ${proj.poster_url ? `poster="${esc(proj.poster_url)}"` : ''}
              ></video>
            </div>
            <div class="wf-final-actions">
              <a class="wf-btn wf-btn-gold" id="wf-download-final" href="${esc(playerUrl)}" download="${esc(proj.id || 'cineforge')}${showSbs ? '_side_by_side' : ''}.mp4">
                ⬇️ 下载成片 MP4
              </a>
              <a class="wf-btn wf-btn-surface" href="#create">✨ 再创作一部</a>
              <a class="wf-btn wf-btn-cyan" href="#eval">⭐ 去评测中心打分</a>
            </div>
          </div>
        ` : `
          <div class="wf-cloud-status-box">
            <div class="wf-cloud-status-row">
              <div class="wf-cloud-status-text">
                <strong>${esc(cq?.stage_label || (st === 'failed' ? '云端生成遇到问题' : (st === 'canceled' || st === 'cancelled') ? '排队已取消' : '准备排入共享影棚'))}</strong>
                <span>${esc(cq?.message || (proj.preview_video_url ? '即时预演已就绪（可先点击上方「观看预演成片」），点击右侧即可排入云端精拍。' : '系统已自动为你拆好分镜，排入共享显卡队列后将逐镜渲染并自动合成 MP4。'))}</span>
              </div>
              <div class="wf-cloud-status-actions">
                ${['queued', 'staging'].includes(st) ? `
                  <button type="button" class="wf-btn wf-btn-rose wf-btn-sm" data-cancel-cloud-job="${esc(cq.id)}">取消排队</button>
                ` : (!cq || ['failed', 'canceled', 'cancelled'].includes(st)) ? `
                  <button type="button" class="wf-btn wf-btn-cyan wf-btn-sm" data-action="dispatch-cloud" ${state.busy.dispatching ? 'disabled' : ''}>
                    ${st === 'failed' ? '↻ 重新排队生成' : '⚡ 免费排入云端生成'}
                  </button>
                ` : ''}
              </div>
            </div>
            <div class="wf-progress-track">
              <div class="wf-progress-fill" style="width:${pct}%;"></div>
            </div>
          </div>
        `}
      </section>
    `;
  }

  function renderWorkspace() {
    const host = container.querySelector('[data-wf-workspace]');
    if (!host) return;

    if (dagHandle) {
      dagHandle.destroy();
      dagHandle = null;
    }

    if (state.activeView === 'dag') {
      dagHandle = renderDag(host, state.detail, {
        api: ctx.api,
        toast: ctx.toast,
        onNodeSelect() {
          // Node detail panel updates smoothly inside dag.js
        },
        onAction(stageKey) {
          handleDagStageAction(stageKey);
        },
        onWorkflowRan() {
          refreshProject({ silent: true });
        },
      });
    } else if (state.activeView === 'storyboard') {
      host.innerHTML = renderStoryboardHtml();
    } else {
      host.innerHTML = renderKanbanHtml();
    }
  }

  function renderAll() {
    if (!state.detail) return;
    const proj = state.detail.project || {};
    const isGuestServer = document.body.classList.contains('is-server-guest');
    const isStudioProj = proj.source === 'studio' || String(proj.id || '').startsWith('studio_');
    const showDirectorTools = !isGuestServer || !isStudioProj || state.directorExpanded;

    container.innerHTML = `
      <div class="wf-shell">
        ${renderHeaderHtml()}
        ${renderNovicePanelHtml()}
        ${isGuestServer && isStudioProj ? `
          <div class="wf-director-toggle-bar">
            <button type="button" class="wf-btn wf-btn-surface wf-btn-sm" data-toggle-director>
              ${state.directorExpanded ? '▲ 收起导演精修工具' : '🎛️ 展开导演精修（改台词 / 单镜重拍）'}
            </button>
          </div>
        ` : ''}
        ${showDirectorTools ? `
          ${renderPipelineHtml()}
          ${renderToolbarHtml()}
          <div data-wf-workspace></div>
        ` : ''}
      </div>
    `;
    renderWorkspace();
    renderModals();
  }

  function getOverlayRoot() {
    let root = document.getElementById('wf-overlay-root');
    if (!root) {
      root = document.createElement('div');
      root.id = 'wf-overlay-root';
      document.body.appendChild(root);
      root.addEventListener('error', onMediaError, true);
      root.addEventListener('click', onOverlayClick);
      root.addEventListener('submit', onOverlaySubmit);
    }
    return root;
  }

  function renderInspectorDrawerHtml() {
    if (!state.inspectorShotId || !state.detail?.shots) return '';
    const shots = state.detail.shots;
    const shotIdx = shots.findIndex((s) => s.id === state.inspectorShotId);
    if (shotIdx < 0) return '';
    const shot = shots[shotIdx];
    const refs = state.detail.refs || [];
    const shotRefUrls = resolveShotRefUrls(shot, refs);
    const thumbUrl = getShotThumbUrl(shot, refs);

    const hasOutVideo = isValidUrl(shot.video_url);
    const hasCtrlVideo = isValidUrl(shot.control_video_url);
    const activeVideoUrl = (state.inspectorMediaMode === 'control' && hasCtrlVideo)
      ? shot.control_video_url
      : (hasOutVideo ? shot.video_url : (hasCtrlVideo ? shot.control_video_url : ''));

    const dialogueText = normalizeDialogueLines(shot.dialogue).join('\n');
    const cutIn = shot.cut_in ?? 0;
    const cutOut = shot.cut_out ?? (shot.seconds || 5);

    return `
      <div class="wf-drawer-backdrop" data-close-drawer>
        <aside class="wf-drawer" role="dialog" aria-modal="true" aria-label="镜头精修抽屉" data-drawer-panel>
          <div class="wf-drawer-header">
            <div class="wf-drawer-title-group">
              <span class="wf-drawer-shot-id">${esc(shot.id)}</span>
              <span class="wf-chip">${esc(shot.scene || 'S01')}</span>
              <span class="wf-chip wf-chip-cyan">${esc(shot.engine || 'H3')}</span>
              <span class="wf-chip ${shot.status === 'approved' ? 'wf-chip-emerald' : shot.status === 'retake' ? 'wf-chip-rose' : 'wf-chip-gold'}">
                ${esc(STATUS_LABELS[shot.status] || shot.status)}
              </span>
            </div>
            <div class="wf-drawer-nav">
              <button type="button" class="wf-btn wf-btn-ghost wf-btn-sm" data-step-shot="${shotIdx - 1}" ${shotIdx <= 0 ? 'disabled' : ''}>‹ 上一镜</button>
              <button type="button" class="wf-btn wf-btn-ghost wf-btn-sm" data-step-shot="${shotIdx + 1}" ${shotIdx >= shots.length - 1 ? 'disabled' : ''}>下一镜 ›</button>
              <button type="button" class="wf-btn wf-btn-ghost wf-btn-sm" data-close-drawer aria-label="关闭抽屉">✕</button>
            </div>
          </div>

          <form class="wf-drawer-body" id="wf-shot-form" data-shot-id="${esc(shot.id)}">
            <div class="wf-drawer-media">
              ${hasOutVideo && hasCtrlVideo ? `
                <div class="wf-media-toggle">
                  <button type="button" class="wf-media-toggle-btn ${state.inspectorMediaMode !== 'control' ? 'is-active' : ''}" data-media-mode="output">🎬 AI 换角成片</button>
                  <button type="button" class="wf-media-toggle-btn ${state.inspectorMediaMode === 'control' ? 'is-active' : ''}" data-media-mode="control">🎞️ 原片控制片段</button>
                </div>
              ` : ''}

              <div class="wf-media-stage">
                ${activeVideoUrl ? `
                  <video controls playsinline preload="metadata" ${thumbUrl ? `poster="${esc(thumbUrl)}"` : ''} src="${esc(activeVideoUrl)}"></video>
                ` : `
                  ${thumbUrl ? `<img src="${esc(thumbUrl)}" alt="${esc(shot.id)}" />` : ''}
                  <div class="wf-thumb-fallback ${thumbUrl ? 'is-hidden' : ''}">
                    <span>${esc(shot.id)} · 尚未云端出片</span>
                  </div>
                `}
              </div>

              <div class="wf-media-note">
                <span>${activeVideoUrl ? '已加载实拍成片 · 支持逐帧拖动核对剪点' : '尚未渲染视频 · 修改下方描述后点击顶部「派发云端精拍」'}</span>
                <span>时长 ${esc(formatSec(shot.seconds || 5))}${shot.wall_sec ? ` · 实测渲染 ${Math.round(shot.wall_sec)}s` : ''}</span>
              </div>

              ${shotRefUrls.length ? `
                <div class="wf-drawer-refs">
                  ${shotRefUrls.map((url, idx) => `
                    <div class="wf-drawer-ref-item">
                      <img src="${esc(url)}" alt="参考图 ${idx + 1}" />
                    </div>
                  `).join('')}
                </div>
              ` : ''}
            </div>

            <div class="wf-form-grid">
              <div class="wf-form-row-2">
                <div class="wf-field">
                  <label for="wf-f-status">镜头状态</label>
                  <select id="wf-f-status" name="status" class="wf-select">
                    ${Object.entries(STATUS_LABELS).map(([k, label]) => `
                      <option value="${esc(k)}" ${shot.status === k ? 'selected' : ''}>${esc(label)}</option>
                    `).join('')}
                  </select>
                </div>
                <div class="wf-field">
                  <label>精剪入点 / 出点 (秒) <span class="wf-field-hint">总长 ${esc(shot.seconds || 5)}s</span></label>
                  <div class="wf-form-row-2" style="gap:8px;">
                    <input type="number" step="0.1" min="0" name="cut_in" class="wf-input" value="${esc(cutIn)}" placeholder="入点" aria-label="入点秒数" />
                    <input type="number" step="0.1" min="0" name="cut_out" class="wf-input" value="${esc(cutOut)}" placeholder="出点" aria-label="出点秒数" />
                  </div>
                </div>
              </div>

              <div class="wf-field">
                <label for="wf-f-summary">中文画面描述</label>
                <textarea id="wf-f-summary" name="summary_zh" class="wf-textarea" rows="2" placeholder="用通俗中文描述这一镜的画面主体、动作与情绪">${esc(shot.summary_zh || '')}</textarea>
              </div>

              <div class="wf-field">
                <label for="wf-f-prompt">视频生成提示词 (Prompt) <span class="wf-field-hint">${esc(shot.engine || 'H3')}</span></label>
                <textarea id="wf-f-prompt" name="prompt" class="wf-textarea mono" rows="3" placeholder="底层视频引擎 Prompt">${esc(shot.prompt || '')}</textarea>
              </div>

              <div class="wf-field">
                <label for="wf-f-dialogue">台词 / 旁白（每行一句）</label>
                <textarea id="wf-f-dialogue" name="dialogue" class="wf-textarea" rows="2" placeholder="输入本镜头台词或旁白">${esc(dialogueText)}</textarea>
              </div>

              <div class="wf-field">
                <label for="wf-f-notes">导演备注 / 质检记录</label>
                <input id="wf-f-notes" type="text" name="notes" class="wf-input" value="${esc(shot.notes || '')}" placeholder="记录修改要点、口型或构图意见" />
              </div>

              ${state.retakeOpen ? `
                <div class="wf-retake-box">
                  <span class="wf-retake-box-title">↻ 打回云端重拍 — 填写重拍原因</span>
                  <input type="text" class="wf-input" data-retake-reason placeholder="例如：角色转身速度太快 / 爪部轻微穿帮 / 需要更暖的光线" value="${esc(shot.notes || '')}" />
                  <div style="display:flex;gap:8px;justify-content:flex-end;">
                    <button type="button" class="wf-btn wf-btn-ghost wf-btn-sm" data-cancel-retake>取消</button>
                    <button type="button" class="wf-btn wf-btn-rose wf-btn-sm" data-confirm-retake="${esc(shot.id)}">确认打回重拍</button>
                  </div>
                </div>
              ` : ''}
            </div>
          </form>

          <div class="wf-drawer-footer">
            <div style="display:flex;gap:8px;">
              <button type="button" class="wf-btn wf-btn-emerald wf-btn-sm" data-drawer-approve="${esc(shot.id)}">✓ 标记通过</button>
              <button type="button" class="wf-btn wf-btn-rose wf-btn-sm" data-toggle-retake>↻ 打回重拍</button>
            </div>
            <button type="submit" form="wf-shot-form" class="wf-btn wf-btn-gold" ${state.busy.savingShot ? 'disabled' : ''}>
              ${state.busy.savingShot ? '保存中...' : '💾 保存修改'}
            </button>
          </div>
        </aside>
      </div>
    `;
  }

  function renderDispatchModalHtml() {
    const info = state.dispatchModal;
    if (!info) return '';
    return `
      <div class="wf-modal-backdrop" data-close-dispatch>
        <div class="wf-modal" role="dialog" aria-modal="true" aria-label="云端精拍派发清单">
          <div class="wf-modal-head">
            <span class="wf-modal-title">⚡ 云端精拍清单已生成</span>
            <button type="button" class="wf-btn wf-btn-ghost wf-btn-sm" data-close-dispatch>✕</button>
          </div>
          <div class="wf-modal-body">
            <div class="wf-dispatch-stats">
              <div class="wf-stat-box">
                <span class="wf-stat-label">本次派发镜头</span>
                <span class="wf-stat-val">${esc(info.shot_count ?? 0)} 镜</span>
              </div>
              <div class="wf-stat-box">
                <span class="wf-stat-label">预计 Colab 算力</span>
                <span class="wf-stat-val">${esc(info.est_cu ?? 0)} CU</span>
              </div>
              <div class="wf-stat-box">
                <span class="wf-stat-label">预计极低费用</span>
                <span class="wf-stat-val" style="color:#34D399;">¥${esc(info.est_cny ?? 0)}</span>
              </div>
            </div>
            <div class="wf-field">
              <label>生成的 CineForge 任务清单路径</label>
              <div class="wf-code-box" style="padding:10px 12px;"><pre>${esc(info.manifest_path || 'studio/data/dispatch/')}</pre></div>
            </div>
            <div class="wf-field">
              <label>
                <span>脱敏 Colab Worker 启动片段（零密钥泄露 · 密钥仅由本机内存读取）</span>
                <button type="button" class="wf-btn wf-btn-cyan wf-btn-sm" data-copy-snippet>📋 复制代码</button>
              </label>
              <div class="wf-code-box"><pre>${esc(info.colab_snippet || '# 暂未提供 Colab 片段')}</pre></div>
            </div>
          </div>
          <div class="wf-modal-foot">
            <button type="button" class="wf-btn wf-btn-gold" data-close-dispatch>完成并返回看板</button>
          </div>
        </div>
      </div>
    `;
  }

  function renderRefLightboxHtml() {
    const ref = state.refLightbox;
    if (!ref) return '';
    return `
      <div class="wf-modal-backdrop" data-close-ref>
        <div class="wf-modal" role="dialog" aria-modal="true" aria-label="角色定妆参考图">
          <div class="wf-modal-head">
            <span class="wf-modal-title">🎭 ${esc(ref.name || ref.id || '视觉锁参考图')}</span>
            <button type="button" class="wf-btn wf-btn-ghost wf-btn-sm" data-close-ref>✕</button>
          </div>
          <div class="wf-modal-body">
            ${isValidUrl(ref.url) ? `<img class="wf-ref-lightbox-img" src="${esc(ref.url)}" alt="${esc(ref.name || '')}" />` : ''}
            ${ref.prompt ? `<p style="margin:0;font-size:13px;color:var(--text-secondary);line-height:1.5;">${esc(ref.prompt)}</p>` : ''}
          </div>
        </div>
      </div>
    `;
  }

  function renderModals() {
    const html = renderInspectorDrawerHtml() + renderDispatchModalHtml() + renderRefLightboxHtml();
    const existing = document.getElementById('wf-overlay-root');
    if (!html) {
      if (existing) existing.innerHTML = '';
      return;
    }
    const root = getOverlayRoot();
    root.innerHTML = html;
  }

  // ---- Actions ----

  async function handleAdvanceStage(stageKey) {
    if (state.busy.advancing) return;
    state.busy.advancing = true;
    renderAll();
    try {
      const resp = await api.advanceStage(state.projectId, stageKey);
      if (isStale()) return;
      if (resp?.stages && state.detail) state.detail.stages = resp.stages;
      if (resp?.project && state.detail) state.detail.project = { ...state.detail.project, ...resp.project };
      const stages = getMergedStages();
      const nextActive = stages.find((s) => s.status === 'active');
      if (nextActive) state.selectedStageKey = nextActive.key;
      toast('阶段已确认推进！', 'success');
    } catch (err) {
      toast(err?.message || '推进阶段失败', 'error');
    } finally {
      if (!isStale()) {
        state.busy.advancing = false;
        renderAll();
      }
    }
  }

  async function handleRenderPreview() {
    if (state.busy.renderingPreview) return;
    state.busy.renderingPreview = true;
    state.previewJob = {
      id: '',
      status: 'running',
      progress: 12,
      message: '正在启动 FFmpeg 预演片合成任务...',
      videoUrl: '',
    };
    updateHeaderProgressOnly();

    try {
      const resp = await api.renderPreview(state.projectId);
      if (isStale()) return;
      const jobId = resp?.job_id || resp?.id || '';
      state.previewJob = {
        id: jobId,
        status: resp?.status || 'running',
        progress: 20,
        message: '正在合成高清 16:9 预演片与环境音轨...',
        videoUrl: resp?.video_url || resp?.preview_video_url || '',
      };
      updateHeaderProgressOnly();

      if (jobId) {
        clearPoll();
        pollTimer = setInterval(async () => {
          try {
            const job = await api.job(jobId);
            if (isStale() || !job) return;
            const st = job.status || 'running';
            const pct = Number.isFinite(Number(job.progress)) ? Number(job.progress) : (st === 'completed' || st === 'done' ? 100 : Math.min(92, (state.previewJob?.progress || 20) + 12));
            const outUrl = job.video_url || job.preview_video_url || job.output_url || job.result?.video_url || job.result?.preview_video_url || '';

            state.previewJob = {
              id: jobId,
              status: st,
              progress: st === 'completed' || st === 'done' ? 100 : pct,
              message: job.message || (st === 'completed' || st === 'done' ? '预演片合成完成，点击立即播放！' : '正在合成预演片...'),
              videoUrl: outUrl || state.previewJob?.videoUrl || '',
            };
            updateHeaderProgressOnly();

            if (st === 'completed' || st === 'done') {
              clearPoll();
              state.busy.renderingPreview = false;
              if (outUrl && state.detail?.project) {
                state.detail.project.preview_video_url = outUrl;
              }
              toast('预演片合成完成！', 'success');
              refreshDetailSilent();
            } else if (st === 'failed' || st === 'error') {
              clearPoll();
              state.busy.renderingPreview = false;
              toast(job.error || job.message || '预演合成失败', 'error');
              updateHeaderProgressOnly();
            }
          } catch {
            // keep waiting on transient poll errors
          }
        }, 1200);
      }
    } catch (err) {
      if (isStale()) return;
      state.busy.renderingPreview = false;
      state.previewJob = {
        id: '',
        status: 'failed',
        progress: 0,
        message: err?.message || '启动预演片合成失败',
        videoUrl: '',
      };
      updateHeaderProgressOnly();
      toast(err?.message || '启动预演片合成失败', 'error');
    }
  }

  async function handleDispatchCloud() {
    if (state.busy.dispatching) return;
    state.busy.dispatching = true;
    renderAll();
    try {
      const resp = await api.dispatchCloud(state.projectId);
      if (isStale()) return;
      const isGuestServer = document.body.classList.contains('is-server-guest');
      if (isGuestServer) {
        const pos = resp?.queue_pos ?? 1;
        toast(`⚡ 已加入共享显卡队列（当前第 ${pos} 位），完成后自动提示播放`, 'success');
      } else {
        state.dispatchModal = resp;
        toast(`已派发 ${resp?.shot_count ?? 0} 个镜头至云端清单`, 'success');
      }
      await refreshDetailSilent();
    } catch (err) {
      toast(err?.message || '派发云端失败', 'error');
    } finally {
      if (!isStale()) {
        state.busy.dispatching = false;
        renderAll();
      }
    }
  }

  function handleWatchFilm() {
    const proj = state.detail?.project || {};
    const videoUrl = getWatchableVideoUrl();
    if (!videoUrl) {
      toast('请先点击「一键合成预演片」生成可播放影片', 'info');
      return;
    }
    if (typeof ctx.openVideoModal === 'function') {
      ctx.openVideoModal({
        title: proj.title || state.projectId,
        subtitle: proj.final_video_url ? '电影母版成片' : 'FFmpeg 实时预演成片',
        videoUrl,
        posterUrl: proj.poster_url || '',
        badges: [
          proj.mode === 'v2v' ? 'V2V 换角' : '原创电影',
          `${proj.rendered_shots ?? 0}/${proj.total_shots ?? 0} 镜`,
        ],
        onClone: () => ctx.navigate(`#create?clone=${encodeURIComponent(state.projectId)}&mode=${encodeURIComponent(proj.mode || 'original')}`),
      });
    }
  }

  async function handleQuickApprove(shotId) {
    try {
      const resp = await api.updateShot(state.projectId, shotId, { status: 'approved' });
      if (isStale()) return;
      applyUpdatedShot(shotId, resp?.shot || { status: 'approved' }, resp?.project_summary);
      toast(`镜头 ${shotId} 已标记过审`, 'success');
    } catch (err) {
      toast(err?.message || '更新镜头状态失败', 'error');
    }
  }

  function applyUpdatedShot(shotId, updatedShot, projectSummary) {
    if (!state.detail?.shots) return;
    const idx = state.detail.shots.findIndex((s) => s.id === shotId);
    if (idx >= 0) {
      state.detail.shots[idx] = { ...state.detail.shots[idx], ...updatedShot };
    }
    if (projectSummary && state.detail.project) {
      state.detail.project = { ...state.detail.project, ...projectSummary };
    } else if (state.detail.project) {
      state.detail.project.approved_shots = state.detail.shots.filter((s) => s.status === 'approved').length;
    }
    renderAll();
  }

  function handleDagStageAction(stageKey) {
    if (stageKey === 'refs') {
      state.activeView = 'storyboard';
      renderAll();
      return;
    }
    if (stageKey === 'render') {
      handleDispatchCloud();
      return;
    }
    if (stageKey === 'master') {
      handleRenderPreview();
      return;
    }
    state.selectedStageKey = stageKey;
    state.activeView = 'kanban';
    renderAll();
  }

  // ---- Event Delegation for Main Container ----

  function onContainerChange(e) {
    const sel = e.target.closest('[data-project-select]');
    if (sel) {
      const nextId = sel.value;
      if (nextId && nextId !== state.projectId) {
        ctx.navigate(`#workflow/${encodeURIComponent(nextId)}`);
      }
    }
  }

  async function onContainerClick(e) {
    if (e.target.closest('[data-toggle-director]')) {
      state.directorExpanded = !state.directorExpanded;
      state.directorUserToggled = true;
      renderAll();
      return;
    }

    const finalModeBtn = e.target.closest('[data-final-mode]');
    if (finalModeBtn) {
      const nextMode = finalModeBtn.dataset.finalMode;
      if (nextMode && nextMode !== state.finalPlayerMode) {
        state.finalPlayerMode = nextMode;
        renderAll();
      }
      return;
    }

    const cancelJobBtn = e.target.closest('[data-cancel-cloud-job]');
    if (cancelJobBtn) {
      const qid = cancelJobBtn.dataset.cancelCloudJob;
      try {
        await api.cancelQueueJob(qid);
        clearCloudPoll();
        toast('已取消排队，并释放本次免费额度', 'info');
        await refreshDetailSilent();
      } catch (err) {
        toast(err?.message || '取消排队失败', 'error');
      }
      return;
    }

    const actionBtn = e.target.closest('[data-action]');
    if (actionBtn) {
      const act = actionBtn.dataset.action;
      if (act === 'render-preview') handleRenderPreview();
      else if (act === 'dispatch-cloud') handleDispatchCloud();
      else if (act === 'watch-film') handleWatchFilm();
      return;
    }

    const advBtn = e.target.closest('[data-advance-stage]');
    if (advBtn) {
      handleAdvanceStage(advBtn.dataset.advanceStage);
      return;
    }

    const stageBtn = e.target.closest('[data-select-stage]');
    if (stageBtn) {
      state.selectedStageKey = stageBtn.dataset.selectStage;
      renderAll();
      return;
    }

    const viewBtn = e.target.closest('[data-switch-view]');
    if (viewBtn) {
      const nextView = viewBtn.dataset.switchView;
      if (nextView && nextView !== state.activeView) {
        state.activeView = nextView;
        renderAll();
      }
      return;
    }

    const sceneBtn = e.target.closest('[data-filter-scene]');
    if (sceneBtn) {
      const scene = sceneBtn.dataset.filterScene || '';
      if (scene !== state.selectedScene) {
        state.selectedScene = scene;
        fetchProjectDetail(state.projectId, scene);
      }
      return;
    }

    const approveBtn = e.target.closest('[data-quick-approve]');
    if (approveBtn) {
      e.stopPropagation();
      handleQuickApprove(approveBtn.dataset.quickApprove);
      return;
    }

    const retakeBtn = e.target.closest('[data-quick-retake]');
    if (retakeBtn) {
      e.stopPropagation();
      state.inspectorShotId = retakeBtn.dataset.quickRetake;
      state.inspectorMediaMode = 'output';
      state.retakeOpen = true;
      renderModals();
      return;
    }

    const refCard = e.target.closest('[data-open-ref]');
    if (refCard) {
      const idx = Number(refCard.dataset.openRef);
      const ref = state.detail?.refs?.[idx];
      if (ref) {
        state.refLightbox = ref;
        renderModals();
      }
      return;
    }

    const shotTrigger = e.target.closest('[data-open-shot]');
    if (shotTrigger) {
      state.inspectorShotId = shotTrigger.dataset.openShot;
      state.inspectorMediaMode = 'output';
      state.retakeOpen = false;
      renderModals();
    }
  }

  container.addEventListener('change', onContainerChange);
  container.addEventListener('click', onContainerClick);

  // ---- Event Delegation for Overlay Root (Drawer & Modals) ----

  async function onOverlayClick(e) {
    if (e.target.closest('[data-close-dispatch]') && (e.target.hasAttribute('data-close-dispatch') || e.target.closest('button[data-close-dispatch]'))) {
      state.dispatchModal = null;
      renderModals();
      return;
    }

    if (e.target.closest('[data-close-ref]') && (e.target.hasAttribute('data-close-ref') || e.target.closest('button[data-close-ref]'))) {
      state.refLightbox = null;
      renderModals();
      return;
    }

    if (e.target.closest('[data-copy-snippet]')) {
      const text = state.dispatchModal?.colab_snippet || '';
      await copyText(text);
      toast('已复制 Colab 脱敏接入代码', 'success');
      return;
    }

    if (e.target.hasAttribute('data-close-drawer') || e.target.closest('button[data-close-drawer]')) {
      state.inspectorShotId = null;
      state.retakeOpen = false;
      renderModals();
      return;
    }

    const stepBtn = e.target.closest('[data-step-shot]');
    if (stepBtn && !stepBtn.disabled) {
      const nextIdx = Number(stepBtn.dataset.stepShot);
      const target = state.detail?.shots?.[nextIdx];
      if (target) {
        state.inspectorShotId = target.id;
        state.inspectorMediaMode = 'output';
        state.retakeOpen = false;
        renderModals();
      }
      return;
    }

    const mediaModeBtn = e.target.closest('[data-media-mode]');
    if (mediaModeBtn) {
      state.inspectorMediaMode = mediaModeBtn.dataset.mediaMode;
      renderModals();
      return;
    }

    const drawerApproveBtn = e.target.closest('[data-drawer-approve]');
    if (drawerApproveBtn) {
      await handleQuickApprove(drawerApproveBtn.dataset.drawerApprove);
      return;
    }

    if (e.target.closest('[data-toggle-retake]')) {
      state.retakeOpen = !state.retakeOpen;
      renderModals();
      return;
    }

    if (e.target.closest('[data-cancel-retake]')) {
      state.retakeOpen = false;
      renderModals();
      return;
    }

    const confirmRetakeBtn = e.target.closest('[data-confirm-retake]');
    if (confirmRetakeBtn) {
      const shotId = confirmRetakeBtn.dataset.confirmRetake;
      const overlay = document.getElementById('wf-overlay-root');
      const reason = overlay?.querySelector('[data-retake-reason]')?.value?.trim() || '导演要求重新拍摄以提升一致性';
      const promptVal = overlay?.querySelector('#wf-f-prompt')?.value?.trim() || '';
      try {
        const resp = await api.retakeShot(state.projectId, shotId, { reason, prompt: promptVal });
        if (isStale()) return;
        state.retakeOpen = false;
        applyUpdatedShot(shotId, resp?.shot || { status: 'retake', notes: reason });
        toast(`镜头 ${shotId} 已打回重拍`, 'info');
      } catch (err) {
        toast(err?.message || '打回重拍失败', 'error');
      }
    }
  }

  async function onOverlaySubmit(e) {
    const form = e.target.closest('#wf-shot-form');
    if (!form) return;
    e.preventDefault();
    if (state.busy.savingShot) return;

    const shotId = form.dataset.shotId;
    const fd = new FormData(form);
    const dialogueRaw = String(fd.get('dialogue') || '');
    const dialogueArr = dialogueRaw.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
    const cutInNum = Number(fd.get('cut_in'));
    const cutOutNum = Number(fd.get('cut_out'));

    const patch = {
      status: String(fd.get('status') || 'draft'),
      summary_zh: String(fd.get('summary_zh') || '').trim(),
      prompt: String(fd.get('prompt') || '').trim(),
      dialogue: dialogueArr,
      cut_in: Number.isFinite(cutInNum) ? cutInNum : 0,
      cut_out: Number.isFinite(cutOutNum) ? cutOutNum : null,
      notes: String(fd.get('notes') || '').trim(),
    };

    state.busy.savingShot = true;
    renderModals();
    try {
      const resp = await api.updateShot(state.projectId, shotId, patch);
      if (isStale()) return;
      state.busy.savingShot = false;
      applyUpdatedShot(shotId, resp?.shot || patch, resp?.project_summary);
      toast(`镜头 ${shotId} 修改已保存`, 'success');
    } catch (err) {
      if (!isStale()) {
        state.busy.savingShot = false;
        renderModals();
      }
      toast(err?.message || '保存失败', 'error');
    }
  }

  await loadInitialData();
}
