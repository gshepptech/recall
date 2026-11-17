'use strict';

// ── Constants ──────────────────────────────────────────────────────
const RECALL_VERSION = '1.0.6';
const K_TOKEN   = 'recall_token';
const K_URL     = 'recall_url';
const K_PROJECT = 'recall_project';
const K_SIDEBAR_W  = 'recall_sidebar_w';
const K_ACTIVE_TAB = 'recall_active_tab';
const K_UI_PREFS   = 'recall_ui_prefs';
const DEFAULT_URL = 'http://localhost:8100/webhook/recall';
const DEFAULT_SIDEBAR_W = 260;
const MIN_SIDEBAR_W = 180;
const MAX_SIDEBAR_W = 640;

function loadUIPrefs() {
  try { return JSON.parse(localStorage.getItem(K_UI_PREFS) || '{}') || {}; }
  catch (e) { return {}; }
}
function saveUIPref(key, value) {
  const p = loadUIPrefs();
  p[key] = value;
  try { localStorage.setItem(K_UI_PREFS, JSON.stringify(p)); } catch (e) {}
}
function applySidebarWidth(w) {
  const n = Math.max(MIN_SIDEBAR_W, Math.min(MAX_SIDEBAR_W, Number(w) || DEFAULT_SIDEBAR_W));
  document.documentElement.style.setProperty('--sidebar-w', n + 'px');
  return n;
}

const TYPE_COLORS = {
  conversation:  '#888780',
  decision:      '#534AB7',
  prompt:        '#1D9E75',
  requirement:   '#185FA5',
  architecture:  '#BA7517',
  bug:           '#A32D2D',
  error:         '#FF6B6B',
  diary:         '#C77DA0',
  investigation: '#D4A017',
  reference:     '#5DADE2',
  mockup:        '#E8730C',
  skill:         '#58D68D',
  feedback:      '#4ECDC4',
  handoff:       '#9B59B6'
};

const PROJ_COLORS = {
  global:   '#534AB7',
  veltisai: '#1D9E75',
  molten8:  '#BA7517'
};

// ── State ──────────────────────────────────────────────────────────
const S = {
  token: '', url: DEFAULT_URL, project: 'global',
  role: 'viewer', projects: [], connected: false,
  activeTab: 'search',

  // search
  searchResults: [], searchSelected: null,
  searchLimit: 50, searchTotal: 0, searchQuery: '',
  searchPageSize: 50, searchLoading: false,

  // graph
  gNodes: [], gEdges: [],
  gT: { x: 0, y: 0, s: 1 },
  gDrag: null, gPan: false, gPanS: null,
  gHover: null, gSel: null, gAF: null,
  // Default-hide auto-logged diary/conversation entries; they dominate
  // the graph and drown out signal memories (decisions/prompts/requirements).
  // User can click the legend to toggle them back on.
  gHiddenTypes: new Set(['conversation']),
  gTypeCounts: {},
  // Sim cooling: gAlpha decays each tick; loop stops at < 0.005.
  // Caches avoid rebuilding nodeMap/activeSet every frame.
  gAlpha: 0, gNeedsDraw: false,
  gActive: [], gActiveSet: new Set(), gNodeMap: {},

  // prompts
  allPrompts: [], selPrompt: null,
  promptFilter: 'all', promptSort: 'last_run',
  promptHistory: [], promptHistoryStats: {},

  // requirements
  allReqs: [], selReq: null,
};

