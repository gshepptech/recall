'use strict';

// ── Graph Tab ─────────────────────────────────────────────────────
// Uses the server-built /api/ui/graph endpoint which computes multi-signal
// edges (title-reference, module, tags, temporal proximity, project, type).
// Canvas coordinates are always in CSS pixels (offsetWidth/offsetHeight);
// the DPR scale is applied inside drawGraph() via a fresh transform each frame.
async function loadGraph() {
  const res = await apiGet('/api/ui/graph', { limit: 300 });
  if (!res) return;
  buildGraphData(res.nodes || [], res.edges || []);
}

function graphSize() {
  const canvas = document.getElementById('graph-canvas');
  return {
    W: canvas.offsetWidth  || canvas.parentElement.offsetWidth  || 800,
    H: canvas.offsetHeight || canvas.parentElement.offsetHeight || 600,
  };
}

// Node visual weight — decisions/prompts/requirements should dominate over
// the sea of auto-logged conversation entries.
const TYPE_WEIGHT = {
  decision:     1.6,
  requirement:  1.5,
  prompt:       1.4,
  reference:    1.25,
  error:        1.2,
  conversation: 0.75,
};
function typeWeight(t) { return TYPE_WEIGHT[t] || 1.0; }

function buildGraphData(nodes, edges) {
  const { W, H } = graphSize();

  // Seed random positions in a disc around the center
  S.gNodes = nodes.map(m => ({
    id: m.id,
    title: m.title || 'Untitled',
    memory_type: m.memory_type || 'conversation',
    access_count: m.access_count || 0,
    tags: Array.isArray(m.tags) ? m.tags : [],
    project: m.project || S.project,
    created_at: m.created_at || null,
    x: W / 2 + (Math.random() - 0.5) * Math.min(W, H) * 0.7,
    y: H / 2 + (Math.random() - 0.5) * Math.min(W, H) * 0.7,
    vx: 0, vy: 0, dragging: false,
  }));

  // Edges come pre-scored with weight + type
  S.gEdges = edges.map(e => ({
    source: e.source,
    target: e.target,
    weight: e.weight || 1,
    type:   e.type   || 'related',
  }));

  // Tally type counts for the interactive legend
  S.gTypeCounts = {};
  S.gNodes.forEach(n => {
    S.gTypeCounts[n.memory_type] = (S.gTypeCounts[n.memory_type] || 0) + 1;
  });

  // Reset viewport so new graph is centered on current canvas
  S.gT = { x: 0, y: 0, s: 1 };
  S.gSel = null;
  S.gHover = null;

  // Pre-warm the layout offscreen so the user doesn't watch it wiggle into place.
  // 250 ticks with alpha=1 settles most graphs; ~80–150ms blocking on n≈150 nodes.
  rebuildGraphCaches();
  S.gAlpha = 1.0;
  for (let i = 0; i < 250; i++) simStep();

  renderGraphLegend();
  renderGraphStats();
  startGraphSim();
}

function visibleNode(n) { return !S.gHiddenTypes.has(n.memory_type); }

function renderGraphLegend() {
  const legend = document.getElementById('graph-legend');
  // Sort: signal types first (decision/prompt/requirement/etc.), conversation last
  const order = ['decision','requirement','prompt','reference','error','conversation'];
  const types = Object.keys(S.gTypeCounts).sort((a, b) => {
    const ia = order.indexOf(a), ib = order.indexOf(b);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
  });
  legend.innerHTML = types.map(t => {
    const off = S.gHiddenTypes.has(t) ? ' off' : '';
    return `<div class="legend-row${off}" data-type="${esc(t)}" title="Click to toggle">
      <span class="legend-dot" style="background:${typeColor(t)}"></span>
      <span>${esc(t)}</span>
      <span class="legend-count">${S.gTypeCounts[t]}</span>
    </div>`;
  }).join('');
  legend.style.display = types.length > 0 ? 'flex' : 'none';
  legend.querySelectorAll('.legend-row').forEach(row => {
    row.addEventListener('click', () => {
      const t = row.dataset.type;
      if (S.gHiddenTypes.has(t)) S.gHiddenTypes.delete(t);
      else S.gHiddenTypes.add(t);
      renderGraphLegend();
      renderGraphStats();
      rebuildGraphCaches();
      kick(0.4);
    });
  });
}

