/**
 * CineForge Studio — 零门槛创作台 (Create Wizard View)
 * Designed for non-technical white-collar testers: zero jargon, instant presets,
 * live cost estimator, and 1-click transition into the visual Workflow Kanban.
 */

let _cleanupFns = [];

function clearRuntime() {
  while (_cleanupFns.length) {
    const fn = _cleanupFns.pop();
    try { fn(); } catch (_) {}
  }
}

export function destroy() {
  clearRuntime();
}

const DURATION_OPTIONS = [
  { sec: 15, label: '15秒 预告', sub: '约 3~4 镜 · 开场/朋友圈' },
  { sec: 30, label: '30秒 爆款短片', sub: '约 6 镜 · 短视频黄金时长' },
  { sec: 60, label: '60秒 完整小剧场', sub: '约 12 镜 · 起承转合完整' },
  { sec: 180, label: '180秒 微电影', sub: '约 36 镜 · 沉浸故事短片' }
];

const ASPECT_OPTIONS = [
  { value: '16:9', label: '16:9 横屏电影', sub: 'B站 / 电脑大屏 / 汇报' },
  { value: '9:16', label: '9:16 竖屏短视频', sub: '抖音 / 小红书 / 视频号' },
  { value: '4:3', label: '4:3 复古经典', sub: '老剧名场面 / 胶片氛围' }
];

const AUTO_PIPELINE_STEPS = [
  { num: '1', name: '创意拆镜', desc: '自动拆分场次脚本' },
  { num: '2', name: '锁定画风', desc: '固定角色视觉锚点' },
  { num: '3', name: '分镜看板', desc: '可视化逐镜精修' },
  { num: '4', name: '云端渲染', desc: '共享 GPU 低价拍片' },
  { num: '5', name: '智能抽检', desc: '一键过审或定向重拍' },
  { num: '6', name: '一键成片', desc: '预演预览与母版导出' }
];

function computeEstimate(durationSec, mode) {
  const sec = Number(durationSec) || 30;
  const isV2V = mode === 'v2v';
  const shots = isV2V
    ? Math.max(2, Math.round(sec / 6))
    : Math.max(3, Math.round(sec / 5));
  const cloudTotalSec = shots * (isV2V ? 38 : 42);
  const cloudMinText = cloudTotalSec < 120
    ? `约 ${cloudTotalSec} 秒`
    : `约 ${(cloudTotalSec / 60).toFixed(1)} 分钟`;

  const commercialCny = Math.max(18, Math.round(shots * (isV2V ? 9.5 : 7.8)));
  const cineforgeCny = Number((shots * (isV2V ? 0.34 : 0.28)).toFixed(1));
  const savingsPct = Math.min(97, Math.max(85, Math.round((1 - cineforgeCny / commercialCny) * 100)));

  return { shots, cloudMinText, commercialCny, cineforgeCny, savingsPct };
}

function normalizeStyle(s, idx) {
  return {
    id: s.id || s.style_id || `style_${idx}`,
    title: s.title || s.name || '电影质感',
    tag: s.tag || s.badge || s.engine || '推荐',
    description: s.description || s.subtitle || s.desc || '',
    preview_url: s.preview_url || s.poster_url || s.image_url || '',
    mode: s.mode || ''
  };
}

function normalizePreset(p, idx, defaultMode) {
  return {
    id: p.id || p.preset_id || p.template_id || `preset_${idx}`,
    title: p.title || p.name || '快捷灵感',
    idea: p.idea || p.prompt || p.description || p.subtitle || '',
    style_id: p.style_id || p.style || '',
    duration_sec: Number(p.duration_sec || p.duration || (defaultMode === 'v2v' ? 15 : 30)),
    aspect: p.aspect || (defaultMode === 'v2v' ? '4:3' : '16:9'),
    character_name: p.character_name || p.character || (defaultMode === 'v2v' ? '橘白三花演技猫' : '主角'),
    source_video_url: p.source_video_url || p.video_url || null,
    poster_url: p.poster_url || p.preview_url || '',
    mode: p.mode || defaultMode,
    badge: p.badge || p.tag || '',
    v2v_options: p.v2v_options || null
  };
}

