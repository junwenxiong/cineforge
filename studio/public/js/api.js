/**
 * CineForge Studio (影铸) — REST API Client, Reactive Store, SSE Events & UI Utilities
 */

const JSON_HEADERS = {
  'Content-Type': 'application/json',
  Accept: 'application/json',
};

export const colabNotebookUrl = '/api/farm/colab-notebook';

let _inviteCode = '';
try {
  if (typeof window !== 'undefined' && window.sessionStorage) {
    _inviteCode = window.sessionStorage.getItem('cineforge_invite_code') || '';
  }
} catch {
  _inviteCode = '';
}

export function getInviteCode() {
  return _inviteCode;
}

export function setInviteCode(code) {
  _inviteCode = code ? String(code).trim() : '';
  try {
    if (typeof window !== 'undefined' && window.sessionStorage) {
      if (_inviteCode) {
        window.sessionStorage.setItem('cineforge_invite_code', _inviteCode);
      } else {
        window.sessionStorage.removeItem('cineforge_invite_code');
      }
    }
  } catch {
    // ignore storage errors
  }
}

async function request(url, options = {}) {
  const { method = 'GET', body, headers = {}, raw = false } = options;
  const authHeaders = _inviteCode ? { 'X-Invite-Code': _inviteCode } : {};
  const fetchOpts = {
    method,
    cache: 'no-store',
    headers: raw
      ? { Accept: 'application/json', ...authHeaders, ...headers }
      : { ...JSON_HEADERS, ...authHeaders, ...headers },
  };

  if (body !== undefined) {
    fetchOpts.body = raw ? body : JSON.stringify(body);
  }

  const res = await fetch(url, fetchOpts);
  const contentType = res.headers.get('content-type') || '';
  let data = null;

  if (contentType.includes('application/json')) {
    try {
      data = await res.json();
    } catch {
      data = null;
    }
  } else {
    const text = await res.text();
    data = text ? { message: text } : null;
  }

  if (!res.ok) {
    const msg =
      (data && (data.error || data.detail || data.message)) ||
      `请求失败 (${res.status})`;
    const err = new Error(msg);
    err.status = res.status;
    err.data = data;
    throw err;
  }

  return data;
}

function buildQuery(params = {}) {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params || {})) {
    if (v !== undefined && v !== null && v !== '') {
      sp.set(k, String(v));
    }
  }
  const qs = sp.toString();
  return qs ? `?${qs}` : '';
}

