'use strict';

// ── Event Listeners ───────────────────────────────────────────────

// Gear
document.getElementById('gear-btn').addEventListener('click', e => {
  e.stopPropagation();
  toggleGear();
});
document.addEventListener('click', e => {
  const panel = document.getElementById('settings-panel');
  if (!panel.contains(e.target) && e.target !== document.getElementById('gear-btn')) {
    closeGear();
  }
});

// Settings Save
document.getElementById('s-save').addEventListener('click', () => {
  const token = document.getElementById('s-token').value.trim();
  const url   = document.getElementById('s-url').value.trim();
  const projEl = document.getElementById('s-project');
  const proj  = projEl ? projEl.value.trim() : S.project;

  if (!token) { document.getElementById('token-error').textContent = 'Token is required'; return; }
  document.getElementById('token-error').textContent = '';

  S.token   = token;
  S.url     = url || DEFAULT_URL;
  S.project = proj || 'global';

  localStorage.setItem(K_TOKEN,   S.token);
  localStorage.setItem(K_URL,     S.url);
  localStorage.setItem(K_PROJECT, S.project);

  updateProjectPill();
  connect();
});

// Settings Clear
document.getElementById('s-clear').addEventListener('click', () => {
  localStorage.removeItem(K_TOKEN);
  localStorage.removeItem(K_URL);
  localStorage.removeItem(K_PROJECT);
  S.token = ''; S.url = DEFAULT_URL; S.project = 'global';
  S.connected = false; S.role = 'viewer'; S.projects = [];
  setConnected(false);
  updateProjectPill();
  document.getElementById('s-token').value = '';
  document.getElementById('s-url').value = '';
  // Reset lists
  document.getElementById('search-list').innerHTML   = '<div class="empty-msg">Connect to search memories.</div>';
  document.getElementById('prompts-list').innerHTML  = '<div class="empty-msg">Connect to load prompts.</div>';
  document.getElementById('req-list').innerHTML      = '<div class="empty-msg">Connect to load requirements.</div>';
  document.getElementById('search-detail').innerHTML  = '<div class="detail-empty"><span>Select a memory to view details</span></div>';
  document.getElementById('prompts-detail').innerHTML = '<div class="detail-empty"><span>Select a prompt to view details</span></div>';
  document.getElementById('req-detail').innerHTML     = '<div class="detail-empty"><span>Select a requirement to view details</span></div>';
  S.gNodes = []; S.gEdges = [];
  stopGraphSim();
});

// Tabs
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    if (!S.connected && btn.dataset.tab !== 'search') {
      // still allow tab switch, just won't have data
    }
    switchTab(btn.dataset.tab);
    if (S.connected) reloadActiveTab();
  });
});

// Search
const searchQ = document.getElementById('search-query');
searchQ.addEventListener('keydown', e => {
  if (e.key === 'Enter') { saveUIPref('searchQuery', searchQ.value); loadSearch(searchQ.value.trim()); }
});
searchQ.addEventListener('input', () => {
  saveUIPref('searchQuery', searchQ.value);
  if (searchQ.value === '') loadSearch('*');
});
document.getElementById('filter-type').addEventListener('change', e => {
  saveUIPref('filterType', e.target.value);
  loadSearch(searchQ.value || '*');
});
document.getElementById('filter-status').addEventListener('change', e => {
  saveUIPref('filterStatus', e.target.value);
  loadSearch(searchQ.value || '*');
});

// Prompts filter
document.querySelectorAll('#prompts-filter-grp .toggle-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('#prompts-filter-grp .toggle-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    S.promptFilter = btn.dataset.pf;
    saveUIPref('promptFilter', S.promptFilter);
    renderPromptsSidebar();
  });
});
document.getElementById('prompts-sort').addEventListener('change', e => {
  S.promptSort = e.target.value;
  saveUIPref('promptSort', S.promptSort);
  renderPromptsSidebar();
});
document.getElementById('prompts-query').addEventListener('input', e => {
  saveUIPref('promptsQuery', e.target.value);
  renderPromptsSidebar();
});

// Requirements filters
document.getElementById('req-status').addEventListener('change', e => {
  saveUIPref('reqStatus', e.target.value);
  renderReqSidebar();
});
document.getElementById('req-sort').addEventListener('change', e => {
  saveUIPref('reqSort', e.target.value);
  renderReqSidebar();
});

// ── Resizable sidebar ─────────────────────────────────────────────
document.querySelectorAll('.resizer').forEach(r => {
  r.addEventListener('mousedown', e => {
    e.preventDefault();
    const view = r.closest('.tab-view');
    if (!view) return;
    const sb = view.querySelector('.sidebar');
    if (!sb) return;
    const startX = e.clientX;
    const startW = sb.getBoundingClientRect().width;
    r.classList.add('dragging');
    document.body.classList.add('resizing');
    const onMove = ev => {
      const w = applySidebarWidth(startW + (ev.clientX - startX));
      r.dataset.pendingW = w;
    };
    const onUp = () => {
      r.classList.remove('dragging');
      document.body.classList.remove('resizing');
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      const w = r.dataset.pendingW;
      if (w) { try { localStorage.setItem(K_SIDEBAR_W, w); } catch (e) {} }
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  });
  r.addEventListener('dblclick', () => {
    const w = applySidebarWidth(DEFAULT_SIDEBAR_W);
    try { localStorage.setItem(K_SIDEBAR_W, String(w)); } catch (e) {}
  });
});

// Dismiss error banner
document.getElementById('dismiss-error').addEventListener('click', hideBanner);

// Resize: redraw graph if visible
window.addEventListener('resize', () => {
  if (S.activeTab === 'graph') startGraphTab();
});

// ── Init ──────────────────────────────────────────────────────────
(function init() {
  const token   = localStorage.getItem(K_TOKEN) || '';
  const url     = localStorage.getItem(K_URL)   || DEFAULT_URL;
  const project = localStorage.getItem(K_PROJECT) || 'global';

  document.getElementById('s-token').value   = token;
  document.getElementById('s-url').value     = url;

  S.token   = token;
  S.url     = url;
  S.project = project;

  updateProjectPill();

  // Restore sidebar width
  applySidebarWidth(localStorage.getItem(K_SIDEBAR_W) || DEFAULT_SIDEBAR_W);

  // Restore filter inputs from UI prefs (applied before connect so first loads use them)
  const prefs = loadUIPrefs();
  const setVal = (id, v) => { if (v != null) { const el = document.getElementById(id); if (el) el.value = v; } };
  setVal('search-query',  prefs.searchQuery);
  setVal('filter-type',   prefs.filterType);
  setVal('filter-status', prefs.filterStatus);
  setVal('prompts-query', prefs.promptsQuery);
  setVal('prompts-sort',  prefs.promptSort);
  setVal('req-status',    prefs.reqStatus);
  setVal('req-sort',      prefs.reqSort);
  if (prefs.promptSort)   S.promptSort   = prefs.promptSort;
  if (prefs.promptFilter) {
    S.promptFilter = prefs.promptFilter;
    document.querySelectorAll('#prompts-filter-grp .toggle-btn').forEach(b => {
      b.classList.toggle('active', b.dataset.pf === prefs.promptFilter);
    });
  }

  // Restore active tab
  const savedTab = localStorage.getItem(K_ACTIVE_TAB);
  if (savedTab && ['search','graph','prompts','requirements'].includes(savedTab)) {
    switchTab(savedTab);
  }

  if (token) {
    connect();
  } else {
    showWhoAreYou();
  }
})();
