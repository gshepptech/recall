'use strict';

// ── Prompts Tab ───────────────────────────────────────────────────
async function loadPrompts() {
  const res = await apiGet('/api/ui/prompts');
  if (!res) return;
  S.allPrompts = res.prompts || [];
  renderPromptsSidebar();
}

function filteredSortedPrompts() {
  let items = [...S.allPrompts];
  const q = document.getElementById('prompts-query').value.toLowerCase();
  if (q) items = items.filter(p => (p.title || '').toLowerCase().includes(q));

  switch (S.promptFilter) {
    case 'run': items = items.filter(p => (p.access_count || 0) > 0); break;
    case 'new': items = items.filter(p => !(p.access_count || 0)); break;
  }

  switch (S.promptSort) {
    case 'name':       items.sort((a,b) => (a.title||'').localeCompare(b.title||'')); break;
    case 'token_size': items.sort((a,b) => (b.token_count||0) - (a.token_count||0)); break;
    case 'run_count':  items.sort((a,b) => (b.access_count||0) - (a.access_count||0)); break;
    default:           items.sort((a,b) => new Date(b.last_accessed||0) - new Date(a.last_accessed||0)); break;
  }
  return items;
}

function renderPromptsSidebar() {
  const list = document.getElementById('prompts-list');
  const items = filteredSortedPrompts();
  if (items.length === 0) {
    list.innerHTML = '<div class="empty-msg">No prompts match this filter.</div>';
    return;
  }
  const maxTok = Math.max(1, ...items.map(p => p.token_count || 0));

  list.innerHTML = items.map((p, i) => {
    const runs   = p.access_count || 0;
    const isRun  = runs > 0;
    const tok    = p.token_count || 0;
    const tokStr = tok > 0 ? (tok >= 1000 ? Math.round(tok/100)/10+'k' : tok+'') : '';
    const pct    = Math.round((tok / maxTok) * 100);
    const active = S.selPrompt && S.selPrompt.id === p.id ? 'active' : '';
    const ts     = daysAgo(p.last_accessed);

    return `<div class="prompt-card ${isRun ? '' : 'unrun'} ${active}" data-pidx="${i}">
      <div class="pc-top">
        <span class="pc-name">${esc(p.title || 'Untitled')}</span>
        ${isRun && tokStr ? `<span class="tok-badge">${tokStr}</span>` : ''}
        ${!isRun ? `<span class="spill spill-new">new</span>` : ''}
      </div>
      <svg width="100%" height="2" style="display:block" xmlns="http://www.w3.org/2000/svg">
        <rect x="0" y="0" width="${pct}%" height="2" fill="#534AB7" rx="1"/>
      </svg>
      <div class="mc-meta">${isRun ? `run ${runs}×  ·  ${ts}` : (tokStr ? tokStr + ' tokens' : '')}</div>
    </div>`;
  }).join('');

  list.querySelectorAll('.prompt-card').forEach(el => {
    el.addEventListener('click', async () => {
      const p = filteredSortedPrompts()[+el.dataset.pidx];
      S.selPrompt = p;
      renderPromptsSidebar();
      // These are independent async ops, so run them in parallel
      renderPromptsDetail(p);
      loadRunHistory(p);
    });
  });
}

async function loadRunHistory(prompt) {
  // Reads prompt_runs via /api/ui/runs. Prefer prompt_id linkage, then fall
  // back to prompt_name for rows logged without a prompt_id.
  const params = { limit: 30 };
  if (prompt.id) params.prompt_id = prompt.id;
  let res = await apiGet('/api/ui/runs', params);

  // Fallback for legacy rows that only carry prompt_name
  if (res && (!res.runs || res.runs.length === 0) && prompt.title) {
    const byName = await apiGet('/api/ui/runs', {
      prompt_name: prompt.title, limit: 30
    });
    if (byName && byName.runs && byName.runs.length) res = byName;
  }

  if (!res) return;
  S.promptHistory = res.runs || [];
  S.promptHistoryStats = res.stats || {};
  renderRunHistory();
  renderPromptStatCards();
}

