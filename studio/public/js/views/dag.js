// CineForge Studio — Lite ComfyUI Visual Workflow Editor + 6-Stage Production Topology
// Supports interactive node dragging, color-coded ComfyUI ports, live Bezier SVG wires,
// node bypass toggles, inline parameter editing, preset switching, ComfyUI JSON import/export,
// and 1-click "Queue Prompt" cloud dispatch, while preserving the 6-stage blueprint view.

const ICONS = {
  input: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>`,
  director: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="18" rx="2"/><path d="M7 3v18"/><path d="M17 3v18"/><path d="M2 9h5"/><path d="M17 9h5"/><path d="M2 15h5"/><path d="M17 15h5"/></svg>`,
  refs: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21"/></svg>`,
  render: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>`,
  qa: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/></svg>`,
  master: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>`,
};

const PORT_COLORS = {
  MODEL: '#a855f7',
  CLIP: '#f59e0b',
  VAE: '#ef4444',
  IMAGE: '#22c55e',
  VIDEO: '#06b6d4',
  AUDIO: '#f97316',
  CONDITIONING: '#3b82f6',
  LATENT: '#eab308',
  MASK: '#ec4899',
  ANY: '#94a3b8',
};

const CAT_LABELS = {
  loader: '模型加载',
  input: '素材输入',
  conditioning: '条件控制',
  sampler: '云端采样',
  post: '增强后处理',
  output: '成片输出',
};

function esc(val) {
  return String(val ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function statusLabel(status) {
  if (status === 'done') return '已完成';
  if (status === 'active') return '进行中';
  return '待执行';
}

function buildBlueprintNodes(detail) {
  const project = detail?.project || {};
  const isV2V = project.mode === 'v2v';
  const stages = Array.isArray(detail?.stages) ? detail.stages : [];
  const backendNodes = Array.isArray(detail?.dag?.nodes) ? detail.dag.nodes : [];
  const shots = Array.isArray(detail?.shots) ? detail.shots : [];
  const refs = Array.isArray(detail?.refs) ? detail.refs : [];
  const scenes = Array.isArray(detail?.scenes) ? detail.scenes : [];

  const totalShots = project.total_shots || shots.length || 0;
  const renderedShots = project.rendered_shots ?? shots.filter((s) => !!s.video_url || s.status === 'review' || s.status === 'approved').length;
  const approvedShots = project.approved_shots ?? shots.filter((s) => s.status === 'approved').length;
  const retakeCount = shots.filter((s) => s.status === 'retake').length;

  const stageByKey = new Map(stages.map((s) => [s.key, s]));
  const backendByStage = new Map();
  const backendById = new Map();
  backendNodes.forEach((n) => {
    if (n.stage) backendByStage.set(n.stage, n);
    if (n.id) backendById.set(n.id, n);
  });

  const defs = [
    {
      id: 'node_input',
      slot: 'dag-slot-input',
      step: '01',
      stage: 'script',
      icon: 'input',
      inPos: null,
      outPos: 'right',
      title: '用户输入节点',
      subtitle: isV2V
        ? '上传原片片段或精选名场面，指定替换主角与风格'
        : '一句话创意、片长与画幅目标，定义影片核心剧情',
      engine: isV2V ? 'V2V Source Cut' : 'Story Brief',
      metric: scenes.length ? `${scenes.length} 场戏` : `${totalShots} 镜构思`,
      desc: isV2V
        ? '自动解析原片分辨率、帧率与音频轨道，提取出干净的动作控制序列，为后续猫咪/3D 换角提供精准表演驱动。'
        : '将你的自然语言想法结构化为 CineForge 标准制片配置（film.json），零门槛启动电影级流水线。',
      inputs: isV2V ? '原片视频 (.mp4) + 换角角色指令 + 目标画幅' : '一句话创意 + 电影画风 + 目标片长 / 画幅',
      outputs: isV2V ? '标准化控制片段 + 原声音轨清单' : 'film.json 制片配置 + 场次剧情大纲',
      actionLabel: '查看剧本阶段',
    },
    {
      id: 'node_director',
      slot: 'dag-slot-director',
      step: '02',
      stage: 'storyboard',
      icon: 'director',
      inPos: 'left',
      outPos: 'right',
      title: 'AI 导演编剧节点',
      subtitle: isV2V
        ? '自动切镜分段、对齐台词节奏并规划每镜换角提示词'
        : '拆解场次节拍、景别运镜、台词与逐镜视频提示词',
      engine: 'CineForge Script',
      metric: `${totalShots} 镜分镜`,
      desc: isV2V
        ? '按画面切点拆分镜头并生成精确起止时间（cut_in / cut_out），保证每个镜头动作衔接丝滑且对口型。'
        : '模拟电影导演分镜思维，将整部短剧自动拆解为逐镜 JSON 卡片，每一镜都可以直接在看板中随时精修。',
      inputs: isV2V ? '原片切点 + 镜头时长 + 角色设定' : '剧情大纲 + 场次节拍 + 视觉锁 ID',
      outputs: 'shots/*.json 逐镜脚本（画面/运镜/台词/时长）',
      actionLabel: '打开逐镜看板',
    },
    {
      id: 'node_refs',
      slot: 'dag-slot-refs',
      step: '03',
      stage: 'refs',
      icon: 'refs',
      inPos: 'left',
      outPos: 'right',
      title: '视觉锁与定妆节点',
      subtitle: isV2V
        ? '锁定猫咪/动画主角定妆锚点，杜绝换角闪烁漂移'
        : '角色/场景参考图一致性锚点，保证全片主角不换脸',
      engine: 'Visual Lock',
      metric: `${refs.length} 张定妆锁`,
      desc: '核心防漂移机制：在拍摄前锁定主角与核心场景的高清参考图（visual_locks.json），所有云端分镜自动挂载同一锚点。',
      inputs: '用户上传参考图 / 风格定妆模板',
      outputs: 'visual_locks.json + refs.json 一致性锚点库',
      actionLabel: '查看角色定妆卡',
    },
    {
      id: 'node_render',
      slot: 'dag-slot-render',
      step: '04',
      stage: 'render',
      icon: 'render',
      inPos: 'left',
      outPos: 'bottom',
      title: 'Colab 云端多模型算力池',
      subtitle: isV2V
        ? 'Colab A100/H100/G4 · LTX-2.5 V2V IC-LoRA 换角渲染'
        : 'Colab A100/H100/G4 · MiniMax-H3 开源4步 / LTX-2.5 渲染',
      engine: isV2V ? 'LTX-2.5 V2V' : 'H3 / LTX-2.5',
      metric: `${renderedShots}/${totalShots} 镜已拍`,
      desc: '全部计算在 Google Colab 云端完成，支持 ComfyUI 节点流参数实时下发，单镜约 38~43 秒，成片自动回传本地 Web。',
      inputs: '逐镜分镜清单 + ComfyUI 工作流参数 + 视觉锁参考图',
      outputs: 'renders/<shot_id>/raw.mp4 原生逐镜成片',
      actionLabel: '派发云端精拍',
    },
    {
      id: 'node_qa',
      slot: 'dag-slot-qa',
      step: '05',
      stage: 'qa',
      icon: 'qa',
      inPos: 'top',
      outPos: 'right',
      title: '智能防穿帮质检',
      subtitle: isV2V
        ? '自动抹除原片字幕 / 护爪防穿帮 / 原声口型同步抽检'
        : '逐镜画面连续性、人物一致性与打回重拍闭环质检',
      engine: isV2V ? 'Desub + PawGuard' : 'Director QA',
      metric: retakeCount > 0 ? `${retakeCount} 镜待重拍` : `${approvedShots}/${totalShots} 镜过审`,
      desc: isV2V
        ? '针对真人换猫经典难题内置自动去字幕、护爪遮罩与口型检查；发现瑕疵可单镜打回重拍，无需整片重做。'
        : '在看板或抽屉内逐镜审片，一键标记过审或打回重拍并填写导演修改意见，精准控制成片质量。',
      inputs: '云端渲染样片 + 连续性 / 字幕 / 护爪检查规则',
      outputs: '过审镜头清单 + 精准单镜重拍指令',
      actionLabel: '去看板逐镜抽检',
    },
    {
      id: 'node_master',
      slot: 'dag-slot-master',
      step: '06',
      stage: 'master',
      icon: 'master',
      inPos: 'left',
      outPos: null,
      title: '电影母版精剪节点',
      subtitle: 'ffmpeg 帧级入出点精剪 / 配乐混音 / 自动烧录字幕成片',
      engine: 'FFmpeg Master',
      metric: project.final_video_url ? '电影母版就绪' : (project.preview_video_url ? '预演片就绪' : '随时可合成'),
      desc: '按照每个镜头设置的 cut_in / cut_out 剪点自动拼接转场、混入环境音效与配乐，一键导出高清 MP4 成片。',
      inputs: '过审分镜成片 + cut.json 精剪点 + 台词字幕 + 配乐',
      outputs: '1080p 电影级成片 / 即时可播放预演 MP4',
      actionLabel: '一键合成预演片',
    },
  ];

  return defs.map((def, idx) => {
    const st = stageByKey.get(def.stage);
    const bn = backendByStage.get(def.stage) || backendById.get(def.id) || backendNodes[idx];
    const status = bn?.status || st?.status || (idx === 0 ? 'done' : 'pending');
    return {
      ...def,
      backendId: bn?.id || def.id,
      status,
      engine: bn?.engine || def.engine,
      metric: bn?.metric || st?.metric || def.metric,
      tip: st?.tip || def.desc,
    };
  });
}

function buildBlueprintEdges(nodes, detail) {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const shots = Array.isArray(detail?.shots) ? detail.shots : [];
  const hasRetake = shots.some((s) => s.status === 'retake');

  const pairs = [
    { from: 'node_input', to: 'node_director', kind: 'main' },
    { from: 'node_input', to: 'node_refs', kind: 'main' },
    { from: 'node_director', to: 'node_render', kind: 'main' },
    { from: 'node_refs', to: 'node_render', kind: 'ref' },
    { from: 'node_render', to: 'node_qa', kind: 'main' },
    { from: 'node_qa', to: 'node_master', kind: 'main' },
  ];
  if (hasRetake) {
    pairs.push({ from: 'node_qa', to: 'node_render', kind: 'retake' });
  }
  return pairs.map((e) => {
    const src = byId.get(e.from);
    const dst = byId.get(e.to);
    const isDone = src?.status === 'done' && dst?.status === 'done';
    const isActive =
      e.kind === 'retake' ||
      (src?.status === 'done' && dst?.status === 'active') ||
      (src?.status === 'active');
    return { ...e, isDone, isActive };
  });
}

function drawBlueprintSvgEdges(canvasEl, svgEl, edges) {
  if (!canvasEl || !svgEl) return;
  const cRect = canvasEl.getBoundingClientRect();
  if (cRect.width < 20 || cRect.height < 20) return;

  svgEl.setAttribute('viewBox', `0 0 ${Math.round(cRect.width)} ${Math.round(cRect.height)}`);
  const paths = [];
  for (const edge of edges) {
    const fromNode = canvasEl.querySelector(`[data-dag-id="${edge.from}"]`);
    const toNode = canvasEl.querySelector(`[data-dag-id="${edge.to}"]`);
    if (!fromNode || !toNode) continue;

    if (edge.kind === 'retake') {
      const fr = fromNode.getBoundingClientRect();
      const tr = toNode.getBoundingClientRect();
      const x1 = fr.left - cRect.left + fr.width * 0.78;
      const y1 = fr.top - cRect.top;
      const x2 = tr.left - cRect.left + tr.width * 0.78;
      const y2 = tr.bottom - cRect.top;
      const d = `M ${x1} ${y1} C ${x1 + 26} ${y1 - 12}, ${x2 + 26} ${y2 + 12}, ${x2} ${y2}`;
      paths.push(`<path class="dag-edge-base is-retake" d="${d}" />`);
      continue;
    }

    const fBox = fromNode.getBoundingClientRect();
    const tBox = toNode.getBoundingClientRect();
    const sameColVertical =
      Math.abs((fBox.left + fBox.width / 2) - (tBox.left + tBox.width / 2)) < 80 &&
      tBox.top > fBox.bottom - 10;

    let d;
    if (sameColVertical) {
      const sx = fBox.left + fBox.width / 2 - cRect.left;
      const sy = fBox.bottom - cRect.top;
      const ex = tBox.left + tBox.width / 2 - cRect.left;
      const ey = tBox.top - cRect.top;
      const midY = (sy + ey) / 2;
      d = `M ${sx} ${sy} C ${sx} ${midY}, ${ex} ${midY}, ${ex} ${ey}`;
    } else {
      const fromPort = fromNode.querySelector('.dag-port-out') || fromNode;
      const toPort = toNode.querySelector('.dag-port-in') || toNode;
      const fr = fromPort.getBoundingClientRect();
      const tr = toPort.getBoundingClientRect();
      const x1 = fr.left + fr.width / 2 - cRect.left;
      const y1 = fr.top + fr.height / 2 - cRect.top;
      const x2 = tr.left + tr.width / 2 - cRect.left;
      const y2 = tr.top + tr.height / 2 - cRect.top;
      const dx = Math.max(46, Math.abs(x2 - x1) * 0.48);
      d = `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
    }
    const baseClass = edge.isDone ? 'is-done' : edge.isActive ? 'is-active' : '';
    paths.push(`<path class="dag-edge-base ${baseClass}" d="${d}" />`);
    if (edge.isActive || edge.isDone) {
      const flowTone = edge.isDone ? 'is-emerald' : edge.kind === 'ref' ? 'is-gold' : '';
      paths.push(`<path class="dag-edge-flow ${flowTone}" d="${d}" />`);
    }
  }
  svgEl.innerHTML = paths.join('');
}

