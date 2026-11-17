'use strict';

// ── Search Tab ────────────────────────────────────────────────────
async function loadSearch(query) {
  // New query → reset paging
  S.searchQuery = query || '';
  S.searchLimit = S.searchPageSize;
  S.searchSelected = null;
  await fetchSearch();
}

async function loadMoreSearch() {
  if (S.searchLoading) return;
  S.searchLimit += S.searchPageSize;
  await fetchSearch();
}

async function fetchSearch() {
  const type   = document.getElementById('filter-type').value;
  const status = document.getElementById('filter-status').value;
  const params = { q: S.searchQuery || '*', limit: S.searchLimit };
  if (type)   params.type   = type;
  if (status) params.status = status;

  S.searchLoading = true;
  renderSearchSidebar();
  const res = await apiGet('/api/ui/memories', params);
  S.searchLoading = false;
  if (!res) return;

  S.searchResults = res.memories || [];
  S.searchTotal   = res.total || 0;
  renderSearchSidebar();
}

function renderSearchSidebar() {
  const list = document.getElementById('search-list');
  if (S.searchResults.length === 0) {
    list.innerHTML = S.searchLoading
      ? '<div class="empty-msg">Searching…</div>'
      : '<div class="empty-msg">No memories found for this query.</div>';
    return;
  }
  const cards = S.searchResults.map((m, i) => {
    const c   = typeColor(m.memory_type);
    const scoreRaw = m.score != null ? m.score : null;
    const sc  = scoreRaw != null ? Math.round(scoreRaw * 100) : null;
    const scColor = sc != null ? scoreColor(sc) : '#888780';
    const pct = sc != null ? Math.min(100, sc) : 0;
    const active = S.searchSelected && S.searchSelected.id === m.id ? 'active' : '';
    const ts  = daysAgo(m.last_accessed || m.created_at);
    const acc = m.access_count || 0;
    const snippet = (m.snippet || '').replace(/\n+/g, ' ').trim().slice(0, 90);

    return `<div class="mem-card ${active}" style="border-left-color:${c}" data-idx="${i}">
      <div class="mc-top">
        ${typeBadge(m.memory_type)}
        ${sc != null ? `<span style="font-size:10px;color:${scColor};font-weight:500">${sc}%</span>` : ''}
      </div>
      <div class="mc-title">${esc(m.title || 'Untitled')}</div>
      ${snippet ? `<div class="mc-snippet">${esc(snippet)}</div>` : ''}
      <svg width="100%" height="3" style="display:block;margin-top:5px" xmlns="http://www.w3.org/2000/svg">
        <rect x="0" y="0" width="100%" height="3" fill="var(--border)" rx="1.5"/>
        <rect x="0" y="0" width="${pct}%" height="3" fill="${scColor}" rx="1.5"/>
      </svg>
      <div class="mc-meta">accessed ${acc}×${ts ? '  ·  ' + ts : ''}</div>
    </div>`;
  }).join('');

  // Footer: counter + load-more (only when there are more rows than fetched)
  const shown   = S.searchResults.length;
  const total   = S.searchTotal || 0;
  const hasMore = shown >= S.searchLimit && shown < total;
  const counter = `<div class="search-counter">showing ${shown}${total ? ' of ' + total : ''}</div>`;
  const loadMore = hasMore
    ? `<button class="search-load-more" id="search-load-more">${S.searchLoading ? 'Loading…' : 'Load more'}</button>`
    : '';

  list.innerHTML = cards + counter + loadMore;

  list.querySelectorAll('.mem-card').forEach(el => {
    el.addEventListener('click', () => {
      const m = S.searchResults[+el.dataset.idx];
      S.searchSelected = m;
      renderSearchSidebar();
      renderSearchDetail(m);
    });
  });
  const lm = document.getElementById('search-load-more');
  if (lm) lm.addEventListener('click', loadMoreSearch);
}