function renderPromptStatCards() {
  const s = S.promptHistoryStats || {};
  const fmt = n => {
    n = Math.round(Number(n) || 0);
    if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
    return n > 0 ? n.toString() : '—';
  };
  const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
  set('avg-in',   fmt(s.avg_in));
  set('avg-cach', fmt(s.avg_cache_read));
  set('avg-out',  fmt(s.avg_out));
}

function renderRunHistory() {
  const sec = document.getElementById('run-hist-section');
  if (!sec) return;
  if (S.promptHistory.length === 0) {
    sec.innerHTML = '<span class="slabel">Run History</span>'
      + '<div class="empty-msg">No runs recorded yet. Run this prompt in Claude Code to see history here.</div>';
    return;
  }

  const s = S.promptHistoryStats || {};
  const totalIn    = Math.round(Number(s.sum_in) || 0);
  const totalCache = Math.round(Number(s.sum_cache_read) || 0);
  const totalOut   = Math.round(Number(s.sum_out) || 0);

  const header = `<span class="slabel">Run History</span>
    <div class="rh-summary">
      <span>${S.promptHistory.length} runs</span>
      <span class="rh-sep">·</span>
      <span>in <b>${totalIn.toLocaleString()}</b></span>
      <span class="rh-sep">·</span>
      <span>cached <b style="color:#BA7517">${totalCache.toLocaleString()}</b></span>
      <span class="rh-sep">·</span>
      <span>out <b>${totalOut.toLocaleString()}</b></span>
    </div>`;

  const entries = S.promptHistory.map((r, idx) => {
    const machine = r.runner || 'unknown';
    const status  = r.status || 'success';
    const ts      = fmtDate(r.created_at);
    const summary = r.output_summary || '';
    const tokIn   = r.tokens_input  || 0;
    const tokCach = r.tokens_cache_read || 0;
    const tokCC   = r.tokens_cache_creation || 0;
    const tokOut  = r.tokens_output || 0;
    const id      = 'diary-' + idx;

    const tokBits = [];
    if (tokIn)   tokBits.push(`in ${tokIn.toLocaleString()}`);
    if (tokCach) tokBits.push(`cached ${tokCach.toLocaleString()}`);
    if (tokCC)   tokBits.push(`cache-new ${tokCC.toLocaleString()}`);
    if (tokOut)  tokBits.push(`out ${tokOut.toLocaleString()}`);

    return `<div class="run-entry">
      <div class="run-entry-hdr">
        <span class="run-machine">${esc(machine)}</span>
        <div style="display:flex;align-items:center;gap:6px">
          <span class="spill spill-${status === 'fail' ? 'fail' : 'success'}">${esc(status)}</span>
          <span class="run-ts">${ts}</span>
        </div>
      </div>
      ${summary ? `<div class="run-diary collapsed" id="${id}">${esc(summary)}</div>
      <span class="show-toggle" data-diary="${id}">↓ show more</span>` : ''}
      ${tokBits.length ? `<div class="run-tokens">${tokBits.join('  ·  ')}</div>` : ''}
    </div>`;
  }).join('');

  sec.innerHTML = header + entries;

  sec.querySelectorAll('.show-toggle').forEach(btn => {
    btn.addEventListener('click', () => {
      const diary = document.getElementById(btn.dataset.diary);
      if (diary.classList.contains('collapsed')) {
        diary.classList.remove('collapsed');
        btn.textContent = '↑ show less';
      } else {
        diary.classList.add('collapsed');
        btn.textContent = '↓ show more';
      }
    });
  });
}