// ── Utilities ─────────────────────────────────────────────────────
function esc(v) {
  return String(v == null ? '' : v)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// SQLite stores dates as "YYYY-MM-DD HH:MM:SS" (space, no T, no Z).
// Without this, browsers parse them as local time → wrong age calculations.
function parseUTCDate(s) {
  if (!s) return new Date();
  // Normalize: space→T, then append Z if no tz offset present
  let n = String(s).replace(' ', 'T');
  if (!n.endsWith('Z') && !n.includes('+') && !/\d{2}:\d{2}$/.test(n.slice(-6).replace(/\d/g,''))) {
    // Simple check: if last char is a digit (no tz suffix), add Z
    if (/\d$/.test(n)) n += 'Z';
  }
  const d = new Date(n);
  return isNaN(d.getTime()) ? new Date() : d;
}

function fmtDate(v) {
  if (!v) return '';
  const d = parseUTCDate(v);
  if (isNaN(d)) return String(v);
  return d.toLocaleDateString('en-US', { month:'short', day:'numeric', year:'numeric' });
}

function daysAgo(v) {
  if (!v) return '';
  const diff = Date.now() - parseUTCDate(v).getTime();
  const days = Math.floor(diff / 86400000);
  if (days === 0) return 'today';
  if (days === 1) return '1d ago';
  return days + 'd ago';
}

function cmpVer(a, b) {
  const pa = a.split('.').map(Number);
  const pb = b.split('.').map(Number);
  for (let i = 0; i < 3; i++) {
    if ((pa[i]||0) > (pb[i]||0)) return 1;
    if ((pa[i]||0) < (pb[i]||0)) return -1;
  }
  return 0;
}

function typeColor(t) { return TYPE_COLORS[t] || '#888780'; }

function scoreColor(n) {
  if (n >= 70) return '#1D9E75';
  if (n >= 40) return '#BA7517';
  return '#A32D2D';
}

function typeBadge(t) {
  const c = typeColor(t);
  const bg = c + '26'; // ~15% opacity hex
  return `<span class="tbadge" style="background:${bg};color:${c};border:1px solid ${c}40">${esc(t || 'memory')}</span>`;
}

function statusPill(s) {
  const cls = 'spill spill-' + (s || 'active');
  return `<span class="${cls}">${esc(s || 'active')}</span>`;
}

// ── Markdown Renderer ─────────────────────────────────────────────
function inlineMd(text) {
  return esc(text)
    .replace(/\*\*([^*<>]+)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`<>]+)`/g, '<code>$1</code>');
}

function renderMd(raw) {
  if (!raw) return '';
  const lines = raw.split('\n');
  const out = [];
  let codeLines = null;

  for (const line of lines) {
    if (codeLines !== null) {
      if (line.startsWith('```')) {
        out.push('<pre><code>' + esc(codeLines.join('\n')) + '</code></pre>');
        codeLines = null;
      } else { codeLines.push(line); }
      continue;
    }
    if (line.startsWith('```')) { codeLines = []; continue; }
    if (line.startsWith('### ')) {
      out.push('<h3>' + inlineMd(line.slice(4)) + '</h3>');
    } else if (line.startsWith('## ')) {
      out.push('<h2>' + inlineMd(line.slice(3)) + '</h2>');
    } else if (line.startsWith('# ')) {
      out.push('<h1>' + inlineMd(line.slice(2)) + '</h1>');
    } else if (/^[*-] /.test(line)) {
      out.push('<li>' + inlineMd(line.slice(2)) + '</li>');
    } else if (line.trim() === '') {
      out.push('<br>');
    } else {
      out.push('<p>' + inlineMd(line) + '</p>');
    }
  }
  if (codeLines !== null) {
    out.push('<pre><code>' + esc(codeLines.join('\n')) + '</code></pre>');
  }
  let html = out.join('\n');
  html = html.replace(/(<li>.*<\/li>\n?)+/g, m => '<ul>' + m + '</ul>');
  return '<div class="mdr">' + html + '</div>';
}

// ── API ────────────────────────────────────────────────────────────

// Base URL without the /webhook/recall suffix
function baseUrl() {
  return (S.url || DEFAULT_URL).replace(/\/webhook\/recall\/?$/, '');
}

// GET to a dedicated /api/ui/* endpoint, cleaner than POST through webhook
async function apiGet(path, params = {}) {
  const qs = new URLSearchParams({ project: S.project, ...params }).toString();
  const url = baseUrl() + path + (qs ? '?' + qs : '');
  try {
    const res = await fetch(url, {
      headers: { 'Authorization': 'Bearer ' + S.token }
    });
    if (res.status === 401) { handle401(); return null; }
    if (res.status === 403) { await handle403(res); return null; }
    if (res.status >= 500) {
      showBanner('Server error. Check the logs.');
      return null;
    }
    if (!res.ok) {
      showBanner('Request failed: ' + res.status);
      return null;
    }
    return await res.json();
  } catch (e) {
    showBanner('Cannot reach ' + baseUrl() + '. Is the server running?');
    return null;
  }
}

// POST to /webhook/recall, still used for write operations and bootstrap
async function apiPost(command, extra = {}) {
  const url = S.url || DEFAULT_URL;
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer ' + S.token,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ command, project: S.project, ...extra })
    });
    if (res.status === 401) { handle401(); return null; }
    if (res.status === 403) { await handle403(res); return null; }
    if (res.status >= 500) {
      showBanner('Server error. Check: docker logs recall');
      return null;
    }
    if (!res.ok) {
      showBanner('Request failed: ' + res.status);
      return null;
    }
    return await res.json();
  } catch (e) {
    showBanner('Cannot reach ' + url + '. Is the server running?');
    return null;
  }
}