function renderGraphStats() {
  const el = document.getElementById('graph-stats');
  if (!el) return;
  const visN = S.gNodes.filter(visibleNode).length;
  const visIds = new Set(S.gNodes.filter(visibleNode).map(n => n.id));
  const visE = S.gEdges.filter(e => visIds.has(e.source) && visIds.has(e.target)).length;
  el.innerHTML = `<span>${visN} nodes</span><span>${visE} links</span>`;
}

// Recompute the visible-node caches. Called when membership changes
// (data load, legend toggle), NOT every frame.
function rebuildGraphCaches() {
  S.gActive = S.gNodes.filter(visibleNode);
  S.gActiveSet = new Set(S.gActive.map(n => n.id));
  S.gNodeMap = Object.fromEntries(S.gActive.map(n => [n.id, n]));
}

// Returns true if it actually advanced physics. Forces scale by gAlpha so
// the layout settles instead of jittering forever on float noise.
function simStep() {
  if (S.gAlpha < 0.005 && !S.gDrag) return false;
  const { W, H } = graphSize();
  const cx = W / 2, cy = H / 2;
  const active = S.gActive;
  const activeSet = S.gActiveSet;
  const nodeMap = S.gNodeMap;
  const a2 = Math.max(S.gAlpha, S.gDrag ? 0.2 : 0);

  for (let i = 0; i < active.length; i++) { active[i].fx = 0; active[i].fy = 0; }

  for (let i = 0; i < active.length; i++) {
    const a = active[i];
    for (let j = i + 1; j < active.length; j++) {
      const b = active[j];
      const dx = b.x - a.x, dy = b.y - a.y;
      const d2 = dx*dx + dy*dy || 1;
      const dist = Math.sqrt(d2);
      const f = 4500 / d2;
      const fx = f * dx / dist, fy = f * dy / dist;
      a.fx -= fx; a.fy -= fy;
      b.fx += fx; b.fy += fy;
    }
  }

  for (let k = 0; k < S.gEdges.length; k++) {
    const e = S.gEdges[k];
    if (!activeSet.has(e.source) || !activeSet.has(e.target)) continue;
    const a = nodeMap[e.source], b = nodeMap[e.target];
    if (!a || !b) continue;
    const dx = b.x - a.x, dy = b.y - a.y;
    const dist = Math.sqrt(dx*dx + dy*dy) || 1;
    const restLen = Math.max(60, 140 - e.weight * 12);
    const f = (dist - restLen) * 0.055;
    const fx = f * dx / dist, fy = f * dy / dist;
    a.fx += fx; a.fy += fy;
    b.fx -= fx; b.fy -= fy;
  }

  for (let i = 0; i < active.length; i++) {
    const n = active[i];
    n.fx += (cx - n.x) * 0.004;
    n.fy += (cy - n.y) * 0.004;
    if (n.dragging) continue;
    n.vx = (n.vx + n.fx * a2) * 0.85;
    n.vy = (n.vy + n.fy * a2) * 0.85;
    n.x += n.vx;
    n.y += n.vy;
  }

  S.gAlpha *= 0.96;
  return true;
}

function nodeRadius(n) {
  // Base size driven by memory type importance + access count
  return 5 + typeWeight(n.memory_type) * 3 + Math.log(n.access_count + 1) * 1.8;
}