export const api = {
  health() {
    return request('/api/health');
  },

  showcase() {
    return request('/api/showcase');
  },

  templates() {
    return request('/api/templates');
  },

  projects() {
    return request('/api/projects');
  },

  createProject(payload) {
    return request('/api/projects', { method: 'POST', body: payload });
  },

  projectDetail(id, params = {}) {
    const qs = buildQuery(params);
    return request(`/api/projects/${encodeURIComponent(id)}${qs}`);
  },

  updateShot(projectId, shotId, patch) {
    return request(
      `/api/projects/${encodeURIComponent(projectId)}/shots/${encodeURIComponent(shotId)}`,
      { method: 'PATCH', body: patch }
    );
  },

  retakeShot(projectId, shotId, body = {}) {
    return request(
      `/api/projects/${encodeURIComponent(projectId)}/shots/${encodeURIComponent(shotId)}/retake`,
      { method: 'POST', body }
    );
  },

  advanceStage(projectId, stage) {
    const body = typeof stage === 'string' ? { stage } : stage || {};
    return request(`/api/projects/${encodeURIComponent(projectId)}/advance-stage`, {
      method: 'POST',
      body,
    });
  },

  renderPreview(projectId) {
    return request(`/api/projects/${encodeURIComponent(projectId)}/render-preview`, {
      method: 'POST',
      body: {},
    });
  },

  dispatchCloud(projectId) {
    return request(`/api/projects/${encodeURIComponent(projectId)}/dispatch-cloud`, {
      method: 'POST',
      body: {},
    });
  },

  workflowPresets() {
    return request('/api/workflows/presets');
  },

  projectWorkflow(projectId, presetId = '') {
    const qs = presetId ? `?preset=${encodeURIComponent(presetId)}` : '';
    return request(`/api/projects/${encodeURIComponent(projectId)}/workflow${qs}`);
  },

  saveProjectWorkflow(projectId, workflow) {
    return request(`/api/projects/${encodeURIComponent(projectId)}/workflow`, {
      method: 'PUT',
      body: workflow,
    });
  },

  importProjectWorkflow(projectId, workflow) {
    return request(`/api/projects/${encodeURIComponent(projectId)}/workflow/import`, {
      method: 'POST',
      body: { workflow },
    });
  },

  runProjectWorkflow(projectId, workflow = null) {
    return request(`/api/projects/${encodeURIComponent(projectId)}/workflow/run`, {
      method: 'POST',
      body: workflow ? { workflow } : {},
    });
  },

  workflowExportUrl(projectId, format = 'comfyui') {
    return `/api/projects/${encodeURIComponent(projectId)}/workflow/export?format=${encodeURIComponent(format)}`;
  },

  uploadFile(file) {
    const filename = (file && file.name) || 'upload.bin';
    const contentType = (file && file.type) || 'application/octet-stream';
    return request(`/api/uploads?filename=${encodeURIComponent(filename)}`, {
      method: 'POST',
      body: file,
      raw: true,
      headers: {
        'Content-Type': contentType,
      },
    });
  },

  jobs() {
    return request('/api/jobs');
  },

  job(id) {
    return request(`/api/jobs/${encodeURIComponent(id)}`);
  },

  farmStatus() {
    return request('/api/farm/status');
  },

  session() {
    return request('/api/session');
  },

  queue(activeOnly = false) {
    return request(`/api/queue${activeOnly ? '?active=1' : ''}`);
  },

  tasks() {
    return request('/api/tasks');
  },

  queueJob(jobId) {
    return request(`/api/queue/${encodeURIComponent(jobId)}`);
  },

  cancelQueueJob(jobId) {
    return request(`/api/queue/${encodeURIComponent(jobId)}/cancel`, {
      method: 'POST',
      body: {},
    });
  },

  shareInfo() {
    return request('/api/share/info');
  },

  colabNotebookUrl,

  evaluations() {
    return request('/api/evaluations');
  },

  submitEvaluation(payload) {
    return request('/api/evaluations', { method: 'POST', body: payload });
  },
};

/* ==========================================================================
   Lightweight Reactive Cache + EventTarget Store
   ========================================================================== */
class StudioStore extends EventTarget {
  constructor() {
    super();
    this.state = {};
    this._timestamps = new Map();
    this._inflight = new Map();
  }

  get(key) {
    return this.state[key];
  }

  set(key, value) {
    this.state[key] = value;
    this._timestamps.set(key, Date.now());
    this.emit('change', { key, value });
    this.emit(`change:${key}`, value);
    return value;
  }

  delete(key) {
    delete this.state[key];
    this._timestamps.delete(key);
    this.emit('change', { key, value: undefined });
    this.emit(`change:${key}`, undefined);
  }

  invalidate(key) {
    if (key) {
      this._timestamps.delete(key);
    } else {
      this._timestamps.clear();
    }
  }

  async getOrFetch(key, fetcher, { force = false, ttlMs = 15000 } = {}) {
    const ts = this._timestamps.get(key) || 0;
    if (!force && key in this.state && Date.now() - ts < ttlMs) {
      return this.state[key];
    }
    if (!force && this._inflight.has(key)) {
      return this._inflight.get(key);
    }
    const promise = Promise.resolve()
      .then(fetcher)
      .then((val) => {
        this.set(key, val);
        return val;
      })
      .finally(() => {
        this._inflight.delete(key);
      });
    this._inflight.set(key, promise);
    return promise;
  }

  emit(type, detail) {
    this.dispatchEvent(new CustomEvent(type, { detail }));
  }

  subscribe(type, handler) {
    const wrapped = (ev) => handler(ev.detail, ev);
    this.addEventListener(type, wrapped);
    return () => this.removeEventListener(type, wrapped);
  }

  on(type, handler) {
    return this.subscribe(type, handler);
  }
}

export const store = new StudioStore();

/* ==========================================================================
   SSE Live Events Wrapper with Graceful Reconnect
   ========================================================================== */
const NAMED_SSE_EVENTS = [
  'project_created',
  'shot_updated',
  'stage_advanced',
  'job_progress',
  'dispatch_created',
  'cloud_queue_updated',
  'evaluation_added',
  'farm_status',
  'heartbeat',
  'ping',
];