async function handle403(res) {
  let scope = null;
  try {
    const body = await res.json();
    scope = (body.detail && body.detail.project_scope) || null;
  } catch (_) {}

  if (scope) {
    showScopeBanner(scope);
  } else {
    showBanner('Access denied (403)');
  }
}

function showScopeBanner(scope) {
  const msg = `Your token is restricted to the ‘${scope}’ project.`;
  const el  = document.getElementById('error-banner');
  const msgEl = document.getElementById('error-banner-msg');
  // Inject a switch button alongside the message
  msgEl.innerHTML =
    `${esc(msg)} &nbsp;<button class="btn-secondary" id="scope-switch-btn"
      style="padding:3px 10px;font-size:11px;vertical-align:middle">
      Switch to ‘${esc(scope)}’
    </button>`;
  el.classList.add('visible');
  document.getElementById('scope-switch-btn').addEventListener('click', () => {
    S.project = scope;
    localStorage.setItem(K_PROJECT, scope);
    updateProjectPill();
    hideBanner();
    connect();
  });
}

// ── Who Are You ───────────────────────────────────────────────────
function handle401() {
  localStorage.removeItem(K_TOKEN);
  localStorage.removeItem(K_URL);
  localStorage.removeItem(K_PROJECT);
  S.token = ''; S.connected = false;
  showWhoAreYou();
}