function drawComfySvgEdges(stageEl, svgEl, workflow) {
  if (!stageEl || !svgEl || !workflow) return;
  const sRect = stageEl.getBoundingClientRect();
  const w = Math.max(stageEl.scrollWidth, Math.round(sRect.width), 1160);
  const h = Math.max(stageEl.scrollHeight, Math.round(sRect.height), 480);
  svgEl.setAttribute('viewBox', `0 0 ${w} ${h}`);
  svgEl.style.width = `${w}px`;
  svgEl.style.height = `${h}px`;

  const enabledMap = new Map((workflow.nodes || []).map((n) => [n.id, n.enabled !== false]));
  const paths = [];
  for (const edge of workflow.edges || []) {
    const fromPort = stageEl.querySelector(`[data-port-out="${CSS.escape(edge.from)}:${CSS.escape(edge.from_port)}"]`)
      || stageEl.querySelector(`[data-comfy-node="${CSS.escape(edge.from)}"]`);
    const toPort = stageEl.querySelector(`[data-port-in="${CSS.escape(edge.to)}:${CSS.escape(edge.to_port)}"]`)
      || stageEl.querySelector(`[data-comfy-node="${CSS.escape(edge.to)}"]`);
    if (!fromPort || !toPort) continue;

    const fr = fromPort.getBoundingClientRect();
    const tr = toPort.getBoundingClientRect();
    const x1 = fr.left - sRect.left + stageEl.scrollLeft + fr.width / 2;
    const y1 = fr.top - sRect.top + stageEl.scrollTop + fr.height / 2;
    const x2 = tr.left - sRect.left + stageEl.scrollLeft + tr.width / 2;
    const y2 = tr.top - sRect.top + stageEl.scrollTop + tr.height / 2;
    const dx = Math.max(54, Math.abs(x2 - x1) * 0.45);
    const d = `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
    const color = PORT_COLORS[edge.data_type] || PORT_COLORS.ANY;
    const active = enabledMap.get(edge.from) && enabledMap.get(edge.to);
    paths.push(
      `<path class="cf-wire ${active ? 'is-active' : 'is-bypass'}" d="${d}" stroke="${color}" />`
    );
  }
  svgEl.innerHTML = paths.join('');
}

export function renderDag(container, detail, callbacks = {}) {
  if (!container) return { destroy() {} };

  if (typeof container.__dagCleanup === 'function') {
    container.__dagCleanup();
    container.__dagCleanup = null;
  }

  const project = detail?.project || {};
  const projectId = project.id || '';
  const isV2V = project.mode === 'v2v';
  const api = callbacks.api || null;
  const toast = callbacks.toast || (() => {});
  const isWritable = String(projectId).startsWith('studio_') || project.source === 'studio';

  const bpNodes = buildBlueprintNodes(detail);
  const bpEdges = buildBlueprintEdges(bpNodes, detail);

  let viewMode = 'comfy'; // 'comfy' (Lite ComfyUI Flow) | 'blueprint' (6-Stage Topology)
  let bpSelectedId = (bpNodes.find((n) => n.status === 'active') || bpNodes[3] || bpNodes[0])?.id || 'node_input';
  let comfyWf = null;
  let comfySelectedId = null;
  let comfyLoading = Boolean(api && projectId);
  let comfyDirty = false;
  let comfyRunning = false;
  let dragState = null;

  const cleanupFns = [];

  async function loadComfyWorkflow(presetId = '') {
    if (!api || !projectId) {
      comfyLoading = false;
      render();
      return;
    }
    comfyLoading = true;
    render();
    try {
      const res = await api.projectWorkflow(projectId, presetId);
      comfyWf = res?.workflow || null;
      comfySelectedId = comfyWf?.nodes?.find((n) => n.category === 'sampler')?.id || comfyWf?.nodes?.[0]?.id || null;
      comfyDirty = Boolean(presetId);
    } catch (err) {
      toast(`加载 ComfyUI 节点流失败：${err?.message || '请重试'}`, 'error');
    } finally {
      comfyLoading = false;
      render();
    }
  }

  async function saveWorkflow({ silent = false } = {}) {
    if (!api || !projectId || !comfyWf) return false;
    if (!isWritable) {
      if (!silent) toast('示例影片为只读，请先去创作台新建项目或在右侧导出 ComfyUI JSON', 'info');
      return false;
    }
    try {
      const res = await api.saveProjectWorkflow(projectId, comfyWf);
      if (res?.workflow) {
        comfyWf = res.workflow;
        comfyDirty = false;
      }
      if (!silent) toast('✓ ComfyUI 节点流参数已保存', 'success');
      render();
      return true;
    } catch (err) {
      toast(`保存工作流失败：${err?.message || '请重试'}`, 'error');
      return false;
    }
  }

  async function runWorkflow() {
    if (!api || !projectId || !comfyWf || comfyRunning) return;
    if (!isWritable) {
      toast('示例影片只读；你可以导出此 ComfyUI JSON 或新建项目后直接运行', 'info');
      return;
    }
    comfyRunning = true;
    render();
    try {
      const res = await api.runProjectWorkflow(projectId, comfyWf);
      if (res?.workflow) comfyWf = res.workflow;
      comfyDirty = false;
      toast(`🚀 已按当前节点流（${(comfyWf.engine || 'h3').toUpperCase()}）派发至 Colab 算力队列！`, 'success');
      if (typeof callbacks.onWorkflowRan === 'function') callbacks.onWorkflowRan(res);
    } catch (err) {
      toast(`运行工作流失败：${err?.message || '请重试'}`, 'error');
    } finally {
      comfyRunning = false;
      render();
    }
  }

  async function handleImportJson(file) {
    if (!file || !api || !projectId) return;
    try {
      const text = await file.text();
      const parsed = JSON.parse(text);
      if (!isWritable) {
        toast('示例影片只读，无法覆盖导入；请在自建项目中使用导入功能', 'warning');
        return;
      }
      const res = await api.importProjectWorkflow(projectId, parsed);
      if (res?.workflow) {
        comfyWf = res.workflow;
        comfySelectedId = comfyWf.nodes?.[0]?.id || null;
        comfyDirty = false;
        toast(`✓ 已导入 ComfyUI 工作流（${comfyWf.nodes?.length || 0} 个节点）`, 'success');
        render();
      }
    } catch (err) {
      toast(`导入失败：${err?.message || '请检查是否为合法 JSON'}`, 'error');
    }
  }

  function renderBlueprintDetailCard(node) {
    if (!node) return '';
    return `
      <div class="dag-detail-head">
        <div class="dag-detail-title-row">
          <span class="wf-chip wf-chip-gold">节点 ${esc(node.step)}</span>
          <span class="dag-detail-title">${esc(node.title)}</span>
          <span class="wf-chip ${node.status === 'done' ? 'wf-chip-emerald' : node.status === 'active' ? 'wf-chip-cyan' : ''}">${esc(statusLabel(node.status))}</span>
          <span class="wf-chip">${esc(node.engine)}</span>
        </div>
        <div class="wf-stage-tip-actions">
          <button type="button" class="wf-btn wf-btn-gold wf-btn-sm" data-dag-action="${esc(node.stage)}">
            ${esc(node.actionLabel)} →
          </button>
        </div>
      </div>
      <p class="dag-detail-desc">${esc(node.desc)}</p>
      <div class="dag-io-grid">
        <div class="dag-io-box">
          <span class="dag-io-label">输入 · Inputs</span>
          <span class="dag-io-value">${esc(node.inputs)}</span>
        </div>
        <div class="dag-io-box">
          <span class="dag-io-label">输出 · Outputs</span>
          <span class="dag-io-value">${esc(node.outputs)}</span>
        </div>
        <div class="dag-io-box">
          <span class="dag-io-label">当前实测指标 · Live Metric</span>
          <span class="dag-io-value">${esc(node.metric)} · ${esc(node.engine)}</span>
        </div>
      </div>
    `;
  }

  function renderComfyInspector(node) {
    if (!node) {
      return `<div class="cf-insp-empty">点击画布中任意节点，查看并实时修改参数、开关旁路或拖动连线布局。</div>`;
    }
    const params = node.params || {};
    const paramEntries = Object.entries(params);
    return `
      <div class="dag-detail-head">
        <div class="dag-detail-title-row">
          <span class="wf-chip wf-chip-gold">${esc(CAT_LABELS[node.category] || node.category)}</span>
          <span class="dag-detail-title">${esc(node.title)}</span>
          <span class="wf-chip">${esc(node.type)}</span>
          <label class="cf-bypass-toggle">
            <input type="checkbox" data-comfy-toggle-enabled="${esc(node.id)}" ${node.enabled !== false ? 'checked' : ''} />
            <span>${node.enabled !== false ? '节点已启用' : '已旁路 (Bypass)'}</span>
          </label>
        </div>
        <div class="wf-stage-tip-actions">
          ${isWritable ? `
            <button type="button" class="wf-btn wf-btn-sm ${comfyDirty ? 'wf-btn-gold' : ''}" data-comfy-save>
              ${comfyDirty ? '● 保存节点改动' : '✓ 已同步'}
            </button>
          ` : `<span class="wf-chip">只读示例 · 可导出 JSON</span>`}
        </div>
      </div>
      ${paramEntries.length ? `
        <div class="cf-param-grid">
          ${paramEntries.map(([pk, pv]) => {
            const ptype = pv?.type || 'text';
            const label = pv?.label || pk;
            const val = pv?.value ?? '';
            if (ptype === 'select' && Array.isArray(pv.options)) {
              return `
                <label class="cf-param-field">
                  <span class="cf-param-label">${esc(label)}</span>
                  <select class="cf-param-input" data-comfy-param="${esc(pk)}">
                    ${pv.options.map((opt) => `<option value="${esc(opt)}" ${String(opt) === String(val) ? 'selected' : ''}>${esc(opt)}</option>`).join('')}
                  </select>
                </label>
              `;
            }
            if (ptype === 'boolean') {
              return `
                <label class="cf-param-field cf-param-check">
                  <input type="checkbox" data-comfy-param="${esc(pk)}" ${val ? 'checked' : ''} />
                  <span class="cf-param-label">${esc(label)}</span>
                </label>
              `;
            }
            if (ptype === 'textarea') {
              return `
                <label class="cf-param-field cf-param-wide">
                  <span class="cf-param-label">${esc(label)}</span>
                  <textarea class="cf-param-input cf-param-textarea" rows="2" data-comfy-param="${esc(pk)}">${esc(val)}</textarea>
                </label>
              `;
            }
            if (ptype === 'number') {
              const isSeed = pk === 'seed';
              return `
                <label class="cf-param-field">
                  <span class="cf-param-label">${esc(label)}</span>
                  <div class="cf-param-num-row">
                    <input
                      type="number"
                      class="cf-param-input"
                      data-comfy-param="${esc(pk)}"
                      value="${esc(val)}"
                      ${pv.min !== undefined ? `min="${esc(pv.min)}"` : ''}
                      ${pv.max !== undefined ? `max="${esc(pv.max)}"` : ''}
                      ${pv.step !== undefined ? `step="${esc(pv.step)}"` : ''}
                    />
                    ${isSeed ? `<button type="button" class="wf-btn wf-btn-sm" data-comfy-rand-seed title="随机种子">🎲</button>` : ''}
                  </div>
                </label>
              `;
            }
            return `
              <label class="cf-param-field">
                <span class="cf-param-label">${esc(label)}</span>
                <input type="text" class="cf-param-input" data-comfy-param="${esc(pk)}" value="${esc(val)}" />
              </label>
            `;
          }).join('')}
        </div>
      ` : `<p class="dag-detail-desc">该节点无可调参数，拖动节点标题栏可自由编排连线位置。</p>`}
    `;
  }

  function renderComfyView() {
    const presets = comfyWf?.presets || [];
    const nodes = comfyWf?.nodes || [];
    const selectedNode = nodes.find((n) => n.id === comfySelectedId) || nodes[0] || null;
    const exportComfyUrl = api && projectId ? api.workflowExportUrl(projectId, 'comfyui') : '#';

    return `
      <div class="cf-toolbar">
        <div class="cf-toolbar-left">
          <select class="cf-preset-select" data-comfy-preset aria-label="选择 ComfyUI 工作流模板">
            ${presets.map((p) => `
              <option value="${esc(p.id)}" ${p.id === comfyWf?.preset_id ? 'selected' : ''}>
                ${esc(p.name)}（${esc(p.badge)}）
              </option>
            `).join('')}
            ${comfyWf?.preset_id === 'custom' ? `<option value="custom" selected>自定义导入流 (${esc(comfyWf.name)})</option>` : ''}
          </select>
          <span class="wf-chip wf-chip-cyan">引擎：${esc((comfyWf?.engine || 'h3').toUpperCase())}</span>
          <span class="wf-chip">拖动节点自由排版 · 点击改参数</span>
        </div>
        <div class="cf-toolbar-actions">
          <label class="wf-btn wf-btn-sm" title="导入标准 ComfyUI JSON 或 CineForge 节点流">
            <input type="file" accept=".json,application/json" data-comfy-import style="display:none;" />
            <span>📥 导入 JSON</span>
          </label>
          <a href="${esc(exportComfyUrl)}" download="${esc(projectId)}_comfyui_workflow.json" class="wf-btn wf-btn-sm" data-comfy-export>
            <span>📤 导出 ComfyUI JSON</span>
          </a>
          <button type="button" class="wf-btn wf-btn-gold wf-btn-sm" data-comfy-run ${comfyRunning ? 'disabled' : ''}>
            <span>${comfyRunning ? '⏳ 派发中...' : '▶ Queue Prompt · 运行此流'}</span>
          </button>
        </div>
      </div>

      ${comfyLoading ? `
        <div class="dag-canvas cf-comfy-canvas" data-dag-canvas>
          <div class="cf-insp-empty">正在加载 Lite ComfyUI 节点流...</div>
        </div>
      ` : `
        <div class="dag-canvas cf-comfy-canvas" data-dag-canvas data-comfy-stage>
          <svg class="dag-edges-svg cf-wires-svg" data-dag-svg data-comfy-svg aria-hidden="true"></svg>
          <div class="cf-nodes-layer">
            ${nodes.map((n) => {
              const pPreview = Object.entries(n.params || {}).slice(0, 3);
              const bypassed = n.enabled === false;
              return `
                <div
                  class="dag-node cf-node cat-${esc(n.category)} ${n.id === comfySelectedId ? 'is-selected' : ''} ${bypassed ? 'is-bypassed' : ''}"
                  data-comfy-node="${esc(n.id)}"
                  data-dag-id="${esc(n.id)}"
                  style="left:${Number(n.x) || 40}px; top:${Number(n.y) || 40}px;"
                >
                  <div class="cf-node-head" data-comfy-drag="${esc(n.id)}">
                    <span class="cf-node-cat">${esc(CAT_LABELS[n.category] || n.category)}</span>
                    <span class="cf-node-title">${esc(n.title)}</span>
                    <span class="cf-node-badge">${bypassed ? 'BYPASS' : 'ON'}</span>
                  </div>
                  <div class="cf-node-ports">
                    <div class="cf-port-col cf-port-col-in">
                      ${(n.inputs || []).map((inp) => `
                        <div class="cf-port-row">
                          <span class="cf-dot" data-port-in="${esc(n.id)}:${esc(inp.name)}" style="background:${PORT_COLORS[inp.type] || PORT_COLORS.ANY};"></span>
                          <span>${esc(inp.name)}</span>
                        </div>
                      `).join('')}
                    </div>
                    <div class="cf-port-col cf-port-col-out">
                      ${(n.outputs || []).map((outp) => `
                        <div class="cf-port-row cf-port-row-out">
                          <span>${esc(outp.name)}</span>
                          <span class="cf-dot" data-port-out="${esc(n.id)}:${esc(outp.name)}" style="background:${PORT_COLORS[outp.type] || PORT_COLORS.ANY};"></span>
                        </div>
                      `).join('')}
                    </div>
                  </div>
                  ${pPreview.length ? `
                    <div class="cf-node-mini-params">
                      ${pPreview.map(([k, v]) => `
                        <div class="cf-mini-kv">
                          <span>${esc(v?.label || k)}</span>
                          <strong>${esc(typeof v?.value === 'boolean' ? (v.value ? '开' : '关') : String(v?.value ?? '').slice(0, 22) || '自动')}</strong>
                        </div>
                      `).join('')}
                    </div>
                  ` : ''}
                </div>
              `;
            }).join('')}
          </div>
        </div>
      `}

      <div class="dag-detail-card" data-dag-detail>
        ${renderComfyInspector(selectedNode)}
      </div>
    `;
  }

  function renderBlueprintView() {
    return `
      <div class="dag-canvas" data-dag-canvas>
        <svg class="dag-edges-svg" data-dag-svg aria-hidden="true"></svg>
        <div class="dag-grid">
          ${bpNodes.map((node) => `
            <button
              type="button"
              class="dag-node ${esc(node.slot)} status-${esc(node.status)} ${node.id === bpSelectedId ? 'is-selected' : ''}"
              data-dag-id="${esc(node.id)}"
              data-dag-stage="${esc(node.stage)}"
            >
              ${node.inPos ? `<span class="dag-port dag-port-in dag-port-${esc(node.inPos)}" aria-hidden="true"></span>` : ''}
              ${node.outPos ? `<span class="dag-port dag-port-out dag-port-${esc(node.outPos)}" aria-hidden="true"></span>` : ''}
              <div class="dag-node-top">
                <span class="dag-node-step">
                  <span class="dag-node-icon">${ICONS[node.icon] || ''}</span>
                  <span>NODE ${esc(node.step)}</span>
                </span>
                <span class="dag-node-status">${esc(statusLabel(node.status))}</span>
              </div>
              <div class="dag-node-title">${esc(node.title)}</div>
              <div class="dag-node-sub">${esc(node.subtitle)}</div>
              <div class="dag-node-foot">
                <span class="dag-node-engine" title="${esc(node.engine)}">${esc(node.engine)}</span>
                <span class="dag-node-metric">${esc(node.metric)}</span>
              </div>
            </button>
          `).join('')}
        </div>
      </div>

      <div class="dag-detail-card" data-dag-detail>
        ${renderBlueprintDetailCard(bpNodes.find((n) => n.id === bpSelectedId))}
      </div>
    `;
  }

  function redrawWires() {
    if (viewMode === 'comfy') {
      const stageEl = container.querySelector('[data-comfy-stage]');
      const svgEl = container.querySelector('[data-comfy-svg]');
      drawComfySvgEdges(stageEl, svgEl, comfyWf);
    } else {
      const canvasEl = container.querySelector('[data-dag-canvas]');
      const svgEl = container.querySelector('[data-dag-svg]');
      drawBlueprintSvgEdges(canvasEl, svgEl, bpEdges);
    }
  }

  function render() {
    container.innerHTML = `
      <div class="dag-wrap">
        <div class="dag-topbar">
          <div class="wf-meta-badges">
            <span class="wf-chip ${isV2V ? 'wf-chip-cyan' : 'wf-chip-gold'}">
              ${isV2V ? '🐱 V2V 经典换角流' : '🧩 Lite ComfyUI 可视化节点流'}
            </span>
            <div class="cf-mode-switch" role="tablist" aria-label="切换工作流视图">
              <button type="button" class="wf-btn wf-btn-sm ${viewMode === 'comfy' ? 'wf-btn-gold' : ''}" data-wf-submode="comfy">
                🧩 ComfyUI 节点流
              </button>
              <button type="button" class="wf-btn wf-btn-sm ${viewMode === 'blueprint' ? 'wf-btn-gold' : ''}" data-wf-submode="blueprint">
                🎬 6 步制片拓扑
              </button>
            </div>
          </div>
          <div class="dag-legend">
            <span class="dag-legend-item"><span class="dag-legend-dot done"></span>已完成 / ON</span>
            <span class="dag-legend-item"><span class="dag-legend-dot active"></span>当前运行</span>
            <span class="dag-legend-item"><span class="dag-legend-dot pending"></span>待执行 / BYPASS</span>
          </div>
        </div>

        ${viewMode === 'comfy' ? renderComfyView() : renderBlueprintView()}
      </div>
    `;

    requestAnimationFrame(() => {
      redrawWires();
      requestAnimationFrame(redrawWires);
    });
  }

  const onPointerMove = (e) => {
    if (!dragState || !comfyWf) return;
    const dx = e.clientX - dragState.startX;
    const dy = e.clientY - dragState.startY;
    const nx = Math.max(12, Math.min(1800, Math.round(dragState.origX + dx)));
    const ny = Math.max(12, Math.min(1000, Math.round(dragState.origY + dy)));
    dragState.node.x = nx;
    dragState.node.y = ny;
    dragState.el.style.left = `${nx}px`;
    dragState.el.style.top = `${ny}px`;
    comfyDirty = true;
    redrawWires();
  };

  const onPointerUp = () => {
    if (!dragState) return;
    dragState.el.classList.remove('is-dragging');
    dragState = null;
    if (comfyDirty && isWritable) {
      saveWorkflow({ silent: true });
    }
  };

  const onPointerDown = (e) => {
    const handle = e.target.closest('[data-comfy-drag]');
    if (!handle || !comfyWf) return;
    const nid = handle.dataset.comfyDrag;
    const node = (comfyWf.nodes || []).find((n) => n.id === nid);
    const el = handle.closest('[data-comfy-node]');
    if (!node || !el) return;
    e.preventDefault();
    comfySelectedId = nid;
    el.classList.add('is-dragging');
    dragState = {
      node,
      el,
      startX: e.clientX,
      startY: e.clientY,
      origX: Number(node.x) || 40,
      origY: Number(node.y) || 40,
    };
  };

  const onClick = (e) => {
    const modeBtn = e.target.closest('[data-wf-submode]');
    if (modeBtn) {
      viewMode = modeBtn.dataset.wfSubmode === 'blueprint' ? 'blueprint' : 'comfy';
      render();
      return;
    }

    if (e.target.closest('[data-comfy-save]')) {
      saveWorkflow();
      return;
    }

    if (e.target.closest('[data-comfy-run]')) {
      runWorkflow();
      return;
    }

    if (e.target.closest('[data-comfy-rand-seed]')) {
      const node = (comfyWf?.nodes || []).find((n) => n.id === comfySelectedId);
      if (node?.params?.seed) {
        node.params.seed.value = Math.floor(Math.random() * 2147483646) + 1;
        comfyDirty = true;
        render();
      }
      return;
    }

    const comfyNodeEl = e.target.closest('[data-comfy-node]');
    if (comfyNodeEl && viewMode === 'comfy') {
      const nid = comfyNodeEl.dataset.comfyNode;
      if (nid !== comfySelectedId) {
        comfySelectedId = nid;
        render();
      }
      return;
    }

    const actionBtn = e.target.closest('[data-dag-action]');
    if (actionBtn) {
      if (typeof callbacks.onAction === 'function') callbacks.onAction(actionBtn.dataset.dagAction);
      return;
    }

    const bpNodeEl = e.target.closest('[data-dag-id]');
    if (bpNodeEl && viewMode === 'blueprint') {
      const id = bpNodeEl.dataset.dagId;
      const node = bpNodes.find((n) => n.id === id);
      if (node) {
        bpSelectedId = id;
        render();
        if (typeof callbacks.onNodeSelect === 'function') callbacks.onNodeSelect(node);
      }
    }
  };

  const onChange = (e) => {
    const presetSel = e.target.closest('[data-comfy-preset]');
    if (presetSel) {
      const val = presetSel.value;
      if (val && val !== 'custom') {
        loadComfyWorkflow(val);
      }
      return;
    }

    const importInp = e.target.closest('[data-comfy-import]');
    if (importInp && importInp.files?.[0]) {
      handleImportJson(importInp.files[0]);
      importInp.value = '';
      return;
    }

    const toggleEl = e.target.closest('[data-comfy-toggle-enabled]');
    if (toggleEl && comfyWf) {
      const nid = toggleEl.dataset.comfyToggleEnabled;
      const node = (comfyWf.nodes || []).find((n) => n.id === nid);
      if (node) {
        node.enabled = Boolean(toggleEl.checked);
        comfyDirty = true;
        render();
      }
      return;
    }

    const paramEl = e.target.closest('[data-comfy-param]');
    if (paramEl && comfyWf) {
      const pk = paramEl.dataset.comfyParam;
      const node = (comfyWf.nodes || []).find((n) => n.id === comfySelectedId);
      if (node?.params?.[pk]) {
        const pdef = node.params[pk];
        if (pdef.type === 'boolean') pdef.value = Boolean(paramEl.checked);
        else if (pdef.type === 'number') pdef.value = Number(paramEl.value);
        else pdef.value = paramEl.value;
        comfyDirty = true;
        render();
      }
    }
  };

  const onWindowResize = () => redrawWires();

  container.addEventListener('pointerdown', onPointerDown);
  window.addEventListener('pointermove', onPointerMove);
  window.addEventListener('pointerup', onPointerUp);
  container.addEventListener('click', onClick);
  container.addEventListener('change', onChange);
  window.addEventListener('resize', onWindowResize);

  cleanupFns.push(() => {
    container.removeEventListener('pointerdown', onPointerDown);
    window.removeEventListener('pointermove', onPointerMove);
    window.removeEventListener('pointerup', onPointerUp);
    container.removeEventListener('click', onClick);
    container.removeEventListener('change', onChange);
    window.removeEventListener('resize', onWindowResize);
  });

  if (api && projectId) {
    loadComfyWorkflow();
  } else {
    viewMode = 'blueprint';
    render();
  }

  const cleanup = () => {
    while (cleanupFns.length) {
      try { cleanupFns.pop()(); } catch (_) {}
    }
  };
  container.__dagCleanup = cleanup;
  return { destroy: cleanup };
}
