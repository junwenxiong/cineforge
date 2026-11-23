/**
 * CineForge Studio — 灵感广场 (Discover View)
 * Aligns with Jimeng / Kling cinema-grade dark visual showcase.
 */

let _cleanupFns = [];
let _heroTimer = null;

function clearRuntime() {
  if (_heroTimer) {
    clearInterval(_heroTimer);
    _heroTimer = null;
  }
  while (_cleanupFns.length) {
    const fn = _cleanupFns.pop();
    try { fn(); } catch (_) {}
  }
}

export function destroy() {
  clearRuntime();
}

const V2V_FEATURES = [
  {
    key: 'lip_sync',
    label: '🎙️ 原声口型同步',
    detail: '100% 保留原剧经典台词、停顿与情绪爆发力，猫咪嘴型与神态逐帧对齐原片音轨。'
  },
  {
    key: 'desub',
    label: '✨ 自动去字幕',
    detail: '拍摄前自动定位并无痕抹除原视频底部硬字幕，成片画面干净纯粹、无残影重影。'
  },
  {
    key: 'paw_guard',
    label: '🐾 护爪防穿帮',
    detail: '针对手指动作与古装衣袖启用空间锚点保护，告别常见 AI 视频的多爪畸变与动作瞬移。'
  }
];

const GALLERY_FILTERS = [
  { key: 'all', label: '全部作品' },
  { key: 'film', label: '30分钟原创电影' },
  { key: 'v2v', label: '名场面换角 V2V' },
  { key: '3d', label: '院线级 3D 动画' },
  { key: 'drama', label: '高分悬疑/萌宠短剧' }
];

function iconSpeaker(muted) {
  if (muted) {
    return `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/></svg>`;
  }
  return `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/></svg>`;
}

function iconPlay(size = 15) {
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="currentColor"><polygon points="6 4 20 12 6 20 6 4"/></svg>`;
}

function matchesFilter(item, filterKey) {
  if (filterKey === 'all') return true;
  const hay = [
    item.category || '',
    item.mode || '',
    item.badge || '',
    item.title || '',
    item.subtitle || '',
    item.engine || '',
    ...(Array.isArray(item.tags) ? item.tags : [])
  ].join(' ').toLowerCase();

  if (filterKey === 'v2v') {
    return item.mode === 'v2v' || Boolean(item.side_by_side_url) || hay.includes('v2v') || hay.includes('换角') || hay.includes('名场面') || hay.includes('猫咪重演');
  }
  if (filterKey === 'film') {
    return hay.includes('film') || hay.includes('movie') || hay.includes('电影') || hay.includes('30分钟') || hay.includes('33分钟') || hay.includes('星核') || hay.includes('守夜人') || hay.includes('长片');
  }
  if (filterKey === '3d') {
    return hay.includes('3d') || hay.includes('动画') || hay.includes('皮克斯') || hay.includes('机甲') || hay.includes('科幻') || hay.includes('starcore') || hay.includes('守夜人');
  }
  if (filterKey === 'drama') {
    return hay.includes('悬疑') || hay.includes('短剧') || hay.includes('萌宠') || hay.includes('残响') || hay.includes('三花') || hay.includes('猫路') || hay.includes('echo') || hay.includes('catfilm') || hay.includes('streetangel');
  }
  return true;
}

function pickV2VClassics(items) {
  const sbs = (items || []).filter((it) => Boolean(it.side_by_side_url));
  const candidates = sbs.length ? sbs : (items || []).filter((it) => it.mode === 'v2v');
  if (!candidates.length) return [];

  const priorityTokens = ['三国', '西游', '红楼'];
  const ordered = [];
  const used = new Set();

  for (const token of priorityTokens) {
    const found = candidates.find((it) => !used.has(it.id) && `${it.title || ''}${it.id || ''}`.includes(token));
    if (found) {
      ordered.push(found);
      used.add(found.id);
    }
  }
  for (const it of candidates) {
    if (!used.has(it.id) && ordered.length < 4) {
      ordered.push(it);
      used.add(it.id);
    }
  }
  return ordered;
}

function buildCloneRoute(item, forceMode) {
  const mode = forceMode || (item.mode === 'v2v' || item.side_by_side_url ? 'v2v' : 'original');
  const cloneId = item.template_id || item.id || item.project_id || '';
  const params = new URLSearchParams();
  if (mode) params.set('mode', mode);
  if (cloneId) params.set('clone', cloneId);
  return `#create?${params.toString()}`;
}