function drawGraph() {
  const canvas = document.getElementById('graph-canvas');
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const W = canvas.offsetWidth, H = canvas.offsetHeight;

  // Keep backing store in sync with CSS size — reset transform each frame
  if (canvas.width !== Math.round(W * dpr) || canvas.height !== Math.round(H * dpr)) {
    canvas.width  = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);

  // Viewport pan + zoom
  ctx.translate(S.gT.x, S.gT.y);
  ctx.scale(S.gT.s, S.gT.s);

  const active = S.gActive;
  const activeSet = S.gActiveSet;
  const nodeMap = S.gNodeMap;
  const selIds  = S.gSel ? new Set(
    [S.gSel.id, ...S.gEdges
      .filter(e => e.source === S.gSel.id || e.target === S.gSel.id)
      .flatMap(e => [e.source, e.target])]
  ) : null;

  // Edges
  S.gEdges.forEach(e => {
    if (!activeSet.has(e.source) || !activeSet.has(e.target)) return;
    const a = nodeMap[e.source], b = nodeMap[e.target];
    if (!a || !b) return;
    const hovConn = S.gHover && (e.source === S.gHover.id || e.target === S.gHover.id);
    const selConn = selIds && selIds.has(e.source) && selIds.has(e.target);
    const dim = selIds && !selConn;
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);

    // Edge type → color: wiki is an explicit [[title]] anchor and gets the
    // loudest styling; references are title-in-body (implicit) and remain
    // mid-weight; tag/module/temporal stay subtle.
    let base;
    switch (e.type) {
      case 'wiki':      base = [127,119,221]; break;  // bold purple — explicit [[link]]
      case 'reference': base = [168,156,247]; break;  // lilac — implicit mention
      case 'module':    base = [83,177,183];  break;  // teal
      case 'tag':       base = [186,117,23];  break;  // amber
      case 'temporal':  base = [100,104,130]; break;  // grey-blue
      case 'project':   base = [136,135,128]; break;  // neutral
      default:          base = [136,135,128];
    }
    const isWiki   = e.type === 'wiki';
    const intensity = isWiki
      ? 0.8
      : Math.min(1, 0.18 + e.weight * 0.06);
    const alpha = selConn ? 0.9 : hovConn ? 0.7 : dim ? 0.03 : intensity;
    ctx.strokeStyle = `rgba(${base[0]},${base[1]},${base[2]},${alpha})`;
    const baseWidth = isWiki ? 2.0 : 0.9;
    const hoverBoost = selConn || hovConn ? 1.8 : baseWidth;
    ctx.lineWidth = (hoverBoost + Math.min(1.2, e.weight * 0.12)) / S.gT.s;
    ctx.stroke();
  });

  // Nodes
  const showLabels = S.gT.s >= 0.65;
  active.forEach(n => {
    const isHov = n === S.gHover;
    const isSel = n === S.gSel;
    const dim   = selIds && !selIds.has(n.id);
    const baseR = nodeRadius(n);
    const r     = baseR + (isHov || isSel ? 3 : 0);
    const color = typeColor(n.memory_type);

    ctx.globalAlpha = dim ? 0.10 : (isHov || isSel ? 1.0 : 0.85);

    // Soft glow on selected node
    if (isSel) {
      ctx.beginPath();
      ctx.arc(n.x, n.y, r + 7, 0, Math.PI * 2);
      ctx.fillStyle = color + '33';
      ctx.fill();
    }

    ctx.beginPath();
    ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();

    // Signal-type memories get a subtle white ring so they stand out from conversation
    if (n.memory_type !== 'conversation' && !dim) {
      ctx.strokeStyle = 'rgba(255,255,255,0.35)';
      ctx.lineWidth = 0.9 / S.gT.s;
      ctx.stroke();
    }
    if (isHov || isSel) {
      ctx.strokeStyle = '#fff';
      ctx.lineWidth = (isSel ? 1.8 : 1.2) / S.gT.s;
      ctx.stroke();
    }

    // Labels — only for important types unless zoomed in
    const alwaysLabel = n.memory_type !== 'conversation' && typeWeight(n.memory_type) >= 1.25;
    if ((showLabels || isHov || isSel) && (alwaysLabel || showLabels || isHov || isSel)) {
      ctx.globalAlpha = dim ? 0.2 : (isSel || isHov ? 1.0 : alwaysLabel ? 0.85 : 0.7);
      ctx.fillStyle = '#e6e5db';
      ctx.font = `${Math.max(9, 10 / Math.max(0.6, S.gT.s))}px -apple-system,sans-serif`;
      ctx.textAlign = 'center';
      const label = (n.title || '').slice(0, 26);
      ctx.fillText(label, n.x, n.y + r + (11 / S.gT.s));
    }
    ctx.globalAlpha = 1;
  });
}