export function connectEvents(onEvent) {
  let closed = false;
  let source = null;
  let retryTimer = null;
  let retryDelay = 2000;

  function safeParse(raw) {
    if (!raw) return {};
    try {
      return JSON.parse(raw);
    } catch {
      return { raw };
    }
  }

  function dispatch(type, rawData) {
    const data = safeParse(rawData);
    const resolvedType = (type === 'message' && data && data.type) ? data.type : type;
    if (resolvedType === 'ping' || resolvedType === 'heartbeat') {
      return;
    }
    const payload = { type: resolvedType, data };
    if (typeof onEvent === 'function') {
      try {
        onEvent(payload);
      } catch {
        // Isolate subscriber errors from SSE loop
      }
    }
    store.emit('sse', payload);
    store.emit(`sse:${resolvedType}`, data);
  }

  function open() {
    if (closed || typeof EventSource === 'undefined') return;
    try {
      source = new EventSource('/api/events');
    } catch {
      scheduleReconnect();
      return;
    }

    source.onopen = () => {
      retryDelay = 2000;
      store.set('sseConnected', true);
    };

    source.onmessage = (ev) => {
      dispatch('message', ev.data);
    };

    for (const evtName of NAMED_SSE_EVENTS) {
      source.addEventListener(evtName, (ev) => {
        dispatch(evtName, ev.data);
      });
    }

    source.onerror = () => {
      store.set('sseConnected', false);
      if (source) {
        try {
          source.close();
        } catch {
          // ignore
        }
        source = null;
      }
      if (!closed) {
        scheduleReconnect();
      }
    };
  }

  function scheduleReconnect() {
    if (closed || retryTimer) return;
    retryTimer = setTimeout(() => {
      retryTimer = null;
      open();
    }, retryDelay);
    retryDelay = Math.min(Math.round(retryDelay * 1.6), 15000);
  }

  open();

  return {
    close() {
      closed = true;
      if (retryTimer) {
        clearTimeout(retryTimer);
        retryTimer = null;
      }
      if (source) {
        try {
          source.close();
        } catch {
          // ignore
        }
        source = null;
      }
      store.set('sseConnected', false);
    },
  };
}

/* ==========================================================================
   UI Helpers: toast, escHtml, formatSec
   ========================================================================== */
const TOAST_ICONS = {
  info: '<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 16v-4M12 8h.01"/></svg>',
  success: '<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M8.5 12.5l2.3 2.3 4.7-4.8"/></svg>',
  warning: '<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.3 3.8L1.8 18.5A2 2 0 0 0 3.5 21.5h17a2 2 0 0 0 1.7-3L13.7 3.8a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/></svg>',
  error: '<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M15 9l-6 6M9 9l6 6"/></svg>',
};

export function toast(msg, type = 'info', duration = 3600) {
  if (typeof document === 'undefined') return;
  const root = document.getElementById('toast-root');
  if (!root) return;

  const safeType = TOAST_ICONS[type] ? type : 'info';
  const el = document.createElement('div');
  el.className = `toast-item toast-${safeType}`;
  el.setAttribute('role', 'status');
  el.innerHTML = `${TOAST_ICONS[safeType]}<span>${escHtml(msg)}</span>`;

  let removed = false;
  const dismiss = () => {
    if (removed) return;
    removed = true;
    el.classList.add('closing');
    setTimeout(() => el.remove(), 220);
  };

  el.addEventListener('click', dismiss);
  root.appendChild(el);

  while (root.children.length > 2) {
    root.firstElementChild.remove();
  }

  if (duration > 0) {
    setTimeout(dismiss, duration);
  }
}

export function escHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

export function formatSec(sec) {
  if (sec === null || sec === undefined || sec === '') return '--';
  const n = Number(sec);
  if (!Number.isFinite(n) || n < 0) return '--';

  if (n < 60) {
    const val = Number.isInteger(n) ? n : Number(n.toFixed(1));
    return `${val}秒`;
  }

  const totalSec = Math.round(n);
  const hours = Math.floor(totalSec / 3600);
  const mins = Math.floor((totalSec % 3600) / 60);
  const rem = totalSec % 60;

  if (hours > 0) {
    return rem > 0 ? `${hours}小时${mins}分${rem}秒` : `${hours}小时${mins}分`;
  }
  if (rem === 0) {
    return `${mins}分钟`;
  }
  return `${mins}分${String(rem).padStart(2, '0')}秒`;
}
