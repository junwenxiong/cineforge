/**
 * CineForge Studio — 2-Column Video Generation Studio (#studio)
 * Direct proven Kling AI / Hailuo AI / SwarmUI UX:
 *   Left column: Mode + Model + Upload + Prompt + Basic Row + Collapsed Advanced + Generate
 *   Right column: Live 4-Stage Progress & Logs + Main Video Player + My Generations + Reference Samples
 */

let _cleanupFns = [];

export function destroy() {
  while (_cleanupFns.length) {
    const fn = _cleanupFns.pop();
    try {
      fn();
    } catch {
      // ignore
    }
  }
}

function addCleanup(fn) {
  if (typeof fn === 'function') _cleanupFns.push(fn);
}

const SVG = {
  play: '<svg viewBox="0 0 24 24" fill="currentColor"><polygon points="6 4 20 12 6 20 6 4"/></svg>',
  upload: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>',
  video: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="5" width="14" height="14" rx="2"/><polygon points="22 7 16 12 22 17 22 7"/></svg>',
  image: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2.5"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>',
  download: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>',
  terminal: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>',
  x: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg>',
  refresh: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>',
  workflow: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="6" height="6" rx="1.5"/><rect x="15" y="4" width="6" height="6" rx="1.5"/><rect x="9" y="14" width="6" height="6" rx="1.5"/><path d="M9 7h6M12 10v4"/></svg>',
  chevron: '<svg class="st-adv-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>',
  check: '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
};

const QUICK_PROMPTS_ORIGINAL = [
  {
    id: 'qp_cat_space',
    label: '太空橘猫',
    title: '太空橘猫眺望地球',
    idea: '戴着迷你透明宇航头盔的橘猫趴在空间站舷窗前，暖金色舱内灯光照亮毛发，窗外是缓缓旋转的蔚蓝地球，画面充满电影感。',
    style_id: 'pixar_3d',
  },
  {
    id: 'qp_mecha',
    label: '雨夜机甲',
    title: '雨夜都市机甲启动',
    idea: '雨夜霓虹都市天台上，银蓝重型机甲缓缓抬头点亮胸口金色能源核心，镜头推进穿过雨幕，电影宽银幕质感。',
    style_id: 'cyber_mecha',
  },
  {
    id: 'qp_pet_city',
    label: '三花特工',
    title: '三花猫穿梭空中走廊',
    idea: '晴朗的近未来海滨都市里，一只戴着发光项圈的三花猫沿着玻璃天桥轻盈奔跑，回眸看向镜头，自然实拍光影。',
    style_id: 'pet_scifi',
  },
];

function stripLeadingEmoji(str) {
  return String(str || '').replace(/^[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\uFE0F★✨🚀🐱🍑🍐🏮🎞️🕵️🎬⬇📋🎁🔒\s]+/u, '').trim();
}