async function showWhoAreYou() {
  const overlay = document.getElementById('who-are-you');
  const list    = document.getElementById('way-user-list');
  overlay.classList.add('visible');
  list.innerHTML = '<div style="font-size:12px;color:var(--tmuted);padding:6px 0">Loading…</div>';

  let users = [];
  try {
    const res = await fetch('/api/ui/users');
    if (res.ok) users = await res.json();
  } catch (_) {}

  list.innerHTML = '';
  if (!users.length) {
    list.innerHTML = '<div style="font-size:12px;color:var(--tmuted);padding:6px 0">No users found. Use the Advanced option below.</div>';
  }

  users.forEach(u => {
    const label = u.label || '';

    const btn = document.createElement('button');
    btn.className = 'way-user-btn';
    btn.textContent = label;

    const inline = document.createElement('div');
    inline.className = 'way-inline';
    inline.innerHTML = `
      <input type="password" placeholder="Paste your token for ${esc(label)}" autocomplete="current-password">
      <div class="way-inline-err"></div>
      <button class="btn-primary" style="align-self:flex-start">Connect</button>
    `;

    btn.addEventListener('click', () => {
      list.querySelectorAll('.way-user-btn').forEach(b => b.classList.remove('selected'));
      list.querySelectorAll('.way-inline').forEach(d => d.classList.remove('open'));
      btn.classList.add('selected');
      inline.classList.add('open');
      inline.querySelector('input').focus();
    });

    const confirmBtn = inline.querySelector('button');
    const tokenInput = inline.querySelector('input');
    const errEl      = inline.querySelector('.way-inline-err');

    async function tryConnect() {
      const tok = tokenInput.value.trim();
      if (!tok) { errEl.textContent = 'Paste your token first'; return; }
      errEl.textContent = '';
      confirmBtn.disabled = true;
      confirmBtn.textContent = 'Checking…';
      try {
        const r = await fetch('/api/ui/bootstrap', {
          headers: { 'Authorization': 'Bearer ' + tok }
        });
        if (r.status === 401) {
          errEl.textContent = 'Wrong token. Try again.';
          tokenInput.value = '';
          tokenInput.focus();
        } else if (r.ok) {
          const info = await r.json();
          const derivedUrl = window.location.origin + '/webhook/recall';
          S.url = derivedUrl;
          S.token = tok;
          if (info.project_scope) {
            S.project = info.project_scope;
            localStorage.setItem(K_PROJECT, info.project_scope);
          }
          localStorage.setItem(K_TOKEN, tok);
          localStorage.setItem(K_URL,   derivedUrl);
          hideWhoAreYou();
          connect();
        } else {
          errEl.textContent = 'Server error (' + r.status + ')';
        }
      } catch (_) {
        errEl.textContent = 'Cannot reach server';
      }
      confirmBtn.disabled = false;
      confirmBtn.textContent = 'Connect';
    }

    confirmBtn.addEventListener('click', tryConnect);
    tokenInput.addEventListener('keydown', e => { if (e.key === 'Enter') tryConnect(); });

    list.appendChild(btn);
    list.appendChild(inline);
  });

  // Advanced path
  const advSubmit = document.getElementById('way-adv-submit');
  const advInput  = document.getElementById('way-adv-token');
  const advErr    = document.getElementById('way-adv-err');

  const newSubmit = advSubmit.cloneNode(true);
  advSubmit.replaceWith(newSubmit);

  async function tryAdvConnect() {
    const tok = advInput.value.trim();
    if (!tok) { advErr.textContent = 'Paste a token first'; return; }
    advErr.textContent = '';
    newSubmit.disabled = true;
    newSubmit.textContent = 'Checking…';
    try {
      const r = await fetch('/api/ui/bootstrap', {
        headers: { 'Authorization': 'Bearer ' + tok }
      });
      if (r.status === 401) {
        advErr.textContent = 'Token rejected';
        advInput.value = '';
        advInput.focus();
      } else if (r.ok) {
        const info = await r.json();
        const derivedUrl = window.location.origin + '/webhook/recall';
        S.url = derivedUrl;
        S.token = tok;
        if (info.project_scope) {
          S.project = info.project_scope;
          localStorage.setItem(K_PROJECT, info.project_scope);
        }
        localStorage.setItem(K_TOKEN, tok);
        localStorage.setItem(K_URL,   derivedUrl);
        hideWhoAreYou();
        connect();
      } else {
        advErr.textContent = 'Server error (' + r.status + ')';
      }
    } catch (_) {
      advErr.textContent = 'Cannot reach server';
    }
    newSubmit.disabled = false;
    newSubmit.textContent = 'Connect';
  }

  newSubmit.addEventListener('click', tryAdvConnect);
  advInput.addEventListener('keydown', e => { if (e.key === 'Enter') tryAdvConnect(); });
}

function hideWhoAreYou() {
  document.getElementById('who-are-you').classList.remove('visible');
  document.getElementById('way-user-list').innerHTML = '';
  document.getElementById('way-adv-token').value = '';
  document.getElementById('way-adv-err').textContent = '';
  const adv = document.getElementById('way-advanced');
  if (adv) adv.removeAttribute('open');
}

// ── Error Banner ──────────────────────────────────────────────────
function showBanner(msg) {
  const el = document.getElementById('error-banner');
  document.getElementById('error-banner-msg').textContent = msg;
  el.classList.add('visible');
}
function hideBanner() {
  document.getElementById('error-banner').classList.remove('visible');
}

// ── Connection Status ─────────────────────────────────────────────
function setConnected(on) {
  S.connected = on;
  document.getElementById('conn-dot').classList.toggle('on', on);
  document.getElementById('conn-label').textContent = on ? 'connected' : 'disconnected';
}

function updateProjectPill() {
  const p = S.project;
  document.getElementById('project-name-disp').textContent = p;
  const dot = document.getElementById('project-dot');
  dot.style.background = PROJ_COLORS[p] || '#888780';
}

// ── Settings Panel ────────────────────────────────────────────────
function openGear() {
  document.getElementById('settings-panel').classList.add('open');
}
function closeGear() {
  document.getElementById('settings-panel').classList.remove('open');
}
function toggleGear() {
  document.getElementById('settings-panel').classList.toggle('open');
}