function graphLoop() {
  const stepped = simStep();
  drawGraph();
  const needsRedraw = S.gNeedsDraw;
  S.gNeedsDraw = false;
  if (stepped || needsRedraw || S.gDrag) {
    S.gAF = requestAnimationFrame(graphLoop);
  } else {
    S.gAF = null;
  }
}

// kick(): request a redraw and (optionally) re-heat the simulation.
// Use small reheat values for interactions that nudge layout (drag, legend toggle).
// Use 0 for pure-redraw events (hover, pan, zoom).
function kick(reheat) {
  S.gNeedsDraw = true;
  if (reheat) S.gAlpha = Math.max(S.gAlpha, reheat);
  if (!S.gAF) S.gAF = requestAnimationFrame(graphLoop);
}

function startGraphSim() {
  if (S.gAF) { cancelAnimationFrame(S.gAF); S.gAF = null; }
  S.gAlpha = 0.3;       // brief warm-in animation; pre-warm already settled most of it
  kick();
}

function stopGraphSim() {
  if (S.gAF) { cancelAnimationFrame(S.gAF); S.gAF = null; }
  S.gAlpha = 0;
}

function startGraphTab() {
  if (S.gNodes.length > 0) {
    startGraphSim();
  } else if (S.connected) {
    loadGraph();
  }
}

function graphToWorld(cx, cy) {
  return {
    x: (cx - S.gT.x) / S.gT.s,
    y: (cy - S.gT.y) / S.gT.s
  };
}

function nodeAtPoint(wx, wy) {
  for (let i = S.gNodes.length - 1; i >= 0; i--) {
    const n = S.gNodes[i];
    if (!visibleNode(n)) continue;
    const r = nodeRadius(n) + 4;
    const dx = n.x - wx, dy = n.y - wy;
    if (dx*dx + dy*dy <= r*r) return n;
  }
  return null;
}

// Small hover tooltip — just title + type, follows cursor
function showHoverTip(n, cx, cy) {
  const el = document.getElementById('graph-tip');
  if (!n) { el.classList.remove('visible'); return; }
  el.innerHTML = `
    <div class="gtip-title">${esc(n.title)}</div>
    <div class="gtip-type">${esc(n.memory_type)} · ${esc(n.project)} · ${n.access_count}×</div>`;
  el.style.left = (cx + 14) + 'px';
  el.style.top  = (cy + 14) + 'px';
  el.classList.add('visible');
}

// Full click-open drawer — fetches content_md and renders markdown
async function openNodeDetail(n) {
  const el = document.getElementById('graph-node-detail');
  if (!n) { el.classList.remove('visible'); S.gSel = null; return; }
  S.gSel = n;

  const connCount = S.gEdges.filter(e => e.source === n.id || e.target === n.id).length;
  const tagHtml = (n.tags || []).map(t => `<span class="tag-pill">${esc(t)}</span>`).join('');

  el.innerHTML = `
    <div class="gndp-head">
      <button class="gndp-close" onclick="closeNodeDetail()" title="Close">×</button>
      <div class="gndp-badges">
        ${typeBadge(n.memory_type)}
      </div>
      <div class="gndp-title">${esc(n.title)}</div>
      <div class="gndp-meta">
        <span>${esc(n.project)}</span>
        <span>accessed ${n.access_count}×</span>
        <span>${connCount} connection${connCount === 1 ? '' : 's'}</span>
      </div>
    </div>
    ${tagHtml ? `<div class="gndp-tags">${tagHtml}</div>` : ''}
    <div class="gndp-body"><div class="gndp-loading">Loading content…</div></div>`;
  el.classList.add('visible');

  const full = await apiGet('/api/ui/memories/' + encodeURIComponent(n.id));
  // Bail if user already closed or clicked a different node while fetch was in flight
  if (S.gSel !== n) return;
  const body = el.querySelector('.gndp-body');
  if (!full || full.error) {
    body.innerHTML = `<div class="gndp-loading" style="color:#f87171">Failed to load memory content</div>`;
    return;
  }
  const content = full.content_md || '_(empty)_';
  body.innerHTML = renderMd(content);
}