function formatElapsed(isoStr) {
  if (!isoStr) return '00:00';
  const ts = Date.parse(isoStr);
  if (!Number.isFinite(ts)) return '00:00';
  const diff = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  const m = Math.floor(diff / 60);
  const s = diff % 60;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function badgeClassForStatus(st) {
  if (st === 'completed') return 'is-emerald';
  if (st === 'rendering' || st === 'assembling' || st === 'previewing') return 'is-gold';
  if (st === 'queued' || st === 'queued_offline' || st === 'preview_ready') return 'is-cyan';
  if (st === 'failed') return 'is-rose';
  return '';
}

export async function render(container, ctx) {
  destroy();
  const esc = ctx.escHtml;
  const api = ctx.api;
  const toast = ctx.toast;
  let alive = true;
  addCleanup(() => {
    alive = false;
  });

  container.innerHTML = `
    <div class="st-workspace">
      <div class="skeleton" style="height:560px;border-radius:16px;"></div>
      <div class="flex-col gap-4">
        <div class="skeleton" style="height:150px;border-radius:16px;"></div>
        <div class="skeleton" style="height:360px;border-radius:16px;"></div>
      </div>
    </div>
  `;

  const [tplResp, scResp, tasksResp] = await Promise.all([
    ctx.store.getOrFetch('templates', () => api.templates(), { ttlMs: 30000 }).catch(() => ({})),
    ctx.store.getOrFetch('showcase', () => api.showcase(), { ttlMs: 30000 }).catch(() => ({})),
    api.tasks().catch(() => ({ tasks: [], recent_logs: [] })),
  ]);
  if (!alive) return;

  const styles = Array.isArray(tplResp?.styles) ? tplResp.styles : [];
  const v2vPresets = Array.isArray(tplResp?.v2v_presets) ? tplResp.v2v_presets : [];
  const storyPresets = Array.isArray(tplResp?.story_presets) ? tplResp.story_presets : [];
  const showcaseItems = Array.isArray(scResp?.items) ? scResp.items : [];
  const samples = showcaseItems.slice(0, 4);

  const query = ctx.query || {};
  const initMode = query.mode === 'v2v' ? 'v2v' : 'original';

  const state = {
    mode: initMode,
    engine: initMode === 'v2v' ? 'v2v' : 'h3',
    title: '',
    prompt: '',
    style_id: styles[0]?.id || 'pixar_3d',
    duration_sec: initMode === 'v2v' ? 15 : 5,
    aspect: initMode === 'v2v' ? '4:3' : '16:9',
    steps: 4,
    seed: '',
    refImageUrl: '',
    refImageName: '',
    sourceVideoUrl: '',
    sourceVideoName: '',
    v2vOptions: { desub: true, paw_guard: true, keep_audio: true },
    uploadingImg: false,
    uploadingVid: false,
    submitting: false,
    showLogs: false,
    playerMode: 'clean', // 'clean' | 'side_by_side'
    selectedTaskId: '',
    selectedSampleId: samples[0]?.id || '',
    snapshot: tasksResp || { tasks: [], recent_logs: [] },
    ghostTask: null,
  };

  // Pre-apply query preset/clone if provided (e.g. #studio?preset=preset_weekly_report)
  const deepKey = (query.preset || query.clone || '').toLowerCase();
  if (deepKey) {
    const mv = v2vPresets.find((p) => String(p.id).toLowerCase() === deepKey);
    const ms = storyPresets.find((p) => String(p.id).toLowerCase() === deepKey);
    const msc = showcaseItems.find((it) => String(it.id).toLowerCase() === deepKey);
    if (mv) {
      state.mode = 'v2v';
      state.engine = 'v2v';
      state.title = mv.title || '';
      state.prompt = mv.idea || '';
      state.duration_sec = 15;
      state.aspect = mv.aspect || '4:3';
      state.sourceVideoUrl = mv.source_video_url || '';
      state.sourceVideoName = mv.title || '示例原片';
    } else if (ms) {
      state.mode = 'original';
      state.title = ms.title || '';
      state.prompt = ms.idea || '';
      state.style_id = ms.style_id || state.style_id;
      state.duration_sec = ms.duration_sec <= 15 ? 15 : 30;
    } else if (msc) {
      const isV2v = msc.mode === 'v2v' || Boolean(msc.side_by_side_url);
      state.mode = isV2v ? 'v2v' : 'original';
      state.engine = isV2v ? 'v2v' : 'h3';
      state.title = `${msc.title} · 同款`;
      state.prompt = msc.subtitle || msc.title || '';
      state.aspect = isV2v ? '4:3' : '16:9';
      if (isV2v && msc.video_url) {
        state.sourceVideoUrl = msc.video_url;
        state.sourceVideoName = msc.title;
      }
    }
  } else if (initMode === 'v2v' && v2vPresets[0]) {
    state.sourceVideoUrl = v2vPresets[0].source_video_url || '';
    state.sourceVideoName = v2vPresets[0].title || '三国演义示例';
    state.prompt = v2vPresets[0].idea || '';
  }

  // Auto-select latest user task if any exists
  const initialTasks = Array.isArray(state.snapshot.tasks) ? state.snapshot.tasks : [];
  if (initialTasks.length > 0) {
    state.selectedTaskId = initialTasks[0].project_id;
  }

  function getMergedTasks() {
    const serverTasks = Array.isArray(state.snapshot?.tasks) ? state.snapshot.tasks : [];
    if (state.ghostTask && !serverTasks.some((t) => t.project_id === state.ghostTask.project_id)) {
      return [state.ghostTask, ...serverTasks];
    }
    return serverTasks;
  }

  function getSelectedTask() {
    const list = getMergedTasks();
    if (!list.length) return null;
    if (state.selectedTaskId) {
      const found = list.find((t) => t.project_id === state.selectedTaskId);
      if (found) return found;
    }
    return list[0];
  }

  function isGuestMode() {
    return document.body.classList.contains('is-server-guest');
  }

  // Static shell mounted ONCE so typing / video playback NEVER loses focus or resets!
  container.innerHTML = `
    <div class="st-workspace" data-view="studio">
      <!-- LEFT: Generation Control Panel -->
      <aside class="st-form-panel" id="st-form-panel" aria-label="视频生成参数">
        <div class="st-mode-tabs" role="tablist" aria-label="生成模式">
          <button type="button" class="st-mode-btn" data-mode="original">文 / 图生视频</button>
          <button type="button" class="st-mode-btn" data-mode="v2v">视频换角 (V2V)</button>
        </div>

        <div class="st-field" id="st-engine-field"></div>
        <div class="st-field" id="st-media-field"></div>

        <div class="st-field">
          <div class="st-label-row">
            <label class="st-label" for="st-prompt">画面描述</label>
            <span class="st-label-hint">支持中文或英文</span>
          </div>
          <textarea
            id="st-prompt"
            class="st-textarea"
            rows="4"
            placeholder="描述主角、动作、场景和光影，例如：戴宇航头盔的橘猫在空间站舷窗前眺望地球..."
          >${esc(state.prompt)}</textarea>
          <div class="st-chips" id="st-quick-prompts"></div>
        </div>

        <div class="st-basic-row">
          <div class="st-field">
            <span class="st-label">视频时长</span>
            <div class="st-pill-group" id="st-dur-pills">
              <button type="button" class="st-pill" data-dur="5">5秒</button>
              <button type="button" class="st-pill" data-dur="15">15秒</button>
              <button type="button" class="st-pill" data-dur="30">30秒</button>
            </div>
          </div>
          <div class="st-field">
            <span class="st-label">画面比例</span>
            <div class="st-pill-group" id="st-aspect-pills">
              <button type="button" class="st-pill" data-aspect="16:9">16:9</button>
              <button type="button" class="st-pill" data-aspect="9:16">9:16</button>
              <button type="button" class="st-pill" data-aspect="4:3">4:3</button>
            </div>
          </div>
        </div>

        <details class="st-advanced" id="st-advanced">
          <summary>
            <span>高级参数（画风 / 步数 / 随机种子）</span>
            ${SVG.chevron}
          </summary>
          <div class="st-adv-body">
            <div class="st-field">
              <label class="st-label" for="st-style-select">视觉风格</label>
              <select id="st-style-select" class="st-select">
                ${styles.map((s) => `<option value="${esc(s.id)}">${esc(s.name)}</option>`).join('')}
              </select>
            </div>
            <div class="st-adv-grid">
              <div class="st-field">
                <label class="st-label" for="st-steps-select">推理步数</label>
                <select id="st-steps-select" class="st-select">
                  <option value="4">4 步 (Turbo 最快)</option>
                  <option value="8">8 步 (平衡)</option>
                  <option value="20">20 步 (精细)</option>
                </select>
              </div>
              <div class="st-field">
                <label class="st-label" for="st-seed-input">随机种子</label>
                <input id="st-seed-input" class="st-input" type="number" placeholder="留空随机" />
              </div>
            </div>
            <div class="st-check-row" id="st-v2v-checks" hidden>
              <label class="st-check"><input type="checkbox" id="st-chk-desub" checked /> 自动去原片字幕</label>
              <label class="st-check"><input type="checkbox" id="st-chk-paw" checked /> 护爪防穿帮</label>
              <label class="st-check"><input type="checkbox" id="st-chk-audio" checked /> 保留原声对白</label>
            </div>
          </div>
        </details>

        <div class="st-submit-wrap">
          <button type="button" class="st-submit-btn" id="st-generate-btn">
            ${SVG.play}
            <span>立即生成视频</span>
          </button>
          <div class="st-submit-hint" id="st-submit-hint"></div>
        </div>
      </aside>

      <!-- RIGHT: Live Progress + Main Video Player + History + Reference Samples -->
      <section class="st-stage-col" aria-label="实时进度与成片区">
        <div id="st-progress-slot"></div>
        <div class="st-card st-player-card" id="st-player-card"></div>
        <div class="st-card" id="st-history-section"></div>
        <div class="st-card" id="st-samples-section"></div>
      </section>
    </div>
  `;

  // Render Left Dynamic Sections
  function renderLeftDynamic() {
    // Mode buttons
    container.querySelectorAll('.st-mode-btn').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.mode === state.mode);
    });

    // Engine selector
    const engEl = container.querySelector('#st-engine-field');
    if (state.mode === 'v2v') {
      engEl.innerHTML = `
        <span class="st-label">云端模型</span>
        <div class="st-locked-engine">
          <span>LTX-2.5 V2V (视频换角 / 变猫咪)</span>
          <span style="font-size:11px;opacity:0.8;">Colab GPU</span>
        </div>
      `;
    } else {
      engEl.innerHTML = `
        <label class="st-label" for="st-engine-select">云端模型</label>
        <select id="st-engine-select" class="st-select">
          <option value="h3" ${state.engine === 'h3' ? 'selected' : ''}>MiniMax-H3 (开源4步 · 推荐)</option>
          <option value="ltx" ${state.engine === 'ltx' ? 'selected' : ''}>LTX-2.5 (图生 / 电影运镜)</option>
        </select>
      `;
      engEl.querySelector('#st-engine-select')?.addEventListener('change', (ev) => {
        state.engine = ev.target.value;
      });
    }

    // Media uploaders
    const mediaEl = container.querySelector('#st-media-field');
    if (state.mode === 'v2v') {
      const vidPreview = state.sourceVideoUrl
        ? `
          <div class="st-media-preview">
            <div class="st-drop-icon">${SVG.video}</div>
            <span class="st-media-name" title="${esc(state.sourceVideoName)}">${esc(state.sourceVideoName || '已选择原片视频')}</span>
            <button type="button" class="st-media-remove" id="st-clear-vid" aria-label="移除原片">${SVG.x}</button>
          </div>
        `
        : `
          <div class="st-dropzone" id="st-vid-drop">
            <input type="file" id="st-vid-input" accept="video/mp4,video/quicktime,video/webm" />
            <div class="st-drop-icon">${SVG.video}</div>
            <div class="st-drop-copy">
              <div class="st-drop-title">${state.uploadingVid ? '正在上传原片视频...' : '上传原片视频 (MP4 / MOV)'}</div>
              <div class="st-drop-sub">或点击下方一键使用经典名场面示例</div>
            </div>
          </div>
        `;

      const presetChips = v2vPresets.slice(0, 3).map((p) => {
        const shortName = stripLeadingEmoji(p.title || p.label).split('·')[0].trim().slice(0, 8);
        const isAct = state.sourceVideoUrl && state.sourceVideoUrl === p.source_video_url;
        return `<button type="button" class="st-chip ${isAct ? 'active' : ''}" data-v2v-clip="${esc(p.id)}">${esc(shortName)}</button>`;
      }).join('');

      const imgBlock = state.refImageUrl
        ? `
          <div class="st-media-preview">
            <img class="st-media-thumb" src="${esc(state.refImageUrl)}" alt="角色参考图" />
            <span class="st-media-name">${esc(state.refImageName || '已上传角色参考图')}</span>
            <button type="button" class="st-media-remove" id="st-clear-img" aria-label="移除参考图">${SVG.x}</button>
          </div>
        `
        : `
          <div class="st-dropzone" id="st-img-drop">
            <input type="file" id="st-img-input" accept="image/png,image/jpeg,image/webp" />
            <div class="st-drop-icon">${SVG.image}</div>
            <div class="st-drop-copy">
              <div class="st-drop-title">${state.uploadingImg ? '正在上传参考图...' : '目标角色照片（可选）'}</div>
              <div class="st-drop-sub">上传自家猫咪或角色图，留空用默认猫咪</div>
            </div>
          </div>
        `;

      mediaEl.innerHTML = `
        <div class="st-label-row">
          <span class="st-label">原片视频</span>
          <span class="st-label-hint">必填或选示例</span>
        </div>
        ${vidPreview}
        <div class="st-chips">${presetChips}</div>
        <div class="st-label-row" style="margin-top:4px;">
          <span class="st-label">角色参考图</span>
          <span class="st-label-hint">可选</span>
        </div>
        ${imgBlock}
      `;
    } else {
      const imgBlock = state.refImageUrl
        ? `
          <div class="st-media-preview">
            <img class="st-media-thumb" src="${esc(state.refImageUrl)}" alt="参考图" />
            <span class="st-media-name">${esc(state.refImageName || '已上传参考图')}</span>
            <button type="button" class="st-media-remove" id="st-clear-img" aria-label="移除参考图">${SVG.x}</button>
          </div>
        `
        : `
          <div class="st-dropzone" id="st-img-drop">
            <input type="file" id="st-img-input" accept="image/png,image/jpeg,image/webp" />
            <div class="st-drop-icon">${SVG.upload}</div>
            <div class="st-drop-copy">
              <div class="st-drop-title">${state.uploadingImg ? '正在上传图片...' : '参考图 / 首帧图（可选）'}</div>
              <div class="st-drop-sub">支持 JPG / PNG / WebP，用于锁定角色外貌</div>
            </div>
          </div>
        `;
      mediaEl.innerHTML = `
        <div class="st-label-row">
          <span class="st-label">参考图</span>
          <span class="st-label-hint">图生视频或锁角色</span>
        </div>
        ${imgBlock}
      `;
    }

    // Bind media events
    mediaEl.querySelector('#st-img-input')?.addEventListener('change', (ev) => handleImageUpload(ev.target.files?.[0]));
    mediaEl.querySelector('#st-vid-input')?.addEventListener('change', (ev) => handleVideoUpload(ev.target.files?.[0]));
    mediaEl.querySelector('#st-clear-img')?.addEventListener('click', () => {
      state.refImageUrl = '';
      state.refImageName = '';
      renderLeftDynamic();
    });
    mediaEl.querySelector('#st-clear-vid')?.addEventListener('click', () => {
      state.sourceVideoUrl = '';
      state.sourceVideoName = '';
      renderLeftDynamic();
    });
    mediaEl.querySelectorAll('[data-v2v-clip]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const preset = v2vPresets.find((p) => p.id === btn.dataset.v2vClip);
        if (!preset) return;
        state.sourceVideoUrl = preset.source_video_url || '';
        state.sourceVideoName = preset.title || '示例原片';
        state.title = preset.title || '';
        state.prompt = preset.idea || '';
        state.aspect = preset.aspect || '4:3';
        const ta = container.querySelector('#st-prompt');
        if (ta) ta.value = state.prompt;
        renderLeftDynamic();
      });
    });

    // Quick prompt chips
    const qpWrap = container.querySelector('#st-quick-prompts');
    if (state.mode === 'v2v') {
      qpWrap.innerHTML = v2vPresets.slice(0, 3).map((p) => {
        const lbl = stripLeadingEmoji(p.title || p.label).split('·')[0].trim().slice(0, 8) + '变猫';
        return `<button type="button" class="st-chip" data-qp-v2v="${esc(p.id)}">${esc(lbl)}</button>`;
      }).join('');
      qpWrap.querySelectorAll('[data-qp-v2v]').forEach((btn) => {
        btn.addEventListener('click', () => {
          const p = v2vPresets.find((x) => x.id === btn.dataset.qpV2v);
          if (!p) return;
          state.title = p.title || '';
          state.prompt = p.idea || '';
          state.sourceVideoUrl = p.source_video_url || state.sourceVideoUrl;
          state.sourceVideoName = p.title || state.sourceVideoName;
          const ta = container.querySelector('#st-prompt');
          if (ta) ta.value = state.prompt;
          renderLeftDynamic();
        });
      });
    } else {
      qpWrap.innerHTML = QUICK_PROMPTS_ORIGINAL.map(
        (qp) => `<button type="button" class="st-chip" data-qp-id="${esc(qp.id)}">${esc(qp.label)}</button>`
      ).join('');
      qpWrap.querySelectorAll('[data-qp-id]').forEach((btn) => {
        btn.addEventListener('click', () => {
          const qp = QUICK_PROMPTS_ORIGINAL.find((x) => x.id === btn.dataset.qpId);
          if (!qp) return;
          state.title = qp.title;
          state.prompt = qp.idea;
          state.style_id = qp.style_id;
          const ta = container.querySelector('#st-prompt');
          if (ta) ta.value = state.prompt;
          const sel = container.querySelector('#st-style-select');
          if (sel) sel.value = state.style_id;
        });
      });
    }

    // Duration & aspect pills
    container.querySelectorAll('#st-dur-pills .st-pill').forEach((btn) => {
      btn.classList.toggle('active', Number(btn.dataset.dur) === Number(state.duration_sec));
    });
    container.querySelectorAll('#st-aspect-pills .st-pill').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.aspect === state.aspect);
    });

    // V2V checkboxes visibility
    const v2vChecks = container.querySelector('#st-v2v-checks');
    if (v2vChecks) v2vChecks.hidden = state.mode !== 'v2v';

    // Submit button & honest hint
    const submitBtn = container.querySelector('#st-generate-btn');
    const hintEl = container.querySelector('#st-submit-hint');
    if (submitBtn) {
      submitBtn.disabled = state.submitting || state.uploadingImg || state.uploadingVid;
      submitBtn.querySelector('span').textContent = state.submitting ? '正在提交任务...' : '立即生成视频';
    }
    if (hintEl) {
      const snap = state.snapshot || {};
      if (snap.colab_connected) {
        hintEl.textContent = `Colab 在线 (${snap.online_gpu_count} GPU) · 提交后自动开始云端渲染`;
      } else if (isGuestMode()) {
        hintEl.textContent = '提交后自动排入共享显卡队列，并先生成即时预演';
      } else {
        hintEl.textContent = '先出 2 秒本地快速预演，同时排入 Colab 高清渲染队列';
      }
    }
  }

  async function handleImageUpload(file) {
    if (!file) return;
    if (!/\.(png|jpe?g|webp)$/i.test(file.name)) {
      toast('仅支持 JPG / PNG / WebP 格式图片', 'warning');
      return;
    }
    state.uploadingImg = true;
    renderLeftDynamic();
    try {
      const res = await api.uploadFile(file);
      state.refImageUrl = res.url || '';
      state.refImageName = file.name;
      toast('参考图已上传', 'success');
    } catch (err) {
      toast(err?.message || '图片上传失败', 'error');
    } finally {
      state.uploadingImg = false;
      renderLeftDynamic();
    }
  }

  async function handleVideoUpload(file) {
    if (!file) return;
    if (!/\.(mp4|mov|webm)$/i.test(file.name)) {
      toast('仅支持 MP4 / MOV / WebM 格式视频', 'warning');
      return;
    }
    state.uploadingVid = true;
    renderLeftDynamic();
    try {
      const res = await api.uploadFile(file);
      state.sourceVideoUrl = res.url || '';
      state.sourceVideoName = file.name;
      toast('原片视频已上传', 'success');
    } catch (err) {
      toast(err?.message || '视频上传失败', 'error');
    } finally {
      state.uploadingVid = false;
      renderLeftDynamic();
    }
  }

  // Render Right: 1. Live Progress Panel
  function renderProgressCard() {
    const slot = container.querySelector('#st-progress-slot');
    if (!slot) return;
    const task = getSelectedTask();
    if (!task) {
      slot.innerHTML = '';
      return;
    }

    const st = task.overall_status || 'draft';
    const pct = Math.max(0, Math.min(100, Number(task.overall_progress || 0)));
    const isDone = st === 'completed';
    const isError = st === 'failed';
    const isActive = ['previewing', 'queued', 'queued_offline', 'rendering', 'assembling'].includes(st);
    const stepIdx = Number(task.step_index ?? 0);
    const cq = task.cloud_job;
    const shotInfo = cq && cq.total_shots > 0 ? ` (${cq.done_shots || 0}/${cq.total_shots}镜)` : '';

    const steps = [
      { idx: 0, label: '1. 提交任务' },
      { idx: 1, label: '2. 本地预演' },
      { idx: 2, label: `3. Colab 渲染${shotInfo}` },
      { idx: 3, label: '4. 合成成片' },
    ];

    const stepHtml = steps.map((sp) => {
      let cls = '';
      let numContent = String(sp.idx + 1);
      if (isDone || sp.idx < stepIdx) {
        cls = 'is-done';
        numContent = SVG.check;
      } else if (isError && sp.idx === stepIdx) {
        cls = 'is-error';
      } else if (sp.idx === stepIdx) {
        cls = 'is-active';
      }
      return `
        <div class="st-step ${cls}">
          <span class="st-step-num">${numContent}</span>
          <span>${esc(sp.label)}</span>
        </div>
      `;
    }).join('');

    const offlineBanner =
      st === 'queued_offline' && !isGuestMode()
        ? `
          <div class="st-offline-banner" id="st-offline-banner">
            <span>当前未检测到在线 Colab GPU，任务已排队。启动 Colab 后会自动接单渲染。</span>
            <a href="#farm" class="st-mini-btn is-gold">去连接 Colab</a>
          </div>
        `
        : '';

    const logs = Array.isArray(state.snapshot?.recent_logs) ? state.snapshot.recent_logs : [];
    const logsHtml = state.showLogs
      ? `
        <div class="st-log-panel" id="st-log-panel" role="log">
          <div class="st-log-line">
            <span class="st-log-time">TASK</span>
            <span class="st-log-tag">${esc(task.engine)}</span>
            <span>状态=${esc(st)} | 进度=${pct}% | ${esc(task.status_detail)}</span>
          </div>
          ${logs.length > 0
            ? logs.slice(0, 20).map((lg) => `
                <div class="st-log-line ${lg.level === 'ok' ? 'is-ok' : lg.level === 'error' ? 'is-error' : ''}">
                  <span class="st-log-time">${esc(lg.time || '--:--')}</span>
                  <span class="st-log-tag">${esc(lg.tag || 'LOG')}</span>
                  <span>${esc(lg.message)}</span>
                </div>
              `).join('')
            : '<div class="st-log-line"><span class="st-log-time">--:--</span><span class="st-log-tag">INFO</span><span>暂无 Colab 运行日志；连接 Colab 后实时渲染日志会显示在这里。</span></div>'
          }
        </div>
      `
      : '';

    const canCancel = cq && ['queued', 'staging', 'rendering', 'assembling'].includes(cq.status);
    const canRetry = ['failed', 'canceled', 'preview_ready', 'draft'].includes(st);

    slot.innerHTML = `
      <div class="st-card st-progress-card ${isDone ? 'is-done' : isError ? 'is-error' : ''}" id="st-live-card">
        <div class="st-prog-head">
          <div class="st-prog-title-wrap">
            <span class="st-prog-title">${esc(task.title)}</span>
            <span class="st-badge ${badgeClassForStatus(st)}">${esc(task.status_label)}</span>
            <span class="st-badge">${esc(task.engine)}</span>
          </div>
          <div class="st-prog-meta">
            ${isActive ? `<span class="st-elapsed" id="st-elapsed-timer">${formatElapsed(task.created_at)}</span>` : ''}
          </div>
        </div>

        <div class="st-stepper">${stepHtml}</div>

        <div class="st-bar-row">
          <div class="st-bar-track">
            <div class="st-bar-fill ${isDone ? 'is-done' : isError ? 'is-error' : ''}" style="width:${pct}%"></div>
          </div>
          <span class="st-bar-pct">${pct}%</span>
        </div>

        <div class="st-prog-msg">${esc(task.status_detail)}</div>
        ${offlineBanner}

        <div class="st-prog-actions">
          ${!isGuestMode() ? `
            <button type="button" class="st-mini-btn" id="st-toggle-logs">
              ${SVG.terminal}
              <span>${state.showLogs ? '收起实时日志' : '查看实时日志'}</span>
            </button>
          ` : ''}
          <a href="#workflow/${encodeURIComponent(task.project_id)}" class="st-mini-btn">
            ${SVG.workflow}
            <span>去工作流细调</span>
          </a>
          ${canRetry ? `
            <button type="button" class="st-mini-btn is-gold" id="st-retry-btn">
              ${SVG.refresh}
              <span>重新提交 Colab</span>
            </button>
          ` : ''}
          ${canCancel ? `
            <button type="button" class="st-mini-btn is-danger" id="st-cancel-btn">
              ${SVG.x}
              <span>取消任务</span>
            </button>
          ` : ''}
        </div>
        ${logsHtml}
      </div>
    `;

    slot.querySelector('#st-toggle-logs')?.addEventListener('click', () => {
      state.showLogs = !state.showLogs;
      renderProgressCard();
    });
    slot.querySelector('#st-cancel-btn')?.addEventListener('click', async () => {
      if (!cq?.id) return;
      try {
        await api.cancelQueueJob(cq.id);
        toast('已取消该云端渲染任务', 'info');
        await pollTasks();
      } catch (err) {
        toast(err?.message || '取消失败', 'error');
      }
    });
    slot.querySelector('#st-retry-btn')?.addEventListener('click', async () => {
      try {
        await api.dispatchCloud(task.project_id);
        toast('已重新加入 Colab 渲染队列', 'success');
        await pollTasks();
      } catch (err) {
        toast(err?.message || '提交失败', 'error');
      }
    });
  }

  // Render Right: 2. Main Video Player (preserve active <video> src if unchanged!)
  let lastPlayerKey = '';
  function renderPlayerCard() {
    const card = container.querySelector('#st-player-card');
    if (!card) return;

    const task = getSelectedTask();
    let videoUrl = '';
    let sbsUrl = '';
    let posterUrl = '';
    let sourceLabel = '';
    let sourceCls = '';
    let title = '';
    let downloadName = 'cineforge_video.mp4';
    let isTaskView = false;

    if (task) {
      isTaskView = true;
      title = task.title;
      sbsUrl = task.side_by_side_url || '';
      downloadName = `${task.project_id}.mp4`;
      if (task.final_video_url) {
        videoUrl = state.playerMode === 'side_by_side' && sbsUrl ? sbsUrl : task.final_video_url;
        posterUrl = ''; // Show real Colab MP4 first frame instead of stale preview poster
        sourceLabel = state.playerMode === 'side_by_side' && sbsUrl ? '左右原片对照版' : 'Colab 高清成片';
        sourceCls = 'is-emerald';
      } else if (task.preview_video_url) {
        videoUrl = task.preview_video_url;
        posterUrl = task.poster_url || '';
        sourceLabel = '本地快速预演（等待 Colab 高清渲染）';
        sourceCls = 'is-cyan';
      } else {
        posterUrl = task.poster_url || '';
        sourceLabel = '正在合成快速预演...';
        sourceCls = 'is-gold';
      }
    } else {
      const sample = samples.find((s) => s.id === state.selectedSampleId) || samples[0];
      if (sample) {
        title = sample.title;
        posterUrl = sample.poster_url || '';
        sbsUrl = sample.side_by_side_url || '';
        videoUrl = state.playerMode === 'side_by_side' && sbsUrl ? sbsUrl : (sample.video_url || '');
        sourceLabel = '示例样片 · 可点击下方按钮填同款参数';
        sourceCls = '';
        downloadName = `${sample.id}.mp4`;
      }
    }

    const playerKey = `${videoUrl}|${sbsUrl}|${sourceLabel}|${state.playerMode}|${title}`;
    if (playerKey === lastPlayerKey && card.querySelector('#st-main-video')) {
      return;
    }
    lastPlayerKey = playerKey;

    const viewportHtml = videoUrl
      ? `
        <video
          id="st-main-video"
          class="st-video-el"
          src="${esc(videoUrl)}"
          ${posterUrl ? `poster="${esc(posterUrl)}"` : ''}
          controls
          playsinline
          preload="metadata"
        ></video>
      `
      : `
        <div class="st-player-empty">
          <div class="st-spinner"></div>
          <div style="font-size:14px;font-weight:600;color:var(--text-primary);">${esc(title || '准备就绪')}</div>
          <div style="font-size:12.5px;">${isTaskView ? '正在生成本地快速预演，约 2 秒后即可预览...' : '在左侧输入画面描述，点击「立即生成视频」开始创作'}</div>
        </div>
      `;

    card.innerHTML = `
      <div class="st-player-viewport">${viewportHtml}</div>
      <div class="st-player-bar">
        <div class="st-player-bar-left">
          <span class="st-badge ${sourceCls}">${esc(sourceLabel || '预览播放器')}</span>
          ${sbsUrl ? `
            <div class="segmented" id="st-sbs-switch">
              <button type="button" class="segmented-btn ${state.playerMode === 'clean' ? 'active' : ''}" data-pm="clean">纯净版</button>
              <button type="button" class="segmented-btn ${state.playerMode === 'side_by_side' ? 'active' : ''}" data-pm="side_by_side">左右对照</button>
            </div>
          ` : ''}
        </div>
        <div class="st-player-bar-right">
          ${videoUrl ? `
            <a href="${esc(videoUrl)}" download="${esc(downloadName)}" class="st-mini-btn is-gold" id="st-download-btn">
              ${SVG.download}
              <span>下载 MP4</span>
            </a>
          ` : ''}
          ${!isTaskView && samples.length > 0 ? `
            <button type="button" class="st-mini-btn" id="st-use-sample-btn">用此样片参数</button>
          ` : ''}
          ${isTaskView && task ? `
            <button type="button" class="st-mini-btn" id="st-reuse-params-btn">填入左侧重拍</button>
          ` : ''}
        </div>
      </div>
    `;

    card.querySelectorAll('[data-pm]').forEach((btn) => {
      btn.addEventListener('click', () => {
        state.playerMode = btn.dataset.pm;
        lastPlayerKey = '';
        renderPlayerCard();
      });
    });

    card.querySelector('#st-use-sample-btn')?.addEventListener('click', () => {
      const sample = samples.find((s) => s.id === state.selectedSampleId) || samples[0];
      if (sample) fillFromSample(sample);
    });

    card.querySelector('#st-reuse-params-btn')?.addEventListener('click', () => {
      if (!task) return;
      state.mode = task.mode === 'v2v' ? 'v2v' : 'original';
      state.engine = task.engine === 'LTX-2.5' ? 'ltx' : (state.mode === 'v2v' ? 'v2v' : 'h3');
      state.title = task.title || '';
      state.prompt = task.idea || task.title || '';
      state.aspect = task.aspect || '16:9';
      state.duration_sec = [5, 15, 30].includes(task.duration_sec) ? task.duration_sec : 15;
      const ta = container.querySelector('#st-prompt');
      if (ta) ta.value = state.prompt;
      renderLeftDynamic();
      toast('已将该视频参数填回左侧面板', 'info');
    });
  }

  // Render Right: 3. My Generations History Grid
  function renderHistoryGrid() {
    const sec = container.querySelector('#st-history-section');
    if (!sec) return;
    const list = getMergedTasks();
    const activeSel = getSelectedTask()?.project_id || '';

    const gridHtml = list.length > 0
      ? `
        <div class="st-grid">
          ${list.map((t) => {
            const isSel = t.project_id === activeSel;
            const playable = t.final_video_url || t.preview_video_url || '';
            const isActive = ['previewing', 'queued', 'queued_offline', 'rendering', 'assembling'].includes(t.overall_status);
            const pct = Math.max(0, Math.min(100, Number(t.overall_progress || 0)));
            const stCls = badgeClassForStatus(t.overall_status);
            const thumb = t.poster_url
              ? `<img src="${esc(t.poster_url)}" alt="${esc(t.title)}" loading="lazy" />`
              : `<div class="st-item-ghost-bg"><div class="st-spinner"></div><span>${pct}%</span></div>`;
            return `
              <article class="st-item-card ${isSel ? 'is-selected' : ''}" data-task-id="${esc(t.project_id)}">
                <div class="st-item-thumb">
                  ${thumb}
                  <span class="st-item-status-tag ${stCls}">${esc(t.status_label)}</span>
                  <span class="st-item-engine-tag">${esc(t.engine)}</span>
                  ${isActive ? `<div class="st-item-prog-strip"><div class="st-item-prog-fill" style="width:${pct}%"></div></div>` : ''}
                </div>
                <div class="st-item-body">
                  <div class="st-item-title">${esc(t.title)}</div>
                  <div class="st-item-foot">
                    <span>${esc(t.duration_sec)}秒 · ${esc(t.aspect)}</span>
                    ${playable
                      ? `<a href="${esc(playable)}" download="${esc(t.project_id)}.mp4" class="st-item-action-link" data-stop-prop>下载</a>`
                      : `<span>${pct}%</span>`
                    }
                  </div>
                </div>
              </article>
            `;
          }).join('')}
        </div>
      `
      : `<div class="st-empty-history">还没有生成记录。在左侧输入描述（或点击快捷示例），点「立即生成视频」即可在这里实时查看进度和成片。</div>`;

    sec.innerHTML = `
      <div class="st-section-head">
        <div class="st-section-title">
          <span>我的生成记录</span>
          <span class="st-count-pill">${list.length}</span>
        </div>
        <button type="button" class="st-mini-btn" id="st-refresh-tasks">
          ${SVG.refresh}
          <span>刷新进度</span>
        </button>
      </div>
      ${gridHtml}
    `;

    sec.querySelector('#st-refresh-tasks')?.addEventListener('click', () => pollTasks(true));
    sec.querySelectorAll('[data-stop-prop]').forEach((a) => {
      a.addEventListener('click', (ev) => ev.stopPropagation());
    });
    sec.querySelectorAll('[data-task-id]').forEach((cardEl) => {
      cardEl.addEventListener('click', () => {
        state.selectedTaskId = cardEl.dataset.taskId;
        state.playerMode = 'clean';
        lastPlayerKey = '';
        renderProgressCard();
        renderPlayerCard();
        renderHistoryGrid();
      });
    });
  }

  // Render Right: 4. Compact Reference Samples Strip
  function fillFromSample(sample) {
    const isV2v = sample.mode === 'v2v' || Boolean(sample.side_by_side_url);
    state.mode = isV2v ? 'v2v' : 'original';
    state.engine = isV2v ? 'v2v' : 'h3';
    state.title = `${sample.title} · 同款`;
    state.prompt = sample.subtitle || sample.title || '';
    state.aspect = isV2v ? '4:3' : '16:9';
    state.duration_sec = isV2v ? 15 : 5;
    if (isV2v && sample.video_url) {
      state.sourceVideoUrl = sample.video_url;
      state.sourceVideoName = sample.title;
    }
    const ta = container.querySelector('#st-prompt');
    if (ta) ta.value = state.prompt;
    renderLeftDynamic();
    toast(`已填入《${sample.title}》同款参数`, 'success');
  }

  function renderSamplesStrip() {
    const sec = container.querySelector('#st-samples-section');
    if (!sec) return;
    if (!samples.length) {
      sec.hidden = true;
      return;
    }

    sec.innerHTML = `
      <div class="st-section-head">
        <div class="st-section-title">
          <span>参考样片</span>
          <span class="st-label-hint">点击预览，或一键填入左侧做同款</span>
        </div>
      </div>
      <div class="st-grid-4">
        ${samples.map((it) => `
          <article class="st-item-card" data-sample-play="${esc(it.id)}">
            <div class="st-item-thumb">
              <img src="${esc(it.poster_url || '')}" alt="${esc(it.title)}" loading="lazy" />
              <span class="st-item-engine-tag">${it.mode === 'v2v' ? 'V2V' : 'H3'}</span>
            </div>
            <div class="st-item-body">
              <div class="st-item-title">${esc(it.title)}</div>
              <div class="st-item-foot">
                <span>${esc(it.duration_label || '')}</span>
                <button type="button" class="st-item-action-link" data-sample-fill="${esc(it.id)}">填同款</button>
              </div>
            </div>
          </article>
        `).join('')}
      </div>
    `;

    sec.querySelectorAll('[data-sample-fill]').forEach((btn) => {
      btn.addEventListener('click', (ev) => {
        ev.stopPropagation();
        const item = samples.find((x) => x.id === btn.dataset.sampleFill);
        if (item) fillFromSample(item);
      });
    });

    sec.querySelectorAll('[data-sample-play]').forEach((cardEl) => {
      cardEl.addEventListener('click', () => {
        const item = samples.find((x) => x.id === cardEl.dataset.samplePlay);
        if (!item) return;
        ctx.openVideoModal({
          title: item.title,
          subtitle: item.subtitle,
          videoUrl: item.video_url,
          sideBySideUrl: item.side_by_side_url,
          posterUrl: item.poster_url,
          onClone: () => fillFromSample(item),
        });
      });
    });
  }

  // Submit Generation (stays right on this page, shows instant ghost card + live progress!)
  async function handleSubmit() {
    if (state.submitting) return;
    const promptVal = (container.querySelector('#st-prompt')?.value || '').trim();
    state.prompt = promptVal;

    let finalPrompt = promptVal;
    let finalTitle = state.title.trim();
    if (!finalPrompt) {
      if (state.mode === 'v2v') {
        finalPrompt = '保留原片声画节奏与口型动作，将主角重演为写实拟人猫咪，自动抹除原片字幕并保持手爪自然。';
      } else {
        toast('请先输入画面描述，或点击输入框下方示例', 'warning');
        container.querySelector('#st-prompt')?.focus();
        return;
      }
    }
    if (!finalTitle) {
      finalTitle = finalPrompt.replace(/\s+/g, ' ').slice(0, 18);
    }
    if (state.mode === 'v2v' && !state.sourceVideoUrl && v2vPresets[0]?.source_video_url) {
      state.sourceVideoUrl = v2vPresets[0].source_video_url;
      state.sourceVideoName = v2vPresets[0].title || '示例原片';
    }

    state.submitting = true;
    renderLeftDynamic();

    const tempId = `pending_${Date.now()}`;
    state.ghostTask = {
      project_id: tempId,
      title: finalTitle,
      idea: finalPrompt,
      mode: state.mode,
      engine: state.mode === 'v2v' ? 'LTX-2.5 V2V' : (state.engine === 'ltx' ? 'LTX-2.5' : 'MiniMax-H3'),
      duration_sec: state.duration_sec,
      aspect: state.aspect,
      poster_url: state.refImageUrl || '',
      overall_status: 'previewing',
      overall_progress: 8,
      step_index: 0,
      status_label: '提交中...',
      status_detail: '正在创建任务并启动本地快速预演...',
      created_at: new Date().toISOString(),
    };
    state.selectedTaskId = tempId;
    lastPlayerKey = '';
    renderProgressCard();
    renderPlayerCard();
    renderHistoryGrid();

    try {
      const payload = {
        title: finalTitle,
        idea: finalPrompt,
        mode: state.mode,
        engine: state.mode === 'v2v' ? 'v2v' : state.engine,
        style_id: state.style_id,
        duration_sec: state.duration_sec,
        aspect: state.aspect,
        character_name: state.mode === 'v2v' ? '主角猫咪' : '主角',
        ref_image_urls: state.refImageUrl ? [state.refImageUrl] : [],
        source_video_url: state.mode === 'v2v' ? (state.sourceVideoUrl || null) : null,
        v2v_options: state.v2vOptions,
        steps: state.steps,
        seed: state.seed ? Number(state.seed) : undefined,
        auto_dispatch: true,
      };
      const res = await api.createProject(payload);
      const createdProj = res?.project;
      if (createdProj?.id) {
        state.selectedTaskId = createdProj.id;
        state.ghostTask = null;
      }
      state.title = '';
      toast('任务已提交，可在右侧实时查看进度', 'success');
      await pollTasks();
    } catch (err) {
      state.ghostTask = null;
      toast(err?.message || '提交生成失败', 'error');
      renderProgressCard();
      renderPlayerCard();
      renderHistoryGrid();
    } finally {
      state.submitting = false;
      renderLeftDynamic();
    }
  }

  async function pollTasks(manual = false) {
    try {
      const snap = await api.tasks();
      if (!alive) return;
      state.snapshot = snap;
      ctx.store.set('liveTasks', snap);
      renderLeftDynamic();
      renderProgressCard();
      renderPlayerCard();
      renderHistoryGrid();
      if (manual) toast('任务状态已刷新', 'info');
    } catch {
      if (manual) toast('刷新失败，请检查本地服务', 'error');
    }
  }

  // Bind static left-panel controls
  container.querySelectorAll('.st-mode-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const next = btn.dataset.mode;
      if (next === state.mode) return;
      state.mode = next;
      state.engine = next === 'v2v' ? 'v2v' : 'h3';
      state.duration_sec = next === 'v2v' ? 15 : 5;
      state.aspect = next === 'v2v' ? '4:3' : '16:9';
      if (next === 'v2v' && !state.sourceVideoUrl && v2vPresets[0]) {
        state.sourceVideoUrl = v2vPresets[0].source_video_url || '';
        state.sourceVideoName = v2vPresets[0].title || '示例原片';
      }
      renderLeftDynamic();
    });
  });

  container.querySelector('#st-prompt')?.addEventListener('input', (ev) => {
    state.prompt = ev.target.value;
  });

  container.querySelectorAll('#st-dur-pills .st-pill').forEach((btn) => {
    btn.addEventListener('click', () => {
      state.duration_sec = Number(btn.dataset.dur);
      renderLeftDynamic();
    });
  });

  container.querySelectorAll('#st-aspect-pills .st-pill').forEach((btn) => {
    btn.addEventListener('click', () => {
      state.aspect = btn.dataset.aspect;
      renderLeftDynamic();
    });
  });

  container.querySelector('#st-style-select')?.addEventListener('change', (ev) => {
    state.style_id = ev.target.value;
  });
  container.querySelector('#st-steps-select')?.addEventListener('change', (ev) => {
    state.steps = Number(ev.target.value) || 4;
  });
  container.querySelector('#st-seed-input')?.addEventListener('input', (ev) => {
    state.seed = ev.target.value;
  });
  container.querySelector('#st-chk-desub')?.addEventListener('change', (ev) => {
    state.v2vOptions.desub = Boolean(ev.target.checked);
  });
  container.querySelector('#st-chk-paw')?.addEventListener('change', (ev) => {
    state.v2vOptions.paw_guard = Boolean(ev.target.checked);
  });
  container.querySelector('#st-chk-audio')?.addEventListener('change', (ev) => {
    state.v2vOptions.keep_audio = Boolean(ev.target.checked);
  });

  container.querySelector('#st-generate-btn')?.addEventListener('click', handleSubmit);

  // Initial render
  renderLeftDynamic();
  renderProgressCard();
  renderPlayerCard();
  renderHistoryGrid();
  renderSamplesStrip();

  // Live SSE updates + 2.5s active polling + 1s elapsed timer
  const onLiveEvent = () => {
    if (alive) pollTasks();
  };
  const unsub1 = ctx.store.subscribe('sse:job_progress', onLiveEvent);
  const unsub2 = ctx.store.subscribe('sse:cloud_queue_updated', onLiveEvent);
  const unsub3 = ctx.store.subscribe('sse:project_created', onLiveEvent);
  addCleanup(unsub1);
  addCleanup(unsub2);
  addCleanup(unsub3);

  const pollInterval = setInterval(() => {
    if (!alive) return;
    const hasActive = getMergedTasks().some((t) =>
      ['previewing', 'queued', 'queued_offline', 'rendering', 'assembling'].includes(t.overall_status)
    );
    if (hasActive || state.showLogs) {
      pollTasks();
    }
  }, 2500);
  addCleanup(() => clearInterval(pollInterval));

  const clockInterval = setInterval(() => {
    if (!alive) return;
    const el = container.querySelector('#st-elapsed-timer');
    const task = getSelectedTask();
    if (el && task?.created_at) {
      el.textContent = formatElapsed(task.created_at);
    }
  }, 1000);
  addCleanup(() => clearInterval(clockInterval));
}