function renderProjSelector(projects, role) {
  const wrap = document.getElementById('proj-selector');
  if (projects.length > 0) {
    const items = projects.map(p => {
      const checked = p === S.project ? 'checked' : '';
      return `<label><input type="radio" name="proj-radio" value="${esc(p)}" ${checked}><span>${esc(p)}</span></label>`;
    }).join('');
    wrap.innerHTML = `<div class="proj-checkboxes">${items}</div>`;
    wrap.querySelectorAll('input[name="proj-radio"]').forEach(r => {
      r.addEventListener('change', () => {
        S.project = r.value;
        localStorage.setItem(K_PROJECT, S.project);
        updateProjectPill();
        closeGear();
        refreshTokenTotals();
        reloadActiveTab();
      });
    });
  } else {
    wrap.innerHTML = `<input type="text" id="s-project" placeholder="global" value="${esc(S.project)}">`;
  }
}

// ── Tab Switching ─────────────────────────────────────────────────
function switchTab(name) {
  S.activeTab = name;
  try { localStorage.setItem(K_ACTIVE_TAB, name); } catch (e) {}
  document.querySelectorAll('.tab-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.tab === name);
  });
  document.querySelectorAll('.tab-view').forEach(v => {
    v.classList.remove('active');
  });
  const view = document.getElementById('view-' + name);
  if (view) view.classList.add('active');

  if (name === 'graph') {
    startGraphTab();
  } else {
    stopGraphSim();
  }
}

function reloadActiveTab() {
  if (!S.connected) return;
  switch (S.activeTab) {
    case 'search':      loadSearch(document.getElementById('search-query').value || '*'); break;
    case 'graph':       loadGraph(); break;
    case 'prompts':     loadPrompts(); break;
    case 'requirements': loadRequirements(); break;
  }
}

// ── Connect / Init ────────────────────────────────────────────────
async function connect() {
  if (!S.token) { openGear(); return; }
  hideBanner();
  document.getElementById('token-error').textContent = '';

  // Bootstrap: get role + project list directly from server (no webhook dispatch)
  const info = await apiGet('/api/ui/bootstrap');
  if (!info) return;

  S.role     = info.role     || 'viewer';
  S.projects = info.projects || [];
  if (info.project_scope) {
    S.project = info.project_scope;
    localStorage.setItem(K_PROJECT, info.project_scope);
  }

  setConnected(true);
  updateProjectPill();

  // Update selector if owner
  renderProjSelector(S.projects, S.role);

  closeGear();

  // Fetch server version from /health (no auth required) and show update indicator
  try {
    const base = (S.url || DEFAULT_URL).replace(/\/webhook\/recall\/?$/, '');
    const hres = await fetch(base + '/health');
    if (hres.ok) {
      const h = await hres.json();
      const el = document.getElementById('server-version');
      if (h.version) {
        const current = h.version.replace(/^v/, '');
        const latest  = (h.latest_version || '').replace(/^v/, '');
        el.textContent = 'v' + current;
        if (latest && cmpVer(latest, current) > 0) {
          el.classList.add('outdated');
          el.title = 'Update available: v' + latest;
          el.textContent = 'v' + current + ' → v' + latest;
        }
      }
    }
  } catch (_) {}

  // Refresh token totals pill (topbar)
  refreshTokenTotals();

  // Load current tab
  reloadActiveTab();
}

// ── Token Totals (topbar pill) ─────────────────────────────────────
function fmtTok(n) {
  n = Number(n) || 0;
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'k';
  return n.toString();
}

async function refreshTokenTotals() {
  // /api/ui/runs returns stats aggregated under the current project scope.
  const res = await apiGet('/api/ui/runs', { limit: 1 });
  if (!res || !res.stats) return;
  const s = res.stats;
  const pill = document.getElementById('token-pill');
  if (!pill) return;
  document.getElementById('tp-in').textContent    = 'in ' + fmtTok(s.sum_in);
  document.getElementById('tp-cache').textContent = 'cached ' + fmtTok(s.sum_cache_read);
  document.getElementById('tp-out').textContent   = 'out ' + fmtTok(s.sum_out);
  pill.title = (Number(s.run_count)||0) + ' runs · total '
             + fmtTok((Number(s.sum_in)||0) + (Number(s.sum_out)||0) + (Number(s.sum_cache_read)||0))
             + ' tokens';
  pill.style.display = 'flex';
}