async function renderSearchDetail(m) {
  const panel = document.getElementById('search-detail');

  // Show skeleton immediately while fetching full content
  panel.innerHTML = `
    <div class="detail-header">
      <div class="dh-r1">${typeBadge(m.memory_type)} ${statusPill(m.status || 'active')}</div>
      <div class="dh-title">${esc(m.title || 'Untitled')}</div>
    </div>
    <div class="detail-body">
      <div class="detail-empty" style="padding:24px 0;color:var(--tfaint);font-size:12px">Loading content…</div>
    </div>`;

  // If the list endpoint already returned content_md (list_all_memories path),
  // skip the extra fetch. Only fetch when content is missing (search path returns snippet only).
  if (m.content_md == null) {
    const full = await apiGet('/api/ui/memories/' + encodeURIComponent(m.id));
    if (full && !full.error) {
      m = { ...m, ...full };
    }
  }

  const sc  = m.score != null ? Math.round(m.score * 100) : 0;
  const scC = scoreColor(sc);
  const acc = m.access_count || 0;
  const R = 26, circ = 2 * Math.PI * R;
  const offset = circ * (1 - sc / 100);
  const tags = Array.isArray(m.tags) ? m.tags : [];
  const tagHtml = tags.map(t => `<span class="tag-pill">${esc(t)}</span>`).join('');

  // Timezone-safe age: SQLite returns "YYYY-MM-DD HH:MM:SS" (no Z) → treated as local without fix
  const ageMs     = Math.max(0, Date.now() - parseUTCDate(m.created_at).getTime());
  const ageDays   = ageMs / 86400000;
  const recency   = Math.round(Math.max(0.05, Math.exp(-0.693 * ageDays / 30)) * 100);
  const frequency = Math.round(Math.min(1.0, Math.log1p(acc) / Math.log1p(100)) * 100);
  const conf      = Math.round((m.confidence_score != null ? m.confidence_score : 1.0) * 100);

  function sigBar(val) {
    const c = scoreColor(val);
    return `<div class="signal-track">
      <svg width="100%" height="4" xmlns="http://www.w3.org/2000/svg">
        <rect x="0" y="0" width="100%" height="4" fill="var(--border)" rx="2"/>
        <rect x="0" y="0" width="${val}%" height="4" fill="${c}" rx="2"/>
      </svg></div>`;
  }

  // content_md is the full text; snippet is truncated fallback
  const content = m.content_md || m.snippet || '';

  panel.innerHTML = `
    <div class="detail-header">
      <div class="dh-r1">
        ${typeBadge(m.memory_type)}
        ${statusPill(m.status || 'active')}
        <span style="font-size:10px;color:var(--tfaint)">accessed ${acc}×</span>
      </div>
      <div class="dh-title">${esc(m.title || 'Untitled')}</div>
      <div class="gauge-block">
        <div class="gauge-svg-wrap">
          <svg width="64" height="64" viewBox="0 0 64 64">
            <circle cx="32" cy="32" r="${R}" fill="none" stroke="var(--bgsec)" stroke-width="5"/>
            <circle cx="32" cy="32" r="${R}" fill="none" stroke="${scC}" stroke-width="5"
              stroke-dasharray="${circ} ${circ}"
              stroke-dashoffset="${offset}"
              stroke-linecap="round"
              transform="rotate(-90 32 32)"/>
            <text x="32" y="37" text-anchor="middle" font-size="14" font-weight="600" fill="${scC}" font-family="-apple-system,sans-serif">${sc}%</text>
          </svg>
        </div>
        <div class="signal-bars">
          <div class="signal-row"><span class="signal-lbl">recency</span>${sigBar(recency)}<span class="signal-val">${recency}</span></div>
          <div class="signal-row"><span class="signal-lbl">frequency</span>${sigBar(frequency)}<span class="signal-val">${frequency}</span></div>
          <div class="signal-row"><span class="signal-lbl">confidence</span>${sigBar(conf)}<span class="signal-val">${conf}</span></div>
        </div>
      </div>
      <div>
        <svg width="100%" height="12" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
          <defs>
            <linearGradient id="tg1" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stop-color="#A32D2D"/>
              <stop offset="35%" stop-color="#BA7517"/>
              <stop offset="70%" stop-color="#1D9E75"/>
            </linearGradient>
          </defs>
          <rect x="0" y="2" width="100%" height="8" rx="3" fill="url(#tg1)"/>
          <line x1="${sc}%" y1="0" x2="${sc}%" y2="12" stroke="#fff" stroke-width="2" stroke-linecap="round"/>
        </svg>
        <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--tfaint);margin-top:2px">
          <span>archive &lt; 20</span><span>stale &lt; 50</span><span>trusted &gt; 80</span>
        </div>
      </div>
    </div>
    <div class="detail-body">
      <span class="slabel">Content</span>
      ${content ? renderMd(content) : '<p style="color:var(--tfaint);font-size:12px">No content.</p>'}
      ${tags.length > 0 ? `<span class="slabel">Tags</span><div style="margin-bottom:10px">${tagHtml}</div>` : ''}
      <span class="slabel">Meta</span>
      <div class="meta-row">
        <span>Created ${fmtDate(m.created_at)}</span>
        ${m.updated_at ? `<span>Updated ${fmtDate(m.updated_at)}</span>` : ''}
        <span>Project: ${esc(m.project || S.project)}</span>
        ${m.created_by ? `<span>By: ${esc(m.created_by)}</span>` : ''}
        ${m.module ? `<span>Module: ${esc(m.module)}</span>` : ''}
      </div>
    </div>`;
}