function closeNodeDetail() {
  const el = document.getElementById('graph-node-detail');
  el.classList.remove('visible');
  S.gSel = null;
}

// Graph events
(function setupGraphEvents() {
  const canvas = document.getElementById('graph-canvas');
  let downPos = null;   // track mousedown position to distinguish click vs drag

  canvas.addEventListener('mousedown', e => {
    const rect = canvas.getBoundingClientRect();
    const cx = e.clientX - rect.left, cy = e.clientY - rect.top;
    downPos = { x: e.clientX, y: e.clientY, cx, cy };
    const w = graphToWorld(cx, cy);
    const n = nodeAtPoint(w.x, w.y);
    if (n) {
      S.gDrag = n;
      n.dragging = true;
      kick(0.3);
    } else {
      S.gPan = true;
      S.gPanS = { x: e.clientX - S.gT.x, y: e.clientY - S.gT.y };
    }
  });

  canvas.addEventListener('mousemove', e => {
    const rect = canvas.getBoundingClientRect();
    const cx = e.clientX - rect.left, cy = e.clientY - rect.top;
    if (S.gDrag) {
      const w = graphToWorld(cx, cy);
      S.gDrag.x = w.x; S.gDrag.y = w.y;
      kick();
      return;
    }
    if (S.gPan && S.gPanS) {
      S.gT.x = e.clientX - S.gPanS.x;
      S.gT.y = e.clientY - S.gPanS.y;
      kick();
      return;
    }
    const w = graphToWorld(cx, cy);
    const prev = S.gHover;
    S.gHover = nodeAtPoint(w.x, w.y);
    if (S.gHover !== prev || S.gHover) showHoverTip(S.gHover, cx, cy);
    canvas.style.cursor = S.gHover ? 'pointer' : '';
    if (S.gHover !== prev) kick();
  });

  canvas.addEventListener('mouseleave', () => {
    const had = S.gHover;
    S.gHover = null;
    document.getElementById('graph-tip').classList.remove('visible');
    if (had) kick();
  });

  canvas.addEventListener('mouseup', e => {
    const moved = downPos && (
      Math.abs(e.clientX - downPos.x) > 4 || Math.abs(e.clientY - downPos.y) > 4
    );
    if (S.gDrag) {
      S.gDrag.dragging = false;
      // If the mouse barely moved, treat as click → open the memory
      if (!moved) {
        const rect = canvas.getBoundingClientRect();
        const cx = e.clientX - rect.left, cy = e.clientY - rect.top;
        const w = graphToWorld(cx, cy);
        const n = nodeAtPoint(w.x, w.y);
        if (n) openNodeDetail(n);
      }
      S.gDrag = null;
      kick(0.15);   // brief settle after drop
    }
    S.gPan = false; S.gPanS = null;
    downPos = null;
  });

  canvas.addEventListener('wheel', e => {
    e.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const cx = e.clientX - rect.left, cy = e.clientY - rect.top;
    const factor = e.deltaY > 0 ? 0.9 : 1.1;
    const newS = Math.min(4, Math.max(0.25, S.gT.s * factor));
    const ratio = newS / S.gT.s;
    S.gT.x = cx - ratio * (cx - S.gT.x);
    S.gT.y = cy - ratio * (cy - S.gT.y);
    S.gT.s = newS;
    kick();
  }, { passive: false });

  // Esc closes the detail drawer
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && S.activeTab === 'graph' && S.gSel) {
      closeNodeDetail();
    }
  });
})();