async function renderPromptsDetail(p) {
  const panel = document.getElementById('prompts-detail');
  const runs  = p.access_count || 0;
  const isRun = runs > 0;
  const tok   = p.token_count || 0;
  const ts    = daysAgo(p.last_accessed || p.created_at);
  const machine = p.created_by || '—';

  // Show header immediately while content loads
  panel.innerHTML = `
    <div class="detail-header">
      <div class="dh-r1">
        ${isRun
          ? `<span class="spill spill-run">run ${runs}×</span><span style="font-size:11px;color:var(--tfaint)">last run ${ts} · ${esc(machine)}</span>`
          : `<span class="spill spill-new">not run yet</span>`}
      </div>
      <div class="dh-title">${esc(p.title || 'Untitled')}</div>
      <div class="prompt-stats-row">
        <div class="stat-card"><div class="stat-card-val">${tok > 0 ? (tok >= 1000 ? Math.round(tok/100)/10+'k' : tok) : '—'}</div><div class="stat-card-lbl">prompt size</div></div>
        <div class="stat-card"><div class="stat-card-val" id="avg-in">—</div><div class="stat-card-lbl">avg input</div></div>
        <div class="stat-card"><div class="stat-card-val" id="avg-cach">—</div><div class="stat-card-lbl">avg cached</div></div>
        <div class="stat-card"><div class="stat-card-val" id="avg-out">—</div><div class="stat-card-lbl">avg output</div></div>
      </div>
    </div>
    <div class="prompts-detail-body">
      <div class="prompt-content-sec">
        <span class="slabel">Prompt Content</span>
        <div style="color:var(--tfaint);font-size:12px;padding:8px 0">Loading…</div>
      </div>
      <div class="run-hist-sec" id="run-hist-section">
        <span class="slabel">Run History</span>
        <div class="empty-msg">Loading run history…</div>
      </div>
    </div>`;

  // Fetch full content directly from DB (list endpoint returns 300-char snippet only)
  if (p.id) {
    const full = await apiGet('/api/ui/memories/' + encodeURIComponent(p.id));
    if (full && !full.error) {
      const contentSec = panel.querySelector('.prompt-content-sec');
      if (contentSec) {
        contentSec.innerHTML = `<span class="slabel">Prompt Content</span>${renderMd(full.content_md || '')}`;
      }
    }
  }
}

// ── Requirements Tab ──────────────────────────────────────────────
async function loadRequirements() {
  const res = await apiGet('/api/ui/requirements');
  if (!res) return;
  S.allReqs = res.requirements || [];
  renderReqSidebar();
}

function renderReqSidebar() {
  const list     = document.getElementById('req-list');
  const stFilter = document.getElementById('req-status').value;
  const sort     = document.getElementById('req-sort').value;

  let items = [...S.allReqs];
  if (stFilter) items = items.filter(r => r.status === stFilter);
  if (sort === 'priority') items.sort((a,b) => (b.priority||0) - (a.priority||0));
  else items.sort((a,b) => new Date(b.created_at||0) - new Date(a.created_at||0));

  if (items.length === 0) {
    list.innerHTML = '<div class="empty-msg">No requirements match this filter.</div>';
    return;
  }

  const statusBorderColor = { pending:'#BA7517', approved:'#1D9E75', rejected:'#A32D2D' };
  list.innerHTML = items.map((r, i) => {
    const c      = statusBorderColor[r.status] || '#888780';
    const active = S.selReq && S.selReq.id === r.id ? 'active' : '';
    return `<div class="req-card ${active}" style="border-left-color:${c}" data-ridx="${i}">
      <div class="rc-top">
        <span class="rc-title">${esc(r.title || 'Untitled')}</span>
        ${statusPill(r.status)}
      </div>
      <div class="mc-meta">${fmtDate(r.created_at)}</div>
    </div>`;
  }).join('');

  const finalItems = items;
  list.querySelectorAll('.req-card').forEach(el => {
    el.addEventListener('click', () => {
      const r = finalItems[+el.dataset.ridx];
      S.selReq = r;
      renderReqSidebar();
      renderReqDetail(r);
    });
  });
}

function renderReqDetail(r) {
  const panel = document.getElementById('req-detail');
  const tags  = r.tags || [];
  panel.innerHTML = `
    <div class="detail-header">
      <div class="dh-r1">${statusPill(r.status)} ${typeBadge('requirement')}</div>
      <div class="dh-title">${esc(r.title || 'Untitled')}</div>
    </div>
    <div class="detail-body">
      <span class="slabel">Content</span>
      ${renderMd(r.content || '')}
      ${tags.length > 0 ? `<span class="slabel">Tags</span><div>${tags.map(t => `<span class="tag-pill">${esc(t)}</span>`).join('')}</div>` : ''}
      <span class="slabel">Meta</span>
      <div class="meta-row">
        <span>Created ${fmtDate(r.created_at)}</span>
        <span>Project: ${esc(r.project || S.project)}</span>
        ${r.priority != null ? `<span>Priority: ${r.priority}</span>` : ''}
      </div>
    </div>`;
}