function openItemModal(ctx, item, preferSideBySide = false) {
  if (!ctx || typeof ctx.openVideoModal !== 'function') return;
  const badges = [item.badge, item.engine, item.duration_label, item.cost_label].filter(Boolean);
  ctx.openVideoModal({
    title: item.title || '影铸作品预览',
    subtitle: item.subtitle || '',
    videoUrl: item.video_url || item.side_by_side_url || '',
    sideBySideUrl: item.side_by_side_url || '',
    posterUrl: item.poster_url || '',
    badges,
    projectId: item.project_id || null,
    initialMode: preferSideBySide && item.side_by_side_url ? 'side_by_side' : 'clean',
    onClone: () => ctx.navigate(buildCloneRoute(item))
  });
}

export async function render(container, ctx) {
  clearRuntime();
  const esc = ctx.escHtml || ((s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])));

  container.innerHTML = `
    <div class="cf-page cf-loading">
      <div class="cf-skel-hero"></div>
      <div class="cf-skel-grid">
        <div class="cf-skel-card"></div>
        <div class="cf-skel-card"></div>
        <div class="cf-skel-card"></div>
      </div>
    </div>
  `;

  let data;
  let projectsData = [];
  try {
    const [showcaseRes, projRes] = await Promise.all([
      ctx.store?.getOrFetch
        ? ctx.store.getOrFetch('showcase', () => ctx.api.showcase(), { ttlMs: 30000 })
        : ctx.api.showcase(),
      ctx.api.projects().catch(() => ({ projects: ctx.store?.get?.('projects') || [] })),
    ]);
    data = showcaseRes;
    projectsData = Array.isArray(projRes?.projects) ? projRes.projects : [];
  } catch (err) {
    container.innerHTML = `
      <div class="cf-page">
        <div class="empty-state">
          <h3>灵感广场暂未连通</h3>
          <p>${esc(err?.message || '请确认 CineForge Studio 后端服务已启动')}</p>
        </div>
      </div>
    `;
    return;
  }

  const allItems = Array.isArray(data?.items) ? data.items : [];
  const heroList = (Array.isArray(data?.hero) && data.hero.length ? data.hero : allItems.slice(0, 4)).slice(0, 4);
  const myWorks = projectsData.filter((p) => p.is_mine || String(p.id || '').startsWith('studio_'));
  const stats = data?.stats || {};
  const v2vItems = pickV2VClassics(allItems);

  const medianSec = Math.round(((Number(stats.median_h3_sec) || 43) + (Number(stats.median_ltx_sec) || 38)) / 2);
  const est30MinUsd = Number(stats.est_cost_30min_usd) || 11;
  const totalShots = Number(stats.total_shots_rendered) || 400;
  const totalFilms = Number(stats.total_films) || Math.max(allItems.length, 6);

  const state = {
    heroIdx: 0,
    heroMuted: true,
    v2vIdx: 0,
    v2vViewMode: 'side_by_side', // 'side_by_side' | 'cat'
    activeFeature: V2V_FEATURES[0].key,
    filter: 'all'
  };

  container.innerHTML = `
    <div class="cf-page">
      ${myWorks.length ? `<section class="cf-section cf-my-works-section" id="cf-my-works-section" aria-label="我刚创作的作品"></section>` : ''}
      <section class="cf-hero" id="cf-hero-stage" aria-label="精选大片轮播"></section>
      ${v2vItems.length ? `<section class="cf-section" id="cf-v2v-section" aria-label="名场面换角互动专区"></section>` : ''}
      <section class="cf-section" id="cf-gallery-section" aria-label="精选样片画廊"></section>
    </div>
  `;

  const myWorksEl = container.querySelector('#cf-my-works-section');
  const heroEl = container.querySelector('#cf-hero-stage');
  const v2vEl = container.querySelector('#cf-v2v-section');
  const galleryEl = container.querySelector('#cf-gallery-section');

  function renderMyWorks() {
    if (!myWorksEl || !myWorks.length) return;
    myWorksEl.innerHTML = `
      <div class="cf-section-head">
        <div class="cf-section-title-group">
          <div class="cf-section-title-row">
            <h2 class="cf-section-title">🎬 我刚创作的作品</h2>
            <span class="badge badge-emerald">仅当前浏览器会话可见</span>
          </div>
          <p class="cf-section-sub">打开即可查看实时生成进度、在线播放成片或下载 MP4</p>
        </div>
        <a href="#create" class="btn btn-primary btn-sm">✨ 再做一个</a>
      </div>
      <div class="cf-my-works-grid">
        ${myWorks.map((p) => {
          const watchUrl = p.final_video_url || p.preview_video_url || '';
          const isReady = Boolean(p.final_video_url);
          const statusText = isReady
            ? '🎉 成片已生成'
            : p.cloud_status === 'rendering'
              ? '⚡ 云端显卡渲染中'
              : p.cloud_status === 'staging' || p.cloud_status === 'queued'
                ? '🕒 已加入云端队列'
                : p.preview_video_url
                  ? '🎬 预演已就绪'
                  : '📝 分镜已生成';
          return `
            <article class="cf-my-work-card" data-my-project="${esc(p.id)}">
              <div class="cf-my-work-top">
                <div class="cf-my-work-title">${esc(p.title || p.id)}</div>
                <span class="badge ${isReady ? 'badge-emerald' : 'badge-cyan'}">${esc(statusText)}</span>
              </div>
              <div class="cf-my-work-meta">
                <span>${p.mode === 'v2v' ? '🐱 V2V 换角' : '✨ 原创短片'}</span>
                <span>·</span>
                <span>已完成 ${esc(p.rendered_shots ?? 0)}/${esc(p.total_shots ?? 0)} 镜</span>
              </div>
              <div class="cf-my-work-actions">
                ${watchUrl ? `
                  <button type="button" class="cf-card-btn is-primary" data-my-play="${esc(p.id)}">
                    <span>▶ ${isReady ? '播放成片' : '看预演版'}</span>
                  </button>
                ` : ''}
                <a href="#workflow/${encodeURIComponent(p.id)}" class="cf-card-btn is-grow">
                  <span>${isReady ? '下载 / 查看详情' : '查看实时进度'}</span>
                </a>
              </div>
            </article>
          `;
        }).join('')}
      </div>
    `;
    const byId = new Map(myWorks.map((p) => [p.id, p]));
    myWorksEl.querySelectorAll('[data-my-play]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const proj = byId.get(btn.dataset.myPlay);
        if (!proj) return;
        const vUrl = proj.final_video_url || proj.preview_video_url;
        if (vUrl && typeof ctx.openVideoModal === 'function') {
          ctx.openVideoModal({
            title: proj.title || proj.id,
            subtitle: proj.final_video_url ? '共享云端生成成片' : '即时预演版',
            videoUrl: vUrl,
            sideBySideUrl: proj.side_by_side_url || '',
            posterUrl: proj.poster_url || '',
            badges: [proj.mode === 'v2v' ? 'V2V 换角' : '原创短片', `${proj.rendered_shots ?? 0}/${proj.total_shots ?? 0} 镜`],
          });
        }
      });
    });
  }

  /* ---------------- 1. Hero Banner Renderer ---------------- */
  function renderHero() {
    if (!heroEl || !heroList.length) return;
    const item = heroList[state.heroIdx] || heroList[0];
    const projectTarget = item.project_id ? `#workflow/${encodeURIComponent(item.project_id)}` : '#workflow';
    const cloneTarget = buildCloneRoute(item);
    const hasPoster = Boolean(item.poster_url);
    const flagshipText = `★ 实拍验证 · 33分钟AI电影仅≈$${est30MinUsd}`;
    const rawBadge = String(item.badge || '').trim();
    const normBadge = (s) => s.replace(/[\s★·•]/g, '').toLowerCase();
    const isDuplicateBadge = !rawBadge ||
      normBadge(rawBadge) === normBadge(flagshipText) ||
      normBadge(flagshipText).includes(normBadge(rawBadge)) ||
      (rawBadge.includes('33分钟') && rawBadge.includes('$'));

    heroEl.innerHTML = `
      <div class="cf-hero-media">
        ${hasPoster ? `<img class="cf-hero-poster" src="${esc(item.poster_url)}" alt="${esc(item.title)}" />` : `<div class="cf-poster-fallback"></div>`}
        ${item.video_url ? `<video class="cf-hero-video" src="${esc(item.video_url)}" ${hasPoster ? `poster="${esc(item.poster_url)}"` : ''} autoplay ${state.heroMuted ? 'muted' : ''} loop playsinline preload="metadata"></video>` : ''}
      </div>
      <div class="cf-hero-scrim"></div>

      <div class="cf-hero-topbar">
        <div class="cf-hero-eyebrow">
          <span class="cf-flagship-badge">${esc(flagshipText)}</span>
          ${!isDuplicateBadge ? `<span class="cf-engine-chip">${esc(rawBadge)}</span>` : ''}
        </div>
        <button type="button" class="cf-mute-btn" data-action="toggle-mute" aria-label="切换声音">
          ${iconSpeaker(state.heroMuted)}
          <span>${state.heroMuted ? '静音预览' : '原声播放'}</span>
        </button>
      </div>

      <div class="cf-hero-body">
        <div class="cf-hero-content">
          <h1 class="cf-hero-title">${esc(item.title || '影铸 AI 电影工坊')}</h1>
          <p class="cf-hero-pitch">${esc(item.subtitle || '一句话创意自动拆剧本、定角色、排分镜，云端极低成本批量拍成电影级短剧。')}</p>

          <div class="cf-hero-metrics">
            <span class="cf-metric-pill">⚡ 单镜约 ${esc(medianSec)} 秒</span>
            <span class="cf-metric-pill is-cyan">🎬 ${esc(item.engine || 'H3 + LTX-2.5 双引擎')}</span>
            <span class="cf-metric-pill is-emerald"><span class="cf-dot-live"></span> 白领评测免费体验</span>
          </div>

          <div class="cf-hero-actions">
            <button type="button" class="cf-btn-gold" data-action="hero-play">
              ${iconPlay(14)}
              <span>立即播放大片</span>
            </button>
            <button type="button" class="cf-btn-glass" data-action="hero-clone" data-route="${esc(cloneTarget)}">
              <span>✨ 用同款拍一条</span>
            </button>
            <button type="button" class="cf-btn-subtle" data-action="hero-workflow" data-route="${esc(projectTarget)}">
              <span>进入工作流看板 →</span>
            </button>
          </div>
        </div>

        <div class="cf-hero-switcher">
          <span class="cf-switcher-label">精选样片 · ${state.heroIdx + 1} / ${heroList.length}</span>
          <div class="cf-hero-dots" role="tablist" aria-label="切换精选大片">
            ${heroList.map((h, i) => `
              <button
                type="button"
                role="tab"
                aria-selected="${i === state.heroIdx ? 'true' : 'false'}"
                class="cf-hero-dot ${i === state.heroIdx ? 'is-active' : ''}"
                data-hero-idx="${i}"
              >
                <div class="cf-hero-dot-thumb">
                  ${h.poster_url ? `<img src="${esc(h.poster_url)}" alt="${esc(h.title)}" />` : `<div class="cf-poster-fallback"></div>`}
                </div>
                <div class="cf-hero-dot-meta">
                  <span class="cf-hero-dot-title">${esc(h.title)}</span>
                  <span class="cf-hero-dot-sub">${esc(h.duration_label || h.engine || '实拍样片')}</span>
                </div>
              </button>
            `).join('')}
          </div>
        </div>
      </div>
    `;

    const videoEl = heroEl.querySelector('.cf-hero-video');
    if (videoEl) {
      videoEl.muted = state.heroMuted;
      const reveal = () => videoEl.classList.add('is-ready');
      videoEl.addEventListener('loadeddata', reveal, { once: true });
      videoEl.addEventListener('canplay', reveal, { once: true });
      videoEl.play?.().catch(() => {});
    }

    heroEl.querySelector('[data-action="toggle-mute"]')?.addEventListener('click', () => {
      state.heroMuted = !state.heroMuted;
      if (videoEl) {
        videoEl.muted = state.heroMuted;
        if (!state.heroMuted) videoEl.play?.().catch(() => {});
      }
      const btn = heroEl.querySelector('[data-action="toggle-mute"]');
      if (btn) {
        btn.innerHTML = `${iconSpeaker(state.heroMuted)}<span>${state.heroMuted ? '静音预览' : '原声播放'}</span>`;
      }
    });

    heroEl.querySelector('[data-action="hero-play"]')?.addEventListener('click', () => {
      openItemModal(ctx, item, false);
    });

    heroEl.querySelector('[data-action="hero-clone"]')?.addEventListener('click', (e) => {
      ctx.navigate(e.currentTarget.dataset.route);
    });

    heroEl.querySelector('[data-action="hero-workflow"]')?.addEventListener('click', (e) => {
      ctx.navigate(e.currentTarget.dataset.route);
    });

    heroEl.querySelectorAll('[data-hero-idx]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const nextIdx = Number(btn.dataset.heroIdx);
        if (!Number.isNaN(nextIdx) && nextIdx !== state.heroIdx) {
          state.heroIdx = nextIdx;
          renderHero();
          resetHeroAutoAdvance();
        }
      });
    });
  }

  function resetHeroAutoAdvance() {
    if (_heroTimer) clearInterval(_heroTimer);
    if (heroList.length <= 1) return;
    _heroTimer = setInterval(() => {
      if (!document.body.contains(heroEl)) return;
      if (heroEl.matches(':hover')) return;
      state.heroIdx = (state.heroIdx + 1) % heroList.length;
      renderHero();
    }, 9500);
  }

  /* ---------------- 2. V2V Interactive Comparison Spotlight ---------------- */
  function renderV2VSpotlight() {
    if (!v2vEl || !v2vItems.length) return;
    const active = v2vItems[state.v2vIdx] || v2vItems[0];
    const isSideBySide = state.v2vViewMode === 'side_by_side' && Boolean(active.side_by_side_url);
    const activeSrc = isSideBySide ? active.side_by_side_url : (active.video_url || active.side_by_side_url);
    const activeFeat = V2V_FEATURES.find((f) => f.key === state.activeFeature) || V2V_FEATURES[0];
    const cloneUrl = buildCloneRoute(active, 'v2v');

    v2vEl.innerHTML = `
      <div class="cf-v2v-card">
        <div class="cf-v2v-header">
          <div class="cf-section-title-group">
            <div class="cf-section-title-row">
              <h2 class="cf-section-title">名场面换角 · 真人变猫咪</h2>
              <span class="badge badge-gold">V2V 实拍对照</span>
            </div>
            <p class="cf-section-sub">完整保留原片声画节奏与人物走位，把经典剧集或自拍视频一键重演成电影级猫咪主角</p>
          </div>

          <div class="cf-v2v-tabs" role="tablist" aria-label="选择经典对照片段">
            ${v2vItems.map((it, idx) => `
              <button
                type="button"
                role="tab"
                aria-selected="${idx === state.v2vIdx ? 'true' : 'false'}"
                class="cf-v2v-tab ${idx === state.v2vIdx ? 'is-active' : ''}"
                data-v2v-idx="${idx}"
              >
                <span>🐱</span>
                <span>${esc(it.title)}</span>
              </button>
            `).join('')}
          </div>
        </div>

        <div class="cf-v2v-stage">
          <div class="cf-v2v-player-wrap">
            <div class="cf-v2v-player-bar">
              <span class="cf-v2v-mode-indicator">
                <span class="cf-dot-live"></span>
                <span>${isSideBySide ? '左右原片同步对照版 · 一眼验真' : '纯猫成片版 · 电影质感输出'}</span>
              </span>
              <div class="cf-segmented" role="group" aria-label="切换对照模式">
                <button
                  type="button"
                  class="cf-seg-btn ${isSideBySide ? 'is-active' : ''}"
                  data-v2v-mode="side_by_side"
                >左右原片对照版</button>
                <button
                  type="button"
                  class="cf-seg-btn ${!isSideBySide ? 'is-active' : ''}"
                  data-v2v-mode="cat"
                >纯猫成片版</button>
              </div>
            </div>

            <div class="cf-v2v-viewport">
              ${isSideBySide ? `
                <div class="cf-v2v-split-labels">
                  <span class="cf-split-tag">左 · 经典原片</span>
                  <span class="cf-split-tag is-gold">右 · 影铸猫咪重演</span>
                </div>
              ` : `
                <div class="cf-v2v-split-labels">
                  <span class="cf-split-tag is-gold">纯净猫咪成片</span>
                </div>
              `}
              <video
                id="cf-v2v-video"
                src="${esc(activeSrc)}"
                ${!isSideBySide && active.poster_url ? `poster="${esc(active.poster_url)}"` : ''}
                controls
                muted
                loop
                playsinline
                preload="auto"
              ></video>
            </div>
          </div>

          <div class="cf-v2v-info">
            <div class="cf-v2v-info-top">
              <div>
                <h3 class="cf-v2v-title">${esc(active.title)}</h3>
                <p class="cf-v2v-desc">${esc(active.subtitle || '经典名场面实拍验证：完整保留原片声音、台词情绪与运镜，一键替换写实猫咪形象。')}</p>
              </div>

              <div class="cf-v2v-meta-row">
                ${active.duration_label ? `<span class="cf-mini-pill">⏱ ${esc(active.duration_label)}</span>` : ''}
                <span class="cf-mini-pill">⚙ ${esc(active.engine || 'LTX-2.5 V2V')}</span>
                <span class="cf-mini-pill is-emerald">💰 ${esc(active.cost_label || '约 ¥1.5 · 评测免费')}</span>
              </div>

              <div class="cf-feature-strip">
                <div class="cf-feature-pills" role="tablist" aria-label="核心技术亮点">
                  ${V2V_FEATURES.map((f) => `
                    <button
                      type="button"
                      role="tab"
                      aria-selected="${f.key === state.activeFeature ? 'true' : 'false'}"
                      class="cf-feature-pill ${f.key === state.activeFeature ? 'is-active' : ''}"
                      data-v2v-feat="${esc(f.key)}"
                    >${esc(f.label)}</button>
                  `).join('')}
                </div>
                <p class="cf-feature-detail" id="cf-v2v-feat-desc">${esc(activeFeat.detail)}</p>
              </div>
            </div>

            <div class="cf-v2v-cta-stack">
              <button type="button" class="cf-btn-gold" data-action="v2v-clone" data-route="${esc(cloneUrl)}">
                <span>🐱 上传我的视频做同款</span>
              </button>
              <button type="button" class="cf-btn-subtle" data-action="v2v-fullscreen">
                <span>放大全屏对照观看</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    `;

    const v2vVideoEl = v2vEl.querySelector('#cf-v2v-video');
    if (v2vVideoEl && isSideBySide) {
      v2vVideoEl.addEventListener('loadedmetadata', () => {
        if (v2vVideoEl.currentTime < 0.05 && Number.isFinite(v2vVideoEl.duration) && v2vVideoEl.duration > 1) {
          try { v2vVideoEl.currentTime = 0.5; } catch (_) {}
        }
      }, { once: true });
    }

    v2vEl.querySelectorAll('[data-v2v-idx]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const idx = Number(btn.dataset.v2vIdx);
        if (!Number.isNaN(idx) && idx !== state.v2vIdx) {
          state.v2vIdx = idx;
          renderV2VSpotlight();
        }
      });
    });

    v2vEl.querySelectorAll('[data-v2v-mode]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const nextMode = btn.dataset.v2vMode;
        if (nextMode === state.v2vViewMode) return;
        const vid = v2vEl.querySelector('#cf-v2v-video');
        const prevTime = vid ? vid.currentTime : 0;
        const wasPlaying = vid ? !vid.paused : false;
        state.v2vViewMode = nextMode;
        renderV2VSpotlight();
        const newVid = v2vEl.querySelector('#cf-v2v-video');
        if (newVid && prevTime > 0) {
          newVid.addEventListener('loadedmetadata', () => {
            try { newVid.currentTime = Math.min(prevTime, Math.max(0, (newVid.duration || prevTime) - 0.1)); } catch (_) {}
            if (wasPlaying) newVid.play?.().catch(() => {});
          }, { once: true });
        }
      });
    });

    v2vEl.querySelectorAll('[data-v2v-feat]').forEach((btn) => {
      btn.addEventListener('click', () => {
        state.activeFeature = btn.dataset.v2vFeat;
        v2vEl.querySelectorAll('[data-v2v-feat]').forEach((b) => {
          const on = b.dataset.v2vFeat === state.activeFeature;
          b.classList.toggle('is-active', on);
          b.setAttribute('aria-selected', on ? 'true' : 'false');
        });
        const featObj = V2V_FEATURES.find((f) => f.key === state.activeFeature);
        const descEl = v2vEl.querySelector('#cf-v2v-feat-desc');
        if (featObj && descEl) descEl.textContent = featObj.detail;
      });
    });

    v2vEl.querySelector('[data-action="v2v-clone"]')?.addEventListener('click', (e) => {
      ctx.navigate(e.currentTarget.dataset.route);
    });

    v2vEl.querySelector('[data-action="v2v-fullscreen"]')?.addEventListener('click', () => {
      openItemModal(ctx, active, state.v2vViewMode === 'side_by_side');
    });
  }

  /* ---------------- 3. Curated Showcase Gallery ---------------- */
  function renderGallery() {
    if (!galleryEl) return;
    const filtered = allItems.filter((it) => matchesFilter(it, state.filter));
    const displayItems = filtered.length ? filtered : allItems;

    galleryEl.innerHTML = `
      <div class="cf-section-head">
        <div class="cf-section-title-group">
          <div class="cf-section-title-row">
            <h2 class="cf-section-title">精选样片画廊</h2>
            <span class="badge badge-cyan">实拍已渲染 ${esc(totalShots)}+ 镜 · ${esc(totalFilms)} 部作品</span>
          </div>
          <p class="cf-section-sub">悬停卡片即可静音预览动态画面，点击「做同款」一键复刻同款工作流与画风</p>
        </div>

        <div class="cf-filter-bar" role="tablist" aria-label="按题材筛选作品">
          ${GALLERY_FILTERS.map((f) => `
            <button
              type="button"
              role="tab"
              aria-selected="${f.key === state.filter ? 'true' : 'false'}"
              class="cf-filter-pill ${f.key === state.filter ? 'is-active' : ''}"
              data-filter="${esc(f.key)}"
            >${esc(f.label)}</button>
          `).join('')}
        </div>
      </div>

      <div class="cf-gallery-grid">
        ${displayItems.map((it) => {
          const cloneRoute = buildCloneRoute(it);
          const hasProject = Boolean(it.project_id);
          const isV2V = it.mode === 'v2v' || Boolean(it.side_by_side_url);
          return `
            <article class="cf-video-card" data-item-id="${esc(it.id)}">
              <div class="cf-card-media" data-card-play="${esc(it.id)}">
                ${it.poster_url
                  ? `<img class="cf-card-poster" src="${esc(it.poster_url)}" alt="${esc(it.title)}" />`
                  : `<div class="cf-poster-fallback">影铸实拍样片</div>`}
                <div class="cf-card-scrim"></div>
                <div class="cf-card-top-badges">
                  <span class="cf-card-badge ${isV2V ? 'is-gold' : ''}">${esc(it.badge || (isV2V ? 'V2V 换角' : '原创成片'))}</span>
                  ${it.side_by_side_url ? `<span class="cf-card-badge">含原片对照</span>` : ''}
                </div>
                <div class="cf-card-play-ring">${iconPlay(18)}</div>
                <div class="cf-card-bottom-meta">
                  <span class="cf-card-engine">${esc(it.engine || 'H3 / LTX-2.5')}</span>
                  <span class="cf-card-duration">${esc(it.duration_label || '实拍样片')}</span>
                </div>
              </div>

              <div class="cf-card-body">
                <div class="cf-card-title-row">
                  <h3 class="cf-card-title" title="${esc(it.title)}">${esc(it.title)}</h3>
                  <span class="cf-card-cost">${esc(it.cost_label || '低价云拍')}</span>
                </div>
                <p class="cf-card-subtitle">${esc(it.subtitle || '点击播放高清样片，或进入分镜看板查看完整工作流。')}</p>
                <div class="cf-card-actions">
                  <button type="button" class="cf-card-btn" data-card-play="${esc(it.id)}">
                    ${iconPlay(11)}
                    <span>播放</span>
                  </button>
                  <button type="button" class="cf-card-btn is-primary is-grow" data-card-clone="${esc(cloneRoute)}">
                    <span>✨ 做同款</span>
                  </button>
                  ${hasProject ? `
                    <button type="button" class="cf-card-btn" data-card-wf="#workflow/${encodeURIComponent(it.project_id)}">
                      <span>分镜看板</span>
                    </button>
                  ` : ''}
                </div>
              </div>
            </article>
          `;
        }).join('')}
      </div>
    `;

    galleryEl.querySelectorAll('[data-filter]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const nextFilter = btn.dataset.filter;
        if (nextFilter !== state.filter) {
          state.filter = nextFilter;
          renderGallery();
        }
      });
    });

    const itemById = new Map(allItems.map((it) => [String(it.id), it]));

    galleryEl.querySelectorAll('[data-card-play]').forEach((el) => {
      el.addEventListener('click', () => {
        const found = itemById.get(String(el.dataset.cardPlay));
        if (found) openItemModal(ctx, found, false);
      });
    });

    galleryEl.querySelectorAll('[data-card-clone]').forEach((btn) => {
      btn.addEventListener('click', () => ctx.navigate(btn.dataset.cardClone));
    });

    galleryEl.querySelectorAll('[data-card-wf]').forEach((btn) => {
      btn.addEventListener('click', () => ctx.navigate(btn.dataset.cardWf));
    });

    // Lazy hover-to-play preview video (keeps initial load fast & memory lean)
    galleryEl.querySelectorAll('.cf-video-card').forEach((card) => {
      const item = itemById.get(String(card.dataset.itemId));
      const media = card.querySelector('.cf-card-media');
      if (!item?.video_url || !media) return;

      let hoverTimer = null;
      let previewVideo = null;

      const stopPreview = () => {
        if (hoverTimer) {
          clearTimeout(hoverTimer);
          hoverTimer = null;
        }
        if (previewVideo) {
          try {
            previewVideo.pause();
            previewVideo.removeAttribute('src');
            previewVideo.load();
          } catch (_) {}
          previewVideo.remove();
          previewVideo = null;
        }
      };

      card.addEventListener('mouseenter', () => {
        hoverTimer = setTimeout(() => {
          if (previewVideo || !document.body.contains(media)) return;
          const v = document.createElement('video');
          v.className = 'cf-card-hover-video';
          v.src = item.video_url;
          v.muted = true;
          v.loop = true;
          v.playsInline = true;
          v.autoplay = true;
          v.preload = 'metadata';
          media.appendChild(v);
          v.play?.().catch(() => {});
          previewVideo = v;
        }, 260);
      });

      card.addEventListener('mouseleave', stopPreview);
      _cleanupFns.push(stopPreview);
    });
  }

  renderMyWorks();
  renderHero();
  resetHeroAutoAdvance();
  renderV2VSpotlight();
  renderGallery();
}