export async function render(container, ctx) {
  clearRuntime();
  const esc = ctx.escHtml || ((s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])));

  container.innerHTML = `
    <div class="cr-page cf-loading">
      <div class="cf-skel-card" style="height: 120px;"></div>
      <div class="cf-skel-hero" style="height: 360px;"></div>
    </div>
  `;

  let tplData = {};
  let showcaseData = {};
  try {
    const fetchTpl = () => ctx.store?.getOrFetch
      ? ctx.store.getOrFetch('templates', () => ctx.api.templates(), { ttlMs: 30000 })
      : ctx.api.templates();
    const fetchSc = () => ctx.store?.getOrFetch
      ? ctx.store.getOrFetch('showcase', () => ctx.api.showcase(), { ttlMs: 30000 })
      : ctx.api.showcase();
    const [tpl, sc] = await Promise.all([
      fetchTpl(),
      fetchSc().catch(() => ({ items: [] }))
    ]);
    tplData = tpl || {};
    showcaseData = sc || {};
  } catch (err) {
    container.innerHTML = `
      <div class="cr-page">
        <div class="empty-state">
          <h3>创作台模板加载失败</h3>
          <p>${esc(err?.message || '请确认 CineForge Studio 后端服务已启动')}</p>
        </div>
      </div>
    `;
    return;
  }

  const styles = (Array.isArray(tplData.styles) ? tplData.styles : []).map(normalizeStyle);
  const storyPresets = (Array.isArray(tplData.story_presets) ? tplData.story_presets : []).map((p, i) => normalizePreset(p, i, 'original'));
  const v2vPresets = (Array.isArray(tplData.v2v_presets) ? tplData.v2v_presets : []).map((p, i) => normalizePreset(p, i, 'v2v'));
  const showcaseItems = Array.isArray(showcaseData.items) ? showcaseData.items : [];

  const query = ctx.query || {};
  const initialMode = query.mode === 'v2v' ? 'v2v' : 'original';

  const state = {
    mode: initialMode,
    activePresetId: '',
    clonedFromLabel: '',
    title: '',
    idea: '',
    style_id: styles[0]?.id || '',
    duration_sec: initialMode === 'v2v' ? 15 : 30,
    aspect: initialMode === 'v2v' ? '4:3' : '16:9',
    engine: initialMode === 'v2v' ? 'v2v' : 'h3',
    character_name: initialMode === 'v2v' ? '写实狸花猫主角' : '主角小星',
    ref_image_urls: [],
    source_video_url: null,
    source_video_label: '',
    v2v_options: {
      desub: true,
      paw_guard: true,
      keep_audio: true
    },
    creator_name: '内测体验官',
    uploadingRef: false,
    uploadingVideo: false,
    submitting: false
  };

  function findStyleId(preferred) {
    if (!styles.length) return preferred || '';
    if (preferred) {
      const exact = styles.find((s) => s.id === preferred || s.title === preferred);
      if (exact) return exact.id;
      const fuzzy = styles.find((s) => `${s.id} ${s.title} ${s.tag}`.toLowerCase().includes(String(preferred).toLowerCase()));
      if (fuzzy) return fuzzy.id;
    }
    if (state.mode === 'v2v') {
      const v2vStyle = styles.find((s) => `${s.id} ${s.title} ${s.tag} ${s.mode}`.toLowerCase().includes('v2v') || s.title.includes('猫'));
      if (v2vStyle) return v2vStyle.id;
    }
    return styles[0].id;
  }

  function applyPreset(preset, labelPrefix = '') {
    if (!preset) return;
    state.mode = preset.mode === 'v2v' ? 'v2v' : 'original';
    state.activePresetId = preset.id;
    state.title = preset.title;
    state.idea = preset.idea;
    state.style_id = findStyleId(preset.style_id);
    const isGuestServer = document.body.classList.contains('is-server-guest');
    let nextDur = DURATION_OPTIONS.some((d) => d.sec === preset.duration_sec)
      ? preset.duration_sec
      : (preset.duration_sec <= 20 ? 15 : preset.duration_sec <= 45 ? 30 : preset.duration_sec <= 90 ? 60 : 180);
    if (isGuestServer && nextDur > 30) nextDur = 30;
    state.duration_sec = nextDur;
    state.aspect = ASPECT_OPTIONS.some((a) => a.value === preset.aspect) ? preset.aspect : state.aspect;
    if (preset.character_name) state.character_name = preset.character_name;
    if (preset.source_video_url) {
      state.source_video_url = preset.source_video_url;
      state.source_video_label = preset.title;
    }
    if (preset.v2v_options && typeof preset.v2v_options === 'object') {
      state.v2v_options = { ...state.v2v_options, ...preset.v2v_options };
    }
    if (labelPrefix) state.clonedFromLabel = `${labelPrefix}《${preset.title}》`;
  }

  // Handle deep links: #create?clone=... or #create?preset=... or #create?mode=v2v
  const deepKey = query.clone || query.preset || '';
  if (deepKey) {
    const keyLower = String(deepKey).toLowerCase();
    const matchedV2V = v2vPresets.find((p) => p.id.toLowerCase() === keyLower || p.title.toLowerCase().includes(keyLower));
    const matchedStory = storyPresets.find((p) => p.id.toLowerCase() === keyLower || p.title.toLowerCase().includes(keyLower));
    const matchedShowcase = showcaseItems.find((it) =>
      String(it.id || '').toLowerCase() === keyLower ||
      String(it.template_id || '').toLowerCase() === keyLower ||
      String(it.project_id || '').toLowerCase() === keyLower
    );

    if (matchedV2V) {
      applyPreset(matchedV2V, '已套用同款 V2V 模板：');
    } else if (matchedStory) {
      applyPreset(matchedStory, '已套用同款灵感模板：');
    } else if (matchedShowcase) {
      const isV2V = query.mode === 'v2v' || matchedShowcase.mode === 'v2v' || Boolean(matchedShowcase.side_by_side_url);
      state.mode = isV2V ? 'v2v' : 'original';
      state.title = `${matchedShowcase.title} · 我的同款版`;
      state.idea = matchedShowcase.subtitle || `参考《${matchedShowcase.title}》的镜头语言与氛围，拍一条属于我的精彩短片。`;
      state.style_id = findStyleId(matchedShowcase.template_id || matchedShowcase.category || (isV2V ? 'v2v' : ''));
      state.duration_sec = isV2V ? 15 : 30;
      state.aspect = isV2V ? '4:3' : '16:9';
      state.character_name = isV2V ? '主角橘白猫' : '主角小星';
      if (isV2V && matchedShowcase.video_url) {
        state.source_video_url = matchedShowcase.video_url;
        state.source_video_label = matchedShowcase.title;
      }
      state.clonedFromLabel = `已复制样片同款参数：《${matchedShowcase.title}》`;
    } else if (state.mode === 'v2v' && v2vPresets[0]) {
      applyPreset(v2vPresets[0]);
    }
  } else if (state.mode === 'v2v' && v2vPresets[0]) {
    state.style_id = findStyleId('v2v');
    state.source_video_url = v2vPresets[0].source_video_url;
    state.source_video_label = v2vPresets[0].title;
  } else if (storyPresets[0]) {
    state.style_id = findStyleId(query.style || storyPresets[0].style_id);
  }
  if (query.style) {
    state.style_id = findStyleId(query.style);
  }

  function getActiveStyle() {
    return styles.find((s) => s.id === state.style_id) || styles[0] || { id: 'default', title: '电影质感', preview_url: '' };
  }

  function getV2VSourceClips() {
    const clips = [];
    const seen = new Set();
    for (const p of v2vPresets) {
      if (p.source_video_url && !seen.has(p.source_video_url)) {
        seen.add(p.source_video_url);
        clips.push({ id: p.id, title: p.title, url: p.source_video_url, poster_url: p.poster_url });
      }
    }
    for (const it of showcaseItems) {
      if (it.side_by_side_url && it.video_url && !seen.has(it.video_url) && clips.length < 3) {
        seen.add(it.video_url);
        clips.push({ id: it.id, title: it.title, url: it.video_url, poster_url: it.poster_url });
      }
    }
    return clips.slice(0, 3);
  }

  function updateSummaryCard() {
    const est = computeEstimate(state.duration_sec, state.mode);
    const activeStyle = getActiveStyle();
    const summaryRoot = container.querySelector('#cr-summary-panel');
    if (!summaryRoot) return;

    const previewImg = state.ref_image_urls[0] || activeStyle.preview_url || '';
    const displayTitle = state.title.trim() || (state.mode === 'v2v' ? '我的猫咪换角重演短片' : '我的 AI 电影短片');

    const isGuestView = document.body.classList.contains('is-server-guest') || document.body.classList.contains('is-guest-preview');
    const ctaText = state.submitting
      ? (isGuestView ? '⏳ 正在提交并排入共享影棚...' : '⏳ 正在生成分镜与工作流看板...')
      : (isGuestView ? '🚀 免费生成我的视频' : '🚀 立即生成可视化工作流');
    const ctaNote = isGuestView
      ? '点击后自动排入共享影棚显卡生成成片，并同步为你先做一版即时预演'
      : '点击后立即生成可编辑的导演看板，所有分镜词与画面均可随时微调';

    summaryRoot.innerHTML = `
      <div class="cr-preview-card">
        ${previewImg
          ? `<img src="${esc(previewImg)}" alt="${esc(activeStyle.title)}" />`
          : `<div class="cf-poster-fallback">画风实时预览</div>`}
        <div class="cr-preview-scrim">
          <div class="cr-preview-badges">
            <span class="cf-card-badge is-gold">${state.mode === 'v2v' ? '🐱 V2V 换角模式' : '✨ 原创拍片模式'}</span>
            <span class="cf-card-badge">${esc(state.duration_sec)}s · ${esc(state.aspect)}</span>
          </div>
          <div>
            <div class="cr-preview-title">${esc(displayTitle)}</div>
            <div class="cr-preview-sub">画风：${esc(activeStyle.title)} · 主角：${esc(state.character_name.trim() || '待定')}</div>
          </div>
        </div>
      </div>

      <div class="cr-pipeline-box">
        <div class="cr-pipeline-head">
          <span>生成后自动启动 6 步工作流</span>
          <span style="color: var(--accent-gold, #f5b041);">全可视化可控</span>
        </div>
        <div class="cr-pipeline-grid">
          ${AUTO_PIPELINE_STEPS.map((st) => `
            <div class="cr-pipe-step">
              <span class="cr-pipe-dot">${esc(st.num)}</span>
              <span>${esc(st.name)}</span>
            </div>
          `).join('')}
        </div>
      </div>

      <div class="cr-cost-box" id="cr-cost-estimator">
        <div class="cr-est-metrics">
          <div class="cr-est-cell">
            <span class="cr-est-k">预计分镜数</span>
            <span class="cr-est-v" data-est-shots>${esc(est.shots)} 镜</span>
          </div>
          <div class="cr-est-cell">
            <span class="cr-est-k">云端单卡预计耗时</span>
            <span class="cr-est-v" data-est-time>${esc(est.cloudMinText)}</span>
          </div>
        </div>

        <div class="cr-price-compare">
          <div class="cr-price-old">
            <span>商业 AI 视频平台同规格估算</span>
            <span class="cr-price-strike">约 ¥${esc(est.commercialCny)}</span>
          </div>
          <div class="cr-price-new">
            <span class="cr-price-label">影铸共享算力池</span>
            <div class="cr-price-hero">
              <span class="cr-price-val" data-est-cost>约 ¥${esc(est.cineforgeCny)}</span>
              <span class="cr-free-tag">内测免费</span>
            </div>
          </div>
          <div style="font-size: 11.5px; color: #7ee8be; display: flex; justify-content: space-between;">
            <span>相比主流商用平台直省 ${esc(est.savingsPct)}%</span>
            <span>支持先免费本地预演</span>
          </div>
        </div>
      </div>

      <button type="button" class="cr-submit-btn" id="cr-submit-btn" ${state.submitting ? 'disabled' : ''}>
        <span>${ctaText}</span>
      </button>
      <p class="cr-submit-note">${ctaNote}</p>
    `;

    summaryRoot.querySelector('#cr-submit-btn')?.addEventListener('click', handleSubmit);
  }

  async function handleSubmit() {
    if (state.submitting) return;

    const presets = state.mode === 'v2v' ? v2vPresets : storyPresets;
    let finalTitle = state.title.trim();
    let finalIdea = state.idea.trim();

    if (!finalTitle && !finalIdea && presets[0]) {
      applyPreset(presets[0]);
      finalTitle = state.title.trim();
      finalIdea = state.idea.trim();
      renderAll();
      ctx.toast?.('已为你自动填入热门灵感模板，正在搭建工作流...', 'info');
    } else {
      if (!finalTitle) {
        finalTitle = finalIdea.slice(0, 14) || (state.mode === 'v2v' ? '我的猫咪名场面重演' : '我的 AI 原创短片');
        state.title = finalTitle;
      }
      if (!finalIdea) {
        finalIdea = state.mode === 'v2v'
          ? `保留原视频台词与动作，将主角替换为${state.character_name || '写实猫咪'}，输出电影级画质短片。`
          : `围绕《${finalTitle}》，以${getActiveStyle().title}画风创作一段精彩反转短剧。`;
        state.idea = finalIdea;
      }
    }

    state.submitting = true;
    updateSummaryCard();

    const isGuestServer = document.body.classList.contains('is-server-guest');
    const payload = {
      title: finalTitle,
      idea: finalIdea,
      mode: state.mode,
      engine: state.mode === 'v2v' ? 'v2v' : (state.engine || 'h3'),
      style_id: state.style_id || styles[0]?.id || 'pixar_3d',
      duration_sec: isGuestServer ? Math.min(30, Number(state.duration_sec) || 30) : (Number(state.duration_sec) || 30),
      aspect: state.aspect || '16:9',
      character_name: state.character_name.trim() || (state.mode === 'v2v' ? '写实猫咪主角' : '主角小星'),
      ref_image_urls: state.ref_image_urls.slice(),
      source_video_url: state.mode === 'v2v' ? (state.source_video_url || null) : null,
      v2v_options: { ...state.v2v_options },
      creator_name: state.creator_name.trim() || '内测体验官',
      auto_dispatch: isGuestServer,
    };

    try {
      const res = await ctx.api.createProject(payload);
      const created = res?.project || res;
      const createdId = created?.id;
      if (!createdId) {
        throw new Error('后端未返回项目编号');
      }
      if (res?.cloud_dispatch?.quota_exceeded) {
        ctx.toast?.(res.cloud_dispatch.error || '本地分镜与预演已生成（云端免费额度已用完）', 'warning');
      } else if (isGuestServer && res?.cloud_job) {
        ctx.toast?.(`🚀 《${created.title || finalTitle}》已自动排入共享影棚队列，正在为你生成视频！`, 'success');
      } else {
        ctx.toast?.(`✨ 《${created.title || finalTitle}》工作流已就绪，正在进入导演看板！`, 'success');
      }
      ctx.navigate(`#workflow/${encodeURIComponent(createdId)}`);
    } catch (err) {
      state.submitting = false;
      updateSummaryCard();
      ctx.toast?.(`创建失败：${err?.message || '请稍后重试'}`, 'error');
    }
  }

  async function handleUploadImage(file) {
    if (!file) return;
    if (!file.type.startsWith('image/')) {
      ctx.toast?.('请选择 JPG / PNG / WebP 格式的角色参考图', 'warning');
      return;
    }
    state.uploadingRef = true;
    renderAll();
    try {
      const res = await ctx.api.uploadFile(file);
      if (res?.url) {
        state.ref_image_urls.push(res.url);
        ctx.toast?.('参考图上传成功，已绑定到角色定妆锚点', 'success');
      } else {
        throw new Error('上传未返回图片地址');
      }
    } catch (err) {
      ctx.toast?.(`图片上传失败：${err?.message || '请重试'}`, 'error');
    } finally {
      state.uploadingRef = false;
      renderAll();
    }
  }

  async function handleUploadVideo(file) {
    if (!file) return;
    if (!file.type.startsWith('video/') && !/\.(mp4|mov|webm|mkv)$/i.test(file.name)) {
      ctx.toast?.('请选择 MP4 / MOV / WebM 格式的短视频（建议 5~30 秒）', 'warning');
      return;
    }
    state.uploadingVideo = true;
    renderAll();
    try {
      const res = await ctx.api.uploadFile(file);
      if (res?.url) {
        state.source_video_url = res.url;
        state.source_video_label = file.name;
        ctx.toast?.(`原片《${file.name}》上传成功`, 'success');
      } else {
        throw new Error('上传未返回视频地址');
      }
    } catch (err) {
      ctx.toast?.(`视频上传失败：${err?.message || '请重试'}`, 'error');
    } finally {
      state.uploadingVideo = false;
      renderAll();
    }
  }

  function renderAll() {
    const activePresets = state.mode === 'v2v' ? v2vPresets : storyPresets;
    const sourceClips = state.mode === 'v2v' ? getV2VSourceClips() : [];

    container.innerHTML = `
      <div class="cr-page">
        <header class="cr-header">
          <div>
            <h1 class="cr-title">零门槛 AI 拍片创作台</h1>
            <p class="cr-subtitle">无需任何专业影视术语，4 步选好想法与画风，系统自动搭建可逐镜掌控的电影工作流看板</p>
          </div>
          <span class="badge badge-emerald">白领内测期间 · 预演与体验免费</span>
        </header>

        ${state.clonedFromLabel ? `
          <div class="cr-clone-banner">
            <span>✨ ${esc(state.clonedFromLabel)} — 你可以直接点击右侧生成，或按自己喜好微调下方内容</span>
            <button type="button" class="cr-clone-clear" id="cr-clear-clone">知道了</button>
          </div>
        ` : ''}

        <!-- Top Dual Creation Mode Selector -->
        <section class="cr-mode-grid" aria-label="选择创作模式">
          <button
            type="button"
            class="cr-mode-card ${state.mode === 'original' ? 'is-active' : ''}"
            data-mode="original"
          >
            <div class="cr-mode-icon">✨</div>
            <div class="cr-mode-body">
              <div class="cr-mode-head">
                <span class="cr-mode-title">一句话拍短剧 / 微电影</span>
                <span class="cr-mode-check">✓ 当前模式</span>
              </div>
              <p class="cr-mode-desc">输入一句话想法，自动拆剧本、定角色、排分镜、云端低价拍片</p>
              <div class="cr-mode-tags">
                <span class="cr-mode-tag">自动拆分场次</span>
                <span class="cr-mode-tag">角色外观锁定</span>
                <span class="cr-mode-tag">支持 15秒~3分钟</span>
              </div>
            </div>
          </button>

          <button
            type="button"
            class="cr-mode-card ${state.mode === 'v2v' ? 'is-active' : ''}"
            data-mode="v2v"
          >
            <div class="cr-mode-icon">🐱</div>
            <div class="cr-mode-body">
              <div class="cr-mode-head">
                <span class="cr-mode-title">视频一键换角重演 (V2V)</span>
                <span class="cr-mode-check">✓ 当前模式</span>
              </div>
              <p class="cr-mode-desc">上传 5~30 秒视频或选经典片段，保留原声与动作，把主角换成猫咪或 3D 动画</p>
              <div class="cr-mode-tags">
                <span class="cr-mode-tag">原声口型同步</span>
                <span class="cr-mode-tag">自动去硬字幕</span>
                <span class="cr-mode-tag">护爪防穿帮</span>
              </div>
            </div>
          </button>
        </section>

        <!-- Main Guided 2-Column Workspace -->
        <div class="cr-workspace">
          <div class="cr-steps">
            <!-- Step 01: Inspiration / Idea / V2V Source -->
            <section class="cr-step-card">
              <div class="cr-step-head">
                <span class="cr-step-num">01</span>
                <div class="cr-step-titles">
                  <h2 class="cr-step-title">先挑一个「3秒开拍灵感」或写下你的想法</h2>
                  <p class="cr-step-hint">${state.mode === 'v2v' ? '点选热门名场面模板一键体验，或拖入你自己的 5~30 秒视频片段' : '点一下任意灵感卡片自动填好全部参数，直接开拍或自由改写'}</p>
                </div>
              </div>

              ${activePresets.length ? `
                <div>
                  <div class="cr-preset-label">⚡ 3秒开拍灵感（点一下自动填充）</div>
                  <div class="cr-preset-chips">
                    ${activePresets.map((p) => `
                      <button
                        type="button"
                        class="cr-preset-chip ${state.activePresetId === p.id ? 'is-active' : ''}"
                        data-preset-id="${esc(p.id)}"
                      >
                        <span>${state.mode === 'v2v' ? '🎬' : '💡'}</span>
                        <span>${esc(p.title)}</span>
                      </button>
                    `).join('')}
                  </div>
                </div>
              ` : ''}

              ${state.mode === 'v2v' ? `
                <div class="cr-field">
                  <div class="cr-label-row">
                    <span class="cr-label">选择经典原片素材，或上传你的短视频</span>
                    ${state.source_video_label ? `<span class="cr-source-badge">✓ 已选素材：${esc(state.source_video_label)}</span>` : ''}
                  </div>

                  ${sourceClips.length ? `
                    <div class="cr-source-clips">
                      ${sourceClips.map((clip) => `
                        <button
                          type="button"
                          class="cr-clip-card ${state.source_video_url === clip.url ? 'is-active' : ''}"
                          data-source-clip="${esc(clip.url)}"
                          data-source-label="${esc(clip.title)}"
                        >
                          <div class="cr-clip-thumb">
                            ${clip.poster_url
                              ? `<img src="${esc(clip.poster_url)}" alt="${esc(clip.title)}" />`
                              : `<div class="cf-poster-fallback">经典原片</div>`}
                          </div>
                          <div class="cr-clip-info">${esc(clip.title)}</div>
                        </button>
                      `).join('')}
                    </div>
                  ` : ''}

                  <label class="cr-dropzone" id="cr-video-dropzone">
                    <input type="file" accept="video/mp4,video/quicktime,video/webm" id="cr-video-input" style="display:none;" />
                    <div class="cr-dropzone-left">
                      <div class="cr-dropzone-icon">🎞️</div>
                      <div class="cr-dropzone-text">
                        <span class="cr-dropzone-title">${state.uploadingVideo ? '正在上传视频并抽取封面...' : '拖拽上传你自己的视频（5~30秒 MP4 / MOV）'}</span>
                        <span class="cr-dropzone-sub">仅用于本机与云端重演处理，保留原视频人声与动作</span>
                      </div>
                    </div>
                    <span class="cr-upload-btn-tag">${state.uploadingVideo ? '上传中...' : '选择视频文件'}</span>
                  </label>
                </div>
              ` : ''}

              <div class="cr-field">
                <div class="cr-label-row">
                  <label class="cr-label" for="cr-title-input">给你的影片起个名字</label>
                  <span class="cr-label-sub">会显示在看板与成片标题中</span>
                </div>
                <input
                  id="cr-title-input"
                  class="cr-input"
                  type="text"
                  maxlength="60"
                  placeholder="${state.mode === 'v2v' ? '例如：三国猫演义 · 俺也一样' : '例如：周五傍晚的治愈小猫 / 30秒项目汇报大片'}"
                  value="${esc(state.title)}"
                />
              </div>

              <div class="cr-field">
                <div class="cr-label-row">
                  <label class="cr-label" for="cr-idea-input">${state.mode === 'v2v' ? '想把主角换成什么样子？有什么特别要求？' : '用大白话写下你想拍的画面或故事'}</label>
                  <span class="cr-label-sub" id="cr-idea-count">${state.idea.length} 字</span>
                </div>
                <textarea
                  id="cr-idea-input"
                  class="cr-textarea"
                  placeholder="${state.mode === 'v2v'
                    ? '例如：把画面里的古装将军换成威风凛凛的橘白大猫，保留原声音效、服装细节和经典表情，画面偏电影柔光质感。'
                    : '例如：周五晚上加班后的写字楼，一只戴着工牌的三花猫突然接管会议室，用三页 PPT 帮打工人准点下班，画风温暖治愈又有电影质感。'}"
                >${esc(state.idea)}</textarea>
              </div>
            </section>

            <!-- Step 02: Cinema Style Visual Grid -->
            <section class="cr-step-card">
              <div class="cr-step-head">
                <span class="cr-step-num">02</span>
                <div class="cr-step-titles">
                  <h2 class="cr-step-title">挑选电影画风</h2>
                  <p class="cr-step-hint">每一张预览图均来自影铸真实参考定妆图，选定后全片保持统一影调与质感</p>
                </div>
              </div>

              <div class="cr-style-grid" role="radiogroup" aria-label="电影画风选择">
                ${styles.map((st) => `
                  <button
                    type="button"
                    role="radio"
                    aria-checked="${st.id === state.style_id ? 'true' : 'false'}"
                    class="cr-style-card ${st.id === state.style_id ? 'is-active' : ''}"
                    data-style-id="${esc(st.id)}"
                  >
                    <div class="cr-style-img-wrap">
                      ${st.preview_url
                        ? `<img src="${esc(st.preview_url)}" alt="${esc(st.title)}" />`
                        : `<div class="cf-poster-fallback">${esc(st.title)}</div>`}
                      <span class="cr-style-selected-badge">✓ 已选</span>
                    </div>
                    <div class="cr-style-meta">
                      <div class="cr-style-name-row">
                        <span class="cr-style-name">${esc(st.title)}</span>
                        <span class="cr-style-tag">${esc(st.tag)}</span>
                      </div>
                      ${st.description ? `<span class="cr-style-desc">${esc(st.description)}</span>` : ''}
                    </div>
                  </button>
                `).join('')}
              </div>
            </section>

            <!-- Step 03: Character Identity & Smart V2V Guards -->
            <section class="cr-step-card">
              <div class="cr-step-head">
                <span class="cr-step-num">03</span>
                <div class="cr-step-titles">
                  <h2 class="cr-step-title">${state.mode === 'v2v' ? '设定替换主角形象 & 防穿帮开关' : '设定主角形象（可选上传参考照片）'}</h2>
                  <p class="cr-step-hint">上传自家宠物或角色照片后，影铸会自动写入「视觉一致性锁」，让主角从头到尾不换脸</p>
                </div>
              </div>

              <div class="cr-field">
                <div class="cr-label-row">
                  <label class="cr-label" for="cr-char-input">主角称呼 / 外观特点</label>
                  <span class="cr-label-sub">例如：戴工牌的橘白猫「年糕」 / 机甲少女林星</span>
                </div>
                <input
                  id="cr-char-input"
                  class="cr-input"
                  type="text"
                  maxlength="50"
                  placeholder="输入主角名字或外观特征"
                  value="${esc(state.character_name)}"
                />
              </div>

              <div class="cr-field">
                <span class="cr-label">主角定妆参考图（可选 · 支持拖拽上传）</span>
                <label class="cr-dropzone" id="cr-img-dropzone">
                  <input type="file" accept="image/png,image/jpeg,image/webp" id="cr-img-input" style="display:none;" />
                  <div class="cr-dropzone-left">
                    <div class="cr-dropzone-icon">🖼️</div>
                    <div class="cr-dropzone-text">
                      <span class="cr-dropzone-title">${state.uploadingRef ? '正在上传参考图...' : '点击或拖入主角照片 / 宠物照片（JPG / PNG / WebP）'}</span>
                      <span class="cr-dropzone-sub">不传也没关系，系统会自动使用所选画风的内置参考定妆图</span>
                    </div>
                  </div>
                  <span class="cr-upload-btn-tag">${state.uploadingRef ? '上传中...' : '上传参考图'}</span>
                </label>

                ${state.ref_image_urls.length ? `
                  <div class="cr-uploaded-preview">
                    ${state.ref_image_urls.map((url, idx) => `
                      <div class="cr-ref-thumb">
                        <img src="${esc(url)}" alt="已上传参考图 ${idx + 1}" />
                        <button type="button" class="cr-ref-remove" data-remove-ref="${idx}" title="移除">×</button>
                      </div>
                    `).join('')}
                  </div>
                ` : ''}
              </div>

              ${state.mode === 'v2v' ? `
                <div class="cr-field">
                  <span class="cr-label">V2V 智能防穿帮护航（推荐全开）</span>
                  <div class="cr-toggle-list">
                    <button type="button" class="cr-toggle-item ${state.v2v_options.desub ? 'is-on' : ''}" data-v2v-opt="desub">
                      <div class="cr-toggle-top">
                        <span class="cr-toggle-title">自动抹除原片字幕</span>
                        <span class="cr-switch"></span>
                      </div>
                      <span class="cr-toggle-desc">自动识别并无痕消除原视频底部的硬字幕条</span>
                    </button>

                    <button type="button" class="cr-toggle-item ${state.v2v_options.paw_guard ? 'is-on' : ''}" data-v2v-opt="paw_guard">
                      <div class="cr-toggle-top">
                        <span class="cr-toggle-title">护爪防穿帮增强</span>
                        <span class="cr-switch"></span>
                      </div>
                      <span class="cr-toggle-desc">加固手部/猫爪与古装衣袖边界，减少变形穿帮</span>
                    </button>

                    <button type="button" class="cr-toggle-item ${state.v2v_options.keep_audio ? 'is-on' : ''}" data-v2v-opt="keep_audio">
                      <div class="cr-toggle-top">
                        <span class="cr-toggle-title">保留原声对口型</span>
                        <span class="cr-switch"></span>
                      </div>
                      <span class="cr-toggle-desc">100% 保留原片台词与音效，自动对齐嘴部开合</span>
                    </button>
                  </div>
                </div>
              ` : ''}
            </section>

            <!-- Step 04: Duration & Aspect Ratio -->
            <section class="cr-step-card">
              <div class="cr-step-head">
                <span class="cr-step-num">04</span>
                <div class="cr-step-titles">
                  <h2 class="cr-step-title">选择成片时长与画面比例</h2>
                  <p class="cr-step-hint">右侧会实时为你计算分镜数、云端渲染耗时和成本对比</p>
                </div>
              </div>

              <div class="cr-field">
                <span class="cr-label">目标成片时长</span>
                <div class="cr-duration-grid" role="radiogroup" aria-label="选择成片时长">
                  ${DURATION_OPTIONS.map((opt) => `
                    <button
                      type="button"
                      role="radio"
                      aria-checked="${opt.sec === state.duration_sec ? 'true' : 'false'}"
                      class="cr-option-pill ${opt.sec > 30 ? 'host-only' : ''} ${opt.sec === state.duration_sec ? 'is-active' : ''}"
                      data-duration="${opt.sec}"
                    >
                      <span class="cr-option-main">${esc(opt.label)}</span>
                      <span class="cr-option-sub">${esc(opt.sub)}</span>
                    </button>
                  `).join('')}
                </div>
              </div>

              <div class="cr-field">
                <span class="cr-label">画面比例</span>
                <div class="cr-aspect-row" role="radiogroup" aria-label="选择画面比例">
                  ${ASPECT_OPTIONS.map((opt) => `
                    <button
                      type="button"
                      role="radio"
                      aria-checked="${opt.value === state.aspect ? 'true' : 'false'}"
                      class="cr-option-pill ${opt.value === state.aspect ? 'is-active' : ''}"
                      data-aspect="${esc(opt.value)}"
                    >
                      <span class="cr-option-main">${esc(opt.label)}</span>
                      <span class="cr-option-sub">${esc(opt.sub)}</span>
                    </button>
                  `).join('')}
                </div>
              </div>

              ${state.mode !== 'v2v' ? `
                <div class="cr-field">
                  <span class="cr-label">云端视频模型（全部在 Colab GPU 运行）</span>
                  <div class="cr-aspect-row" role="radiogroup" aria-label="选择云端模型">
                    <button
                      type="button"
                      role="radio"
                      aria-checked="${state.engine !== 'ltx' ? 'true' : 'false'}"
                      class="cr-option-pill ${state.engine !== 'ltx' ? 'is-active' : ''}"
                      data-engine="h3"
                    >
                      <span class="cr-option-main">MiniMax-H3（开源4步）</span>
                      <span class="cr-option-sub">多参考图角色锁定最强 · 同步立体声</span>
                    </button>
                    <button
                      type="button"
                      role="radio"
                      aria-checked="${state.engine === 'ltx' ? 'true' : 'false'}"
                      class="cr-option-pill ${state.engine === 'ltx' ? 'is-active' : ''}"
                      data-engine="ltx"
                    >
                      <span class="cr-option-main">LTX-2.5（开源图生/首帧）</span>
                      <span class="cr-option-sub">人物特写与中文口型自然 · 单首帧驱动</span>
                    </button>
                  </div>
                </div>
              ` : ''}

              <div class="cr-field">
                <div class="cr-label-row">
                  <label class="cr-label" for="cr-creator-input">导演 / 体验官署名（选填）</label>
                  <span class="cr-label-sub">用于在团队看板中标识是谁创建的影片</span>
                </div>
                <input
                  id="cr-creator-input"
                  class="cr-input"
                  type="text"
                  maxlength="30"
                  placeholder="例如：产品部小王 / 内测体验官"
                  value="${esc(state.creator_name)}"
                />
              </div>
            </section>
          </div>

          <!-- Right Sticky Workflow & Ultra-Low Cost Preview Card -->
          <aside class="cr-summary-sticky" id="cr-summary-panel" aria-label="工作流与成本实时预览"></aside>
        </div>
      </div>
    `;

    bindEvents();
    updateSummaryCard();
  }

  function bindEvents() {
    container.querySelector('#cr-clear-clone')?.addEventListener('click', () => {
      state.clonedFromLabel = '';
      renderAll();
    });

    // Mode switcher
    container.querySelectorAll('[data-mode]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const nextMode = btn.dataset.mode;
        if (nextMode === state.mode) return;
        state.mode = nextMode;
        state.activePresetId = '';
        state.style_id = findStyleId(nextMode === 'v2v' ? 'v2v' : '');
        if (nextMode === 'v2v') {
          if (state.duration_sec > 60) state.duration_sec = 15;
          if (!state.source_video_url && v2vPresets[0]?.source_video_url) {
            state.source_video_url = v2vPresets[0].source_video_url;
            state.source_video_label = v2vPresets[0].title;
          }
        }
        renderAll();
      });
    });

    // Preset chips
    const activePresets = state.mode === 'v2v' ? v2vPresets : storyPresets;
    const presetMap = new Map(activePresets.map((p) => [p.id, p]));
    container.querySelectorAll('[data-preset-id]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const preset = presetMap.get(btn.dataset.presetId);
        if (preset) {
          applyPreset(preset);
          renderAll();
          ctx.toast?.(`已填入灵感「${preset.title}」`, 'info');
        }
      });
    });

    // V2V source clip cards
    container.querySelectorAll('[data-source-clip]').forEach((btn) => {
      btn.addEventListener('click', () => {
        state.source_video_url = btn.dataset.sourceClip;
        state.source_video_label = btn.dataset.sourceLabel || '已选经典原片';
        renderAll();
      });
    });

    // Inputs (update live preview without full DOM re-render)
    container.querySelector('#cr-title-input')?.addEventListener('input', (e) => {
      state.title = e.target.value;
      updateSummaryCard();
    });

    container.querySelector('#cr-idea-input')?.addEventListener('input', (e) => {
      state.idea = e.target.value;
      const cnt = container.querySelector('#cr-idea-count');
      if (cnt) cnt.textContent = `${state.idea.length} 字`;
    });

    container.querySelector('#cr-char-input')?.addEventListener('input', (e) => {
      state.character_name = e.target.value;
      updateSummaryCard();
    });

    container.querySelector('#cr-creator-input')?.addEventListener('input', (e) => {
      state.creator_name = e.target.value;
    });

    // Style cards
    container.querySelectorAll('[data-style-id]').forEach((btn) => {
      btn.addEventListener('click', () => {
        state.style_id = btn.dataset.styleId;
        container.querySelectorAll('[data-style-id]').forEach((card) => {
          const active = card.dataset.styleId === state.style_id;
          card.classList.toggle('is-active', active);
          card.setAttribute('aria-checked', active ? 'true' : 'false');
        });
        updateSummaryCard();
      });
    });

    // Duration pills
    container.querySelectorAll('[data-duration]').forEach((btn) => {
      btn.addEventListener('click', () => {
        state.duration_sec = Number(btn.dataset.duration) || 30;
        container.querySelectorAll('[data-duration]').forEach((pill) => {
          const active = Number(pill.dataset.duration) === state.duration_sec;
          pill.classList.toggle('is-active', active);
          pill.setAttribute('aria-checked', active ? 'true' : 'false');
        });
        updateSummaryCard();
      });
    });

    // Aspect ratio pills
    container.querySelectorAll('[data-aspect]').forEach((btn) => {
      btn.addEventListener('click', () => {
        state.aspect = btn.dataset.aspect;
        container.querySelectorAll('[data-aspect]').forEach((pill) => {
          const active = pill.dataset.aspect === state.aspect;
          pill.classList.toggle('is-active', active);
          pill.setAttribute('aria-checked', active ? 'true' : 'false');
        });
        updateSummaryCard();
      });
    });

    // Cloud engine pills (H3 vs LTX-2.5)
    container.querySelectorAll('[data-engine]').forEach((btn) => {
      btn.addEventListener('click', () => {
        state.engine = btn.dataset.engine;
        container.querySelectorAll('[data-engine]').forEach((pill) => {
          const active = pill.dataset.engine === state.engine;
          pill.classList.toggle('is-active', active);
          pill.setAttribute('aria-checked', active ? 'true' : 'false');
        });
        updateSummaryCard();
      });
    });

    // V2V toggle switches
    container.querySelectorAll('[data-v2v-opt]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const key = btn.dataset.v2vOpt;
        state.v2v_options[key] = !state.v2v_options[key];
        btn.classList.toggle('is-on', Boolean(state.v2v_options[key]));
      });
    });

    // Ref image upload + drag/drop
    const imgInput = container.querySelector('#cr-img-input');
    const imgDrop = container.querySelector('#cr-img-dropzone');
    imgInput?.addEventListener('change', (e) => {
      const f = e.target.files?.[0];
      if (f) handleUploadImage(f);
    });
    if (imgDrop) {
      imgDrop.addEventListener('dragover', (e) => {
        e.preventDefault();
        imgDrop.classList.add('is-dragover');
      });
      imgDrop.addEventListener('dragleave', () => imgDrop.classList.remove('is-dragover'));
      imgDrop.addEventListener('drop', (e) => {
        e.preventDefault();
        imgDrop.classList.remove('is-dragover');
        const f = e.dataTransfer?.files?.[0];
        if (f) handleUploadImage(f);
      });
    }

    container.querySelectorAll('[data-remove-ref]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const idx = Number(btn.dataset.removeRef);
        if (!Number.isNaN(idx)) {
          state.ref_image_urls.splice(idx, 1);
          renderAll();
        }
      });
    });

    // Video upload + drag/drop (V2V)
    const vidInput = container.querySelector('#cr-video-input');
    const vidDrop = container.querySelector('#cr-video-dropzone');
    vidInput?.addEventListener('change', (e) => {
      const f = e.target.files?.[0];
      if (f) handleUploadVideo(f);
    });
    if (vidDrop) {
      vidDrop.addEventListener('dragover', (e) => {
        e.preventDefault();
        vidDrop.classList.add('is-dragover');
      });
      vidDrop.addEventListener('dragleave', () => vidDrop.classList.remove('is-dragover'));
      vidDrop.addEventListener('drop', (e) => {
        e.preventDefault();
        vidDrop.classList.remove('is-dragover');
        const f = e.dataTransfer?.files?.[0];
        if (f) handleUploadVideo(f);
      });
    }
  }

  renderAll();
}
