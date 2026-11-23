// CineForge Studio — Visual Workflow Topology DAG Canvas
// Interactive obsidian node-graph with DOM-measured animated cubic Bezier SVG connectors

const ICONS = {
  input: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>`,
  director: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="18" rx="2"/><path d="M7 3v18"/><path d="M17 3v18"/><path d="M2 9h5"/><path d="M17 9h5"/><path d="M2 15h5"/><path d="M17 15h5"/></svg>`,
  refs: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21"/></svg>`,
  render: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>`,
  qa: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/></svg>`,
  master: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>`,
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
      title: '低成本云端算力池',
      subtitle: isV2V
        ? 'Colab G4/H100 分布式农场 · LTX-2.5 V2V IC-LoRA 换角渲染'
        : 'Colab G4/H100 分布式农场 · MiniMax H3 / LTX-2.5 逐镜渲染',
      engine: isV2V ? 'LTX-2.5 V2V' : 'H3 / LTX-2.5',
      metric: `${renderedShots}/${totalShots} 镜已拍`,
      desc: '将分镜清单自动派发给闲置/低价 Colab GPU 农场并行拍摄，单镜仅约 38~43 秒，30 分钟长片实测约 $11（每分钟 ≈ ¥2.4）。',
      inputs: '逐镜分镜清单 + 视觉锁参考图 + 控制视频',
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
      subtitle: 'ffmpeg 帧级入出点精剪 / CC0 实录配乐 / 自动烧录字幕成片',
      engine: 'FFmpeg Master',
      metric: project.final_video_url ? '电影母版就绪' : (project.preview_video_url ? '预演片就绪' : '随时可合成'),
      desc: '按照你在每个镜头设置的 cut_in / cut_out 剪点自动拼接转场、混入环境音效与配乐，一键导出高清 MP4 成片。',
      inputs: '过审分镜成片 + cut.json 精剪点 + 台词字幕 + 配乐',
      outputs: '1080p 电影级成片 / 即时可播放预演 MP4',
      actionLabel: '一键合成预演片',
    },
  ];

  // Merge backend stage & dag metadata gracefully
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

function drawSvgEdges(canvasEl, svgEl, edges) {
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
      // Curved feedback loop on the right side from QA back up to Render
      const fr = fromNode.getBoundingClientRect();
      const tr = toNode.getBoundingClientRect();
      const x1 = fr.left - cRect.left + fr.width * 0.78;
      const y1 = fr.top - cRect.top;
      const x2 = tr.left - cRect.left + tr.width * 0.78;
      const y2 = tr.bottom - cRect.top;
      const bulge = 26;
      const d = `M ${x1} ${y1} C ${x1 + bulge} ${y1 - 12}, ${x2 + bulge} ${y2 + 12}, ${x2} ${y2}`;
      paths.push(`<path class="dag-edge-base is-retake" d="${d}" />`);
      continue;
    }

    const fBox = fromNode.getBoundingClientRect();
    const tBox = toNode.getBoundingClientRect();
    const sameColVertical =
      Math.abs((fBox.left + fBox.width / 2) - (tBox.left + tBox.width / 2)) < 80 &&
      tBox.top > fBox.bottom - 10;

    // Same-column vertical flow (node_render bottom-center -> node_qa top-center)
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

export function renderDag(container, detail, callbacks = {}) {
  if (!container) return { destroy() {} };

  if (typeof container.__dagCleanup === 'function') {
    container.__dagCleanup();
    container.__dagCleanup = null;
  }

  const project = detail?.project || {};
  const isV2V = project.mode === 'v2v';
  const nodes = buildBlueprintNodes(detail);
  const edges = buildBlueprintEdges(nodes, detail);

  const defaultSelected = nodes.find((n) => n.status === 'active') || nodes[3] || nodes[0];
  let selectedId = defaultSelected?.id || 'node_input';

  function renderDetailCard(node) {
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

  container.innerHTML = `
    <div class="dag-wrap">
      <div class="dag-topbar">
        <div class="wf-meta-badges">
          <span class="wf-chip ${isV2V ? 'wf-chip-cyan' : 'wf-chip-gold'}">
            ${isV2V ? '🐱 V2V 经典换角拓扑' : '🎬 原创电影制片拓扑'}
          </span>
          <span class="wf-chip">6 大自动编排节点 · 点击任意节点查看输入/输出与快捷操作</span>
        </div>
        <div class="dag-legend">
          <span class="dag-legend-item"><span class="dag-legend-dot done"></span>已完成</span>
          <span class="dag-legend-item"><span class="dag-legend-dot active"></span>当前运行</span>
          <span class="dag-legend-item"><span class="dag-legend-dot pending"></span>待执行</span>
        </div>
      </div>

      <div class="dag-canvas" data-dag-canvas>
        <svg class="dag-edges-svg" data-dag-svg aria-hidden="true"></svg>
        <div class="dag-grid">
          ${nodes.map((node) => `
            <button
              type="button"
              class="dag-node ${esc(node.slot)} status-${esc(node.status)} ${node.id === selectedId ? 'is-selected' : ''}"
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
        ${renderDetailCard(nodes.find((n) => n.id === selectedId))}
      </div>
    </div>
  `;

  const canvasEl = container.querySelector('[data-dag-canvas]');
  const svgEl = container.querySelector('[data-dag-svg]');
  const detailEl = container.querySelector('[data-dag-detail]');

  const redraw = () => drawSvgEdges(canvasEl, svgEl, edges);
  const rafId = requestAnimationFrame(() => {
    redraw();
    // Second pass after webfont/layout settle
    requestAnimationFrame(redraw);
  });

  let resizeObserver = null;
  if (typeof ResizeObserver !== 'undefined' && canvasEl) {
    resizeObserver = new ResizeObserver(() => redraw());
    resizeObserver.observe(canvasEl);
  }
  const onWindowResize = () => redraw();
  window.addEventListener('resize', onWindowResize);

  const onClick = (e) => {
    const actionBtn = e.target.closest('[data-dag-action]');
    if (actionBtn) {
      const stageKey = actionBtn.dataset.dagAction;
      if (typeof callbacks.onAction === 'function') {
        callbacks.onAction(stageKey);
      }
      return;
    }

    const nodeEl = e.target.closest('[data-dag-id]');
    if (!nodeEl) return;
    const id = nodeEl.dataset.dagId;
    const node = nodes.find((n) => n.id === id);
    if (!node) return;

    selectedId = id;
    container.querySelectorAll('.dag-node').forEach((el) => {
      el.classList.toggle('is-selected', el.dataset.dagId === id);
    });
    if (detailEl) {
      detailEl.innerHTML = renderDetailCard(node);
    }
    if (typeof callbacks.onNodeSelect === 'function') {
      callbacks.onNodeSelect(node);
    }
  };

  container.addEventListener('click', onClick);

  const cleanup = () => {
    cancelAnimationFrame(rafId);
    if (resizeObserver) resizeObserver.disconnect();
    window.removeEventListener('resize', onWindowResize);
    container.removeEventListener('click', onClick);
  };

  container.__dagCleanup = cleanup;
  return { destroy: cleanup };
}
