"""
screener_view.py
=================
The Screener page — visual rule builder, natural-language search, presets,
saved searches and result cards over the research library.

Split out of pages.py for the same reason risk_view.py was: pages.py is
already the biggest file in the app and this page is a small application on
its own. The rule that keeps it honest: nothing here decides what matches.
Every threshold, comparison, score and explanation comes from
core/screener.py through /api/screen — this file renders what it is given.
That's why the result cards can claim "here's why it matched" and be right:
the ✓/✗ lines are the engine's own per-condition output, not a second
implementation of the same rules in JavaScript.

The page is one static shell plus a JS controller that keeps the rule tree
in a variable and re-posts it on every change. Rendering results server-side
would mean a full page load per pill toggle; at ~560 rows the whole screen
costs a few tens of ms, so the interaction is a fetch and a re-render.
"""

from __future__ import annotations

from .views import card


def screener_page() -> tuple[str, str]:
    body = f"""
{_STYLE}
<div class="scr-head">
  <div>
    <h2 style="margin:0 0 3px;font-size:19px">Screener</h2>
    <div style="font-size:11px;color:#898781">
      Combine any number of conditions over the research library —
      <span id="scr-universe">…</span> tickers with a research page.
    </div>
  </div>
  <div style="display:flex;gap:8px;margin-left:auto;align-items:center">
    <button class="btn secondary" onclick="scrOpenSave()">☆ Save search</button>
    <button class="btn secondary" onclick="scrReset()">Clear all</button>
  </div>
</div>

<div class="scr-searchbar">
  <div style="position:relative;flex:1;min-width:260px">
    <input id="scr-nl" placeholder="Try: price near 8 ema, quality above 90, turnaround, buy zone stocks above 200ma"
           autocomplete="off" oninput="scrOnType(this.value)"
           onkeydown="if(event.key==='Enter'){{scrRunNL();return false}}"
           style="width:100%;padding:10px 12px;font-size:13px">
    <div id="scr-suggest"></div>
  </div>
  <button class="btn" onclick="scrRunNL()">Search</button>
  <button class="btn secondary" onclick="scrOpenPicker()">+ Add condition</button>
</div>

<div id="scr-presets" class="scr-presets"></div>

{card("Active rules", '<div id="scr-rules"></div>', icon="🧩",
      right='<span id="scr-livecount" class="scr-live">—</span>')}

<div id="scr-refine"></div>
<div id="scr-missing"></div>
<div id="scr-summary"></div>

<div class="scr-resulthead">
  <div id="scr-resulttitle" style="font-size:13px;font-weight:600">Results</div>
  <div style="margin-left:auto;display:flex;gap:8px;align-items:center">
    <label style="font-size:11px;color:#898781">Sort</label>
    <select id="scr-sort" onchange="scrRun()">
      <option value="match">Match score</option>
      <option value="composite">Weighted composite</option>
      <option value="quality">Quality</option>
      <option value="rs">RS rank</option>
      <option value="conviction">Conviction</option>
      <option value="eps">EPS growth</option>
      <option value="breakout">Breakout %</option>
      <option value="market_cap">Market cap</option>
      <option value="ticker">Ticker A-Z</option>
    </select>
    <button class="btn secondary" onclick="scrOpenWeights()">⚖ Weights</button>
    <button class="btn secondary" onclick="scrToggleView()" id="scr-viewbtn">Table view</button>
  </div>
</div>
<div id="scr-results"><div class="scr-empty">Loading…</div></div>

{_SAVED_PANEL}
{_MODALS}
"""
    return body, _JS


_STYLE = """
<style>
.scr-head { display:flex; align-items:flex-end; gap:12px; margin-bottom:14px; flex-wrap:wrap }
.scr-searchbar { display:flex; gap:8px; margin-bottom:14px; flex-wrap:wrap; align-items:flex-start }
#scr-suggest { position:absolute; top:40px; left:0; right:0; background:white;
  border:0.5px solid #e1e0d9; border-radius:8px; box-shadow:0 8px 24px rgba(0,0,0,.10);
  max-height:300px; overflow-y:auto; z-index:60; display:none }
.scr-sug { display:flex; gap:8px; align-items:center; padding:8px 12px; font-size:12px;
  cursor:pointer; border-top:0.5px solid #f1efea }
.scr-sug:first-child { border-top:none }
.scr-sug:hover, .scr-sug.on { background:#E6F1FB }
.scr-sug .k { margin-left:auto; font-size:10px; color:#898781; text-transform:uppercase }
.scr-presets { display:flex; gap:8px; overflow-x:auto; padding-bottom:10px; margin-bottom:4px }
.scr-preset { flex:0 0 auto; background:white; border:0.5px solid #e1e0d9; border-radius:10px;
  padding:9px 13px; cursor:pointer; min-width:150px }
.scr-preset:hover { border-color:#185FA5; background:#F7FBFF }
.scr-preset.on { border-color:#185FA5; background:#E6F1FB }
.scr-preset b { display:block; font-size:12px; margin-bottom:2px }
.scr-preset span { font-size:10px; color:#898781; line-height:1.35; display:block }
.scr-live { font-size:11px; font-weight:600; color:#0C447C; background:#E6F1FB;
  padding:3px 9px; border-radius:20px }
.scr-pill { display:inline-flex; align-items:center; gap:7px; background:#E6F1FB; color:#0C447C;
  border:0.5px solid #cfe2f5; font-size:11.5px; font-weight:600; padding:5px 6px 5px 11px;
  border-radius:20px; margin:0 5px 5px 0 }
.scr-pill.neg { background:#FCEBEB; color:#791F1F; border-color:#f3d5d5 }
.scr-pill .x { cursor:pointer; border:none; background:rgba(0,0,0,.06); color:inherit;
  border-radius:50%; width:17px; height:17px; line-height:15px; font-size:12px; padding:0 }
.scr-pill .x:hover { background:rgba(0,0,0,.16) }
.scr-pill .n { font-weight:500; opacity:.72; font-size:10px }
.scr-joiner { display:inline-block; font-size:10px; font-weight:700; color:#898781;
  margin:0 6px 5px 1px; letter-spacing:.5px; cursor:pointer; text-decoration:underline dotted }
.scr-joiner:hover { color:#185FA5 }
.scr-empty { padding:26px; text-align:center; color:#898781; font-size:12px;
  background:white; border:0.5px solid #e1e0d9; border-radius:12px }
.scr-note { font-size:11px; padding:9px 13px; border-radius:9px; margin-bottom:10px;
  background:#FAEEDA; color:#633806; border:0.5px solid #f0dfc0 }
.scr-note b { font-weight:600 }
.scr-refine { font-size:11px; padding:9px 13px; border-radius:9px; margin-bottom:10px;
  background:#F7FBFF; color:#0C447C; border:0.5px solid #cfe2f5;
  display:flex; gap:10px; align-items:center; flex-wrap:wrap }
.scr-stats { display:flex; gap:9px; flex-wrap:wrap; margin-bottom:14px }
.scr-stat { background:white; border:0.5px solid #e1e0d9; border-radius:11px;
  padding:10px 15px; min-width:104px }
.scr-stat .v { font-size:19px; font-weight:600; line-height:1.15 }
.scr-stat .l { font-size:10px; color:#898781; text-transform:uppercase; letter-spacing:.3px }
.scr-resulthead { display:flex; align-items:center; gap:10px; margin-bottom:10px; flex-wrap:wrap }
.scr-card { background:white; border:0.5px solid #e1e0d9; border-radius:12px; padding:13px 15px;
  margin-bottom:9px }
.scr-card:hover { border-color:#cfe2f5 }
.scr-cardtop { display:flex; align-items:center; gap:10px; flex-wrap:wrap }
.scr-tk { font-size:15px; font-weight:700; text-decoration:none; color:#0b0b0b }
.scr-tk:hover { color:#185FA5 }
.scr-why { display:flex; flex-wrap:wrap; gap:5px; margin-top:9px }
.scr-why div { font-size:11px; padding:3px 9px; border-radius:6px; background:#E1F5EE;
  color:#085041 }
.scr-why div.no { background:#FCEBEB; color:#791F1F }
.scr-hl { background:#CFF0E4; color:#085041; font-weight:700; padding:0 4px; border-radius:4px }
.scr-meta { display:flex; gap:14px; flex-wrap:wrap; margin-top:8px; font-size:11px;
  color:#898781 }
.scr-meta b { color:#0b0b0b; font-weight:600 }
.scr-ms { margin-left:auto; text-align:right; flex-shrink:0 }
.scr-ms .v { font-size:17px; font-weight:700; color:#0F6E56 }
.scr-ms .l { font-size:9px; color:#898781; text-transform:uppercase }
.scr-saved { display:flex; gap:7px; flex-wrap:wrap }
.scr-savedchip { display:inline-flex; align-items:center; gap:7px; background:white;
  border:0.5px solid #e1e0d9; border-radius:20px; padding:5px 7px 5px 12px; font-size:11.5px;
  cursor:pointer }
.scr-savedchip:hover { border-color:#185FA5; background:#F7FBFF }
.scr-savedchip .x { border:none; background:rgba(0,0,0,.06); border-radius:50%; width:17px;
  height:17px; line-height:15px; font-size:12px; padding:0; cursor:pointer }
.scr-wrow { display:flex; align-items:center; gap:9px; margin-bottom:8px }
.scr-wrow label { font-size:12px; flex:1 }
.scr-wrow input[type=range] { flex:1.4 }
.scr-wrow .pct { font-size:11px; font-weight:600; width:38px; text-align:right }
.scr-tablewrap { background:white; border:0.5px solid #e1e0d9; border-radius:12px;
  overflow-x:auto }
.scr-tablewrap td.hit { background:#E1F5EE; font-weight:600 }
</style>
"""


_SAVED_PANEL = """
<div style="margin-top:22px">
  <div style="font-size:11px;color:#898781;text-transform:uppercase;letter-spacing:.3px;
              margin-bottom:8px">Saved searches</div>
  <div id="scr-saved" class="scr-saved"></div>
</div>
"""


_MODALS = """
<dialog id="scr-modal-picker">
  <div class="modal-body" style="min-width:430px;max-width:520px">
    <h3>Add a condition</h3>
    <input id="scr-fieldsearch" placeholder="Filter fields…" oninput="scrRenderPicker()"
           style="width:100%;margin-bottom:10px">
    <div id="scr-fieldlist" style="max-height:270px;overflow-y:auto;
         border:0.5px solid #e1e0d9;border-radius:8px"></div>
    <div id="scr-condform" style="margin-top:12px;display:none">
      <div style="font-size:12px;font-weight:600;margin-bottom:8px" id="scr-condlabel"></div>
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
        <select id="scr-condop" onchange="scrPickerOpChanged()"></select>
        <span id="scr-condvaluewrap"></span>
        <label style="font-size:11px;display:flex;align-items:center;gap:5px">
          <input type="checkbox" id="scr-condneg"> NOT
        </label>
      </div>
      <div id="scr-condhint" style="font-size:11px;color:#898781;margin-top:8px"></div>
    </div>
    <div class="modal-actions">
      <button class="btn secondary" onclick="closeModal('scr-modal-picker')">Cancel</button>
      <button class="btn" onclick="scrAddCondition()">Add condition</button>
    </div>
  </div>
</dialog>

<dialog id="scr-modal-save">
  <form class="modal-body" onsubmit="scrSave(event)" style="min-width:340px">
    <h3>Save this search</h3>
    <input id="scr-savename" placeholder="e.g. AI Leaders" style="width:100%" required>
    <div style="font-size:11px;color:#898781;margin-top:8px" id="scr-savepreview"></div>
    <div class="modal-actions">
      <button type="button" class="btn secondary"
              onclick="closeModal('scr-modal-save')">Cancel</button>
      <button type="submit" class="btn">Save</button>
    </div>
  </form>
</dialog>

<dialog id="scr-modal-weights">
  <div class="modal-body" style="min-width:400px">
    <h3>Weighted composite</h3>
    <div style="font-size:11px;color:#898781;margin-bottom:14px">
      Ranks matches by a blend of these fields, independent of which
      conditions you filtered on. Pick “Weighted composite” in the Sort
      menu to order results by it.
    </div>
    <div id="scr-weightrows"></div>
    <div class="modal-actions">
      <button class="btn secondary" onclick="scrResetWeights()">Reset</button>
      <button class="btn" onclick="closeModal('scr-modal-weights');scrRun()">Apply</button>
    </div>
  </div>
</dialog>
"""


# The controller. Kept as one string (the app has no bundler and every other
# page does the same) but organised in the same order as the page reads:
# state, rules, presets/saved, run, render.
_JS = r"""
// ── state ───────────────────────────────────────────────────────────────────
// RULES is the single source of truth for the screen; every interaction
// mutates it and calls scrRun(), which re-posts the whole tree. There's no
// incremental filtering on the client — the engine owns matching, so the
// client never has a second opinion about what a rule means.
let META = null;
let RULES = { op: 'AND', negate: false, items: [] };
let WEIGHTS = {};
let LAST = null;
let VIEW = 'cards';
let PICKED = null;
let SUGI = -1;

function scrEsc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

async function scrInit() {
  try {
    const res = await fetch('/api/screener/meta');
    META = await res.json();
  } catch (e) { toast('Could not load screener fields', 'err'); return; }
  WEIGHTS = Object.assign({}, META.composite_defaults);
  document.getElementById('scr-universe').textContent = META.universe;
  scrRenderPresets();
  scrRenderSaved();
  scrRun();
}

// ── rules ───────────────────────────────────────────────────────────────────
function scrField(key) { return (META.fields || []).find(f => f.key === key); }

function scrAdd(conds, replace) {
  if (replace) RULES = { op: RULES.op, negate: false, items: [] };
  for (const c of conds) {
    // Same field+operator twice is a correction, not a second rule.
    const i = RULES.items.findIndex(
      x => !x.items && x.field === c.field && x.op === c.op);
    if (i >= 0) RULES.items[i] = c; else RULES.items.push(c);
  }
  scrRun();
}

function scrRemove(i) { RULES.items.splice(i, 1); scrRun(); }
function scrToggleJoin() { RULES.op = RULES.op === 'AND' ? 'OR' : 'AND'; scrRun(); }
function scrToggleNeg(i) {
  RULES.items[i].negate = !RULES.items[i].negate; scrRun();
}
function scrReset() {
  RULES = { op: 'AND', negate: false, items: [] };
  document.getElementById('scr-nl').value = '';
  scrRun();
}

function scrRenderRules() {
  const box = document.getElementById('scr-rules');
  if (!RULES.items.length) {
    box.innerHTML = '<div style="font-size:12px;color:#898781">' +
      'No conditions yet — pick a preset, type a search, or use ' +
      '<b>+ Add condition</b>. An empty screen lists the whole library.</div>';
    return;
  }
  const stats = {};
  (LAST && LAST.stats || []).forEach(s => { stats[s.index] = s; });
  const parts = RULES.items.map((c, i) => {
    const st = stats[i];
    // "alone: N" is how many tickers the rule matches by itself — the
    // cheapest way to see which rule is doing the damage.
    const n = st ? ` <span class="n">${st.alone}</span>` : '';
    const pill = `<span class="scr-pill${c.negate ? ' neg' : ''}" title="${
      st ? scrEsc(st.text) + ' — matches ' + st.alone + ' on its own; drop it and the screen returns ' + st.without : ''}">
        <span onclick="scrToggleNeg(${i})" style="cursor:pointer">${
          scrEsc(st ? st.text : (c.field || ''))}${n}</span>
        <button class="x" onclick="scrRemove(${i})">×</button></span>`;
    const join = i < RULES.items.length - 1
      ? `<span class="scr-joiner" onclick="scrToggleJoin()">${RULES.op}</span>` : '';
    return pill + join;
  });
  box.innerHTML = parts.join('') +
    '<div style="font-size:10px;color:#898781;margin-top:7px">' +
    'Click a pill to negate it · click ' + RULES.op + ' to switch to ' +
    (RULES.op === 'AND' ? 'OR' : 'AND') + ' · the small number is how many ' +
    'tickers that rule matches on its own</div>';
}

// ── presets & saved ─────────────────────────────────────────────────────────
function scrRenderPresets() {
  document.getElementById('scr-presets').innerHTML = (META.presets || []).map(p =>
    `<div class="scr-preset" onclick="scrApplyPreset('${p.key}')"
          title="${scrEsc(p.pills.join('  AND  '))}">
       <b>${p.icon} ${scrEsc(p.name)}</b><span>${scrEsc(p.desc)}</span></div>`).join('');
}

function scrApplyPreset(key) {
  const p = (META.presets || []).find(x => x.key === key);
  if (!p) return;
  RULES = { op: 'AND', negate: false, items: p.conditions.map(c => Object.assign({}, c)) };
  document.getElementById('scr-nl').value = '';
  scrRun();
}

function scrRenderSaved() {
  const box = document.getElementById('scr-saved');
  const saved = (META && META.saved) || [];
  if (!saved.length) {
    box.innerHTML = '<div style="font-size:12px;color:#898781">' +
      'Nothing saved yet — build a screen and hit ☆ Save search.</div>';
    return;
  }
  box.innerHTML = saved.map(s =>
    `<span class="scr-savedchip">
       <span onclick="scrLoadSaved('${scrEsc(s.name)}')">${s.icon || '⭐'} ${scrEsc(s.name)}</span>
       <button class="x" onclick="scrDeleteSaved('${scrEsc(s.name)}')">×</button></span>`).join('');
}

function scrLoadSaved(name) {
  const s = (META.saved || []).find(x => x.name === name);
  if (!s) return;
  RULES = JSON.parse(JSON.stringify(s.rules || { op: 'AND', items: [] }));
  if (!RULES.items) RULES = { op: 'AND', negate: false, items: [] };
  if (s.sort) document.getElementById('scr-sort').value = s.sort;
  document.getElementById('scr-nl').value = '';
  scrRun();
}

function scrOpenSave() {
  document.getElementById('scr-savepreview').textContent =
    RULES.items.length ? (LAST ? LAST.pills.map(p => p.text).join('  ' + RULES.op + '  ') : '')
                       : 'This screen has no conditions.';
  openModal('scr-modal-save');
}

async function scrSave(ev) {
  ev.preventDefault();
  const name = document.getElementById('scr-savename').value.trim();
  if (!name) return false;
  const res = await fetch('/api/screener/save', {
    method: 'POST',
    body: JSON.stringify({ name, rules: RULES,
                           sort: document.getElementById('scr-sort').value }),
  });
  const data = await res.json();
  if (data.ok) { META.saved = data.saved; scrRenderSaved(); toast(data.message, 'ok'); }
  else toast(data.message || 'Save failed', 'err');
  closeModal('scr-modal-save');
  document.getElementById('scr-savename').value = '';
  return false;
}

async function scrDeleteSaved(name) {
  const res = await fetch('/api/screener/delete', {
    method: 'POST', body: JSON.stringify({ name }),
  });
  const data = await res.json();
  if (data.ok) { META.saved = data.saved; scrRenderSaved(); toast(data.message, 'ok'); }
  else toast(data.message || 'Delete failed', 'err');
}

// ── natural language ────────────────────────────────────────────────────────
let scrSugTimer = null;
function scrOnType(v) {
  clearTimeout(scrSugTimer);
  scrSugTimer = setTimeout(() => scrSuggest(v), 140);
}

async function scrSuggest(q) {
  const box = document.getElementById('scr-suggest');
  const term = (q || '').trim();
  // Only suggest on the last clause — "turnaround and qual" should offer
  // quality, not re-offer turnaround.
  const tail = term.split(/,|\band\b|\+/).pop().trim();
  if (tail.length < 2) { box.style.display = 'none'; return; }
  try {
    const res = await fetch('/api/screener/suggest?q=' + encodeURIComponent(tail));
    const rows = await res.json();
    if (!rows.length) { box.style.display = 'none'; return; }
    SUGI = -1;
    box.innerHTML = rows.map((r, i) =>
      `<div class="scr-sug" data-i="${i}" onclick="scrPickSuggestion(${i})">
         <span>${scrEsc(r.label)}</span><span class="k">${r.kind}</span></div>`).join('');
    box._rows = rows;
    box.style.display = 'block';
  } catch (e) { box.style.display = 'none'; }
}

function scrPickSuggestion(i) {
  const box = document.getElementById('scr-suggest');
  const r = (box._rows || [])[i];
  box.style.display = 'none';
  if (!r) return;
  // A suggestion with no threshold set (e.g. "Quality Score…") is an
  // invitation to pick one, not a rule — open the picker on that field.
  const bare = r.conditions.filter(c => c.value === null || c.value === undefined);
  if (bare.length === 1 && r.conditions.length === 1) {
    document.getElementById('scr-nl').value = '';
    scrOpenPicker(bare[0].field);
    return;
  }
  document.getElementById('scr-nl').value = '';
  scrAdd(r.conditions.map(c => Object.assign({}, c)), false);
}

function scrRunNL() {
  const q = document.getElementById('scr-nl').value.trim();
  document.getElementById('scr-suggest').style.display = 'none';
  if (!q) { scrRun(); return; }
  scrRun({ query: q });
}

document.addEventListener('keydown', (e) => {
  const box = document.getElementById('scr-suggest');
  if (!box || box.style.display === 'none') return;
  const rows = box.querySelectorAll('.scr-sug');
  if (!rows.length) return;
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault();
    SUGI = (SUGI + (e.key === 'ArrowDown' ? 1 : rows.length - 1)) % rows.length;
    rows.forEach((r, i) => r.classList.toggle('on', i === SUGI));
  } else if (e.key === 'Enter' && SUGI >= 0) {
    e.preventDefault(); scrPickSuggestion(SUGI);
  } else if (e.key === 'Escape') { box.style.display = 'none'; }
});
document.addEventListener('click', (e) => {
  const box = document.getElementById('scr-suggest');
  if (box && !e.target.closest('#scr-nl') && !e.target.closest('#scr-suggest'))
    box.style.display = 'none';
});

// ── field picker ────────────────────────────────────────────────────────────
function scrOpenPicker(preselect) {
  document.getElementById('scr-fieldsearch').value = '';
  PICKED = null;
  document.getElementById('scr-condform').style.display = 'none';
  scrRenderPicker();
  openModal('scr-modal-picker');
  if (preselect) scrPickField(preselect);
}

function scrRenderPicker() {
  const q = document.getElementById('scr-fieldsearch').value.trim().toLowerCase();
  const list = document.getElementById('scr-fieldlist');
  let html = '';
  for (const g of META.groups) {
    const fields = META.fields.filter(f => f.group === g &&
      (!q || f.label.toLowerCase().includes(q) || f.key.includes(q)));
    if (!fields.length) continue;
    html += `<div style="font-size:10px;text-transform:uppercase;letter-spacing:.3px;
              color:#898781;padding:7px 12px 4px;background:#faf9f5">${g}</div>`;
    html += fields.map(f =>
      `<div onclick="scrPickField('${f.key}')" style="padding:7px 12px;font-size:12px;
            cursor:pointer;border-top:0.5px solid #f1efea"
            onmouseover="this.style.background='#E6F1FB'"
            onmouseout="this.style.background=''">
         ${scrEsc(f.label)}${f.hint ? '<div style="font-size:10px;color:#898781">' +
           scrEsc(f.hint) + '</div>' : ''}</div>`).join('');
  }
  list.innerHTML = html || '<div style="padding:14px;font-size:12px;color:#898781">no fields match</div>';
}

function scrPickField(key) {
  const f = scrField(key);
  if (!f) return;
  PICKED = f;
  document.getElementById('scr-condform').style.display = 'block';
  document.getElementById('scr-condlabel').textContent = f.label;
  document.getElementById('scr-condhint').textContent = f.hint || '';
  document.getElementById('scr-condop').innerHTML = f.ops.map(o =>
    `<option value="${o}">${scrEsc(META.operators[o] || o)}</option>`).join('');
  scrPickerOpChanged();
}

function scrPickerOpChanged() {
  const f = PICKED;
  if (!f) return;
  const op = document.getElementById('scr-condop').value;
  const wrap = document.getElementById('scr-condvaluewrap');
  if (f.kind === 'bool') {
    wrap.innerHTML = `<select id="scr-condvalue">
        <option value="true">Yes</option><option value="false">No</option></select>`;
  } else if (f.kind === 'enum') {
    const vals = (META.enums && META.enums[f.key]) || f.values || [];
    wrap.innerHTML = `<select id="scr-condvalue">${vals.map(v =>
      `<option value="${scrEsc(v)}">${scrEsc(v)}</option>`).join('')}</select>`;
  } else if (op === 'between') {
    wrap.innerHTML = `<input id="scr-condvalue" type="number" step="any" placeholder="from"
        style="width:88px"> <input id="scr-condvalue2" type="number" step="any"
        placeholder="to" style="width:88px">`;
  } else {
    wrap.innerHTML = `<input id="scr-condvalue" type="number" step="any"
        placeholder="value" style="width:104px">${f.unit ?
        ' <span style="font-size:11px;color:#898781">' + scrEsc(f.unit) + '</span>' : ''}`;
  }
}

function scrAddCondition() {
  if (!PICKED) { toast('Pick a field first', 'err'); return; }
  const op = document.getElementById('scr-condop').value;
  const el = document.getElementById('scr-condvalue');
  let value = el ? el.value : null;
  if (PICKED.kind === 'bool') value = value === 'true';
  else if (PICKED.kind !== 'enum') {
    if (value === '' || value === null) { toast('Enter a value', 'err'); return; }
    value = parseFloat(value);
    if (isNaN(value)) { toast('Enter a number', 'err'); return; }
  }
  const cond = { field: PICKED.key, op, value,
                 negate: document.getElementById('scr-condneg').checked };
  const v2 = document.getElementById('scr-condvalue2');
  if (v2 && v2.value !== '') cond.value2 = parseFloat(v2.value);
  document.getElementById('scr-condneg').checked = false;
  closeModal('scr-modal-picker');
  scrAdd([cond], false);
}

// ── weights ─────────────────────────────────────────────────────────────────
function scrOpenWeights() {
  const box = document.getElementById('scr-weightrows');
  const keys = Object.keys(WEIGHTS);
  box.innerHTML = keys.map(k => {
    const f = scrField(k);
    return `<div class="scr-wrow">
      <label>${scrEsc(f ? f.label : k)}</label>
      <input type="range" min="0" max="100" value="${WEIGHTS[k]}"
             oninput="scrSetWeight('${k}', this.value)">
      <span class="pct" id="scr-w-${k}">${WEIGHTS[k]}%</span></div>`;
  }).join('');
  openModal('scr-modal-weights');
}
function scrSetWeight(k, v) {
  WEIGHTS[k] = parseFloat(v);
  document.getElementById('scr-w-' + k).textContent = v + '%';
}
function scrResetWeights() {
  WEIGHTS = Object.assign({}, META.composite_defaults);
  scrOpenWeights();
}

// ── run ─────────────────────────────────────────────────────────────────────
let scrSeq = 0;
async function scrRun(extra) {
  const seq = ++scrSeq;
  const payload = Object.assign({
    rules: RULES, composite: WEIGHTS,
    sort: document.getElementById('scr-sort').value, limit: 200,
  }, extra || {});
  document.getElementById('scr-livecount').textContent = '…';
  let data;
  try {
    const res = await fetch('/api/screen', {
      method: 'POST', body: JSON.stringify(payload),
    });
    data = await res.json();
  } catch (e) {
    document.getElementById('scr-results').innerHTML =
      '<div class="scr-empty">Request failed — is the server still running?</div>';
    return;
  }
  // A slow earlier request must not overwrite a newer result.
  if (seq !== scrSeq) return;
  if (!data.ok) { toast(data.message || 'Screen failed', 'err'); return; }
  LAST = data;
  // A natural-language search comes back as real rules, so the pills and
  // every later edit operate on what the parser actually understood.
  if (extra && extra.query) RULES = data.rules;
  scrRenderRules();
  scrRenderSummary(data);
  scrRenderResults(data);
}

// ── render ──────────────────────────────────────────────────────────────────
function scrRenderSummary(d) {
  document.getElementById('scr-livecount').textContent =
    d.count + ' / ' + d.universe;
  document.getElementById('scr-resulttitle').textContent =
    d.count === 0 ? 'No stocks matched'
                  : 'Found ' + d.count + ' stock' + (d.count === 1 ? '' : 's') +
                    (d.shown < d.count ? ' — showing top ' + d.shown : '');

  const s = d.summary || {};
  const tiles = [
    ['Avg Quality', s.avg_quality], ['Avg Health', s.avg_health],
    ['Avg EPS Growth', s.avg_eps_growth, '%'], ['Avg RS', s.avg_rs],
    ['Avg Conviction', s.avg_conviction],
    ['Avg Breakout', s.avg_breakout, '%'],
  ].filter(t => t[1] !== null && t[1] !== undefined);
  let html = '';
  if (d.count) {
    html = '<div class="scr-stats">' + tiles.map(t =>
      `<div class="scr-stat"><div class="v">${t[1]}${t[2] || ''}</div>
         <div class="l">${t[0]}</div></div>`).join('') +
      `<div class="scr-stat"><div class="v">${s.above_200ma}</div>
         <div class="l">Above 200MA</div></div>
       <div class="scr-stat"><div class="v">${s.in_buy_zone}</div>
         <div class="l">In Buy Zone</div></div>
       <div class="scr-stat"><div class="v">${s.earnings_soon}</div>
         <div class="l">Earnings ≤7d</div></div></div>`;
  }
  document.getElementById('scr-summary').innerHTML = html;

  // Coverage gaps, always shown when they exist: a rule on a field that
  // half the library lacks silently excludes those names, and that looks
  // exactly like a real rejection unless we say so.
  const miss = (d.missing || []).filter(m => m.rows > 0);
  let notes = miss.length
    ? '<div class="scr-note">⚠ Excluded for missing data: ' + miss.map(m =>
        `<b>${scrEsc(m.label)}</b> — no value for ${m.rows} of ${d.universe} tickers`)
        .join(' · ') + '. These are not rejections; the library has no data ' +
        'for them on this field.</div>'
    : '';
  // If the live index lost data and the snapshot is carrying the screen,
  // say so up front — the results are usable but not all of them are live.
  const rec = (d.summary || {}).recovered || 0;
  if (rec) {
    notes += `<div class="scr-note">↺ <b>${rec}</b> of ${d.count} result` +
      (d.count === 1 ? '' : 's') + ' came from the durable snapshot because ' +
      'the research index has no data for them. Values are real but as of ' +
      'their last good scan — each is badged with its date. Run a scan or ' +
      'Refresh Research to bring them current.</div>';
  }
  document.getElementById('scr-missing').innerHTML = notes;

  const ref = d.refine || [];
  document.getElementById('scr-refine').innerHTML = ref.length
    ? '<div class="scr-refine"><b>Refine:</b>' + ref.map((r, i) =>
        `<span>${scrEsc(r.why)}</span>
         <button class="btn secondary" style="padding:4px 10px"
           onclick='scrAdd(${JSON.stringify(r.conditions)}, false)'>${scrEsc(r.label)}</button>`)
        .join('') + '</div>'
    : '';
}

function scrToggleView() {
  VIEW = VIEW === 'cards' ? 'table' : 'cards';
  document.getElementById('scr-viewbtn').textContent =
    VIEW === 'cards' ? 'Table view' : 'Card view';
  if (LAST) scrRenderResults(LAST);
}

function scrRenderResults(d) {
  const box = document.getElementById('scr-results');
  if (!d.results.length) {
    box.innerHTML = scrEmptyHelp(d);
    return;
  }
  box.innerHTML = VIEW === 'cards'
    ? d.results.map(scrCard).join('')
    : scrTable(d);
}

// An empty result is a question ("why?"), so answer it with the engine's
// per-condition stats instead of a shrug.
function scrEmptyHelp(d) {
  const stats = (d.stats || []).slice().sort((a, b) => a.alone - b.alone);
  if (!stats.length) return '<div class="scr-empty">No stocks matched.</div>';
  const rows = stats.map(s =>
    `<tr><td>${scrEsc(s.text)}</td>
       <td style="text-align:right">${s.alone}</td>
       <td style="text-align:right">${s.without}</td>
       <td style="text-align:right;color:#898781">${s.missing || 0}</td></tr>`).join('');
  const tightest = stats[0];
  return `<div class="scr-empty" style="text-align:left">
    <div style="font-size:13px;font-weight:600;margin-bottom:4px;color:#0b0b0b">
      No stocks matched all ${stats.length} conditions.</div>
    <div style="margin-bottom:12px">Tightest rule:
      <b style="color:#0b0b0b">${scrEsc(tightest.text)}</b> — only
      ${tightest.alone} of ${d.universe} tickers pass it on its own.</div>
    <table><thead><tr><th>Condition</th><th style="text-align:right">Matches alone</th>
      <th style="text-align:right">Screen without it</th>
      <th style="text-align:right">No data</th></tr></thead>
      <tbody>${rows}</tbody></table>
    <div style="margin-top:10px;font-size:11px">Remove or loosen the rule whose
      “screen without it” column is highest — that's the one costing you the most.</div>
  </div>`;
}

function scrNum(v, nd, unit) {
  if (v === null || v === undefined) return '—';
  return Number(v).toFixed(nd === undefined ? 1 : nd) + (unit || '');
}

function scrBig(v) {
  if (v === null || v === undefined) return '—';
  const a = Math.abs(v);
  for (const [cut, s] of [[1e12, 'T'], [1e9, 'B'], [1e6, 'M']])
    if (a >= cut) return '$' + (v / cut).toFixed(1) + s;
  return '$' + Math.round(v);
}

function scrCard(r) {
  const why = (r.why || []).map(w =>
    `<div class="${w.passed ? '' : 'no'}">${w.passed ? '✓' : '✗'} ${scrEsc(w.text)}</div>`
  ).join('');
  const stars = r.conv_stars ? '★'.repeat(r.conv_stars) + '☆'.repeat(5 - r.conv_stars) : '';
  const meta = [
    ['Price', r.price === null ? '—' : '$' + scrNum(r.price, 2)],
    ['Quality', r.quality === null ? '—' : r.quality],
    ['Health', r.health === null ? '—' : r.health],
    ['Moat', r.moat === null ? '—' : r.moat + '/' + (r.moat_total || 4)],
    ['RS', r.rs_rank === null ? '—' : r.rs_rank],
    ['EPS gr', r.eps_growth === null ? '—' : scrNum(r.eps_growth, 0, '%')],
    ['Fwd P/E', r.forward_pe === null ? '—' : scrNum(r.forward_pe, 1)],
    ['Inst', r.inst_own === null ? '—' : scrNum(r.inst_own, 0, '%')],
  ].map(m => `<span>${m[0]} <b>${m[1]}</b></span>`).join('');
  const tags = [
    r.category, r.grade ? 'Grade ' + r.grade : '',
    r.in_buy_zone ? 'Buy Zone' : '', r.above_200ma ? '>200MA' : '',
    r.earnings_soon ? '⚠ earnings ≤7d' : '',
  ].filter(Boolean).map(t =>
    `<span class="chip" style="margin:0">${scrEsc(t)}</span>`).join(' ');
  // Recovered rows are real data from an earlier scan, not live values —
  // label them so a stale price is never read as a current one.
  const recovered = r.recovered
    ? `<span class="chip" style="margin:0;background:#FAEEDA;color:#633806"
         title="The live index had no data for this ticker; these values come from the durable snapshot, as of ${scrEsc(r.data_as_of || 'an earlier scan')}">
         ↺ as of ${scrEsc((r.data_as_of || '').slice(0, 16) || 'earlier scan')}</span>`
    : '';
  // The scan falls back to the ticker for LongName when yfinance has no
  // company name, so showing both would read "MU  MU".
  const name = (r.name && r.name !== r.ticker) ? r.name : '';
  return `<div class="scr-card">
    <div class="scr-cardtop">
      <a class="scr-tk" href="/research/${scrEsc(r.ticker)}.html">${scrEsc(r.ticker)}</a>
      <span style="font-size:11.5px;color:#898781;max-width:230px;overflow:hidden;
        text-overflow:ellipsis;white-space:nowrap">${scrEsc(name)}</span>
      ${tags}${recovered}
      <span style="font-size:11px;color:#8a6d1a">${stars}</span>
      <div class="scr-ms"><div class="v">${r.match_score}</div>
        <div class="l">match</div></div>
    </div>
    <div class="scr-meta">${meta}</div>
    <div class="scr-why">${why}</div>
  </div>`;
}

// The table shows the fields the screen filtered on, highlighted — so the
// numbers you asked about are the numbers on screen.
function scrTable(d) {
  const cols = [];
  const seen = new Set();
  for (const p of (d.pills || [])) {
    if (seen.has(p.field)) continue;
    seen.add(p.field);
    const f = scrField(p.field);
    if (f) cols.push(f);
  }
  const head = cols.map(c => `<th>${scrEsc(c.label)}</th>`).join('');
  const rows = d.results.map(r => {
    const cells = cols.map(c => {
      const v = r[c.key];
      // Precision comes from the field registry — rounding Forward P/E to
      // a whole number turns 5.9 into "6" and loses the point of the filter.
      const txt = v === null || v === undefined ? '—'
        : (typeof v === 'boolean' ? (v ? 'Yes' : 'No')
          : (typeof v === 'number'
             ? (c.unit === '$' ? scrBig(v) : scrNum(v, c.decimals, c.unit))
             : scrEsc(v)));
      const hit = (r.matched_fields || []).includes(c.key);
      return `<td class="${hit ? 'hit' : ''}">${txt}</td>`;
    }).join('');
    return `<tr><td><a href="/research/${scrEsc(r.ticker)}.html"><b>${scrEsc(r.ticker)}</b></a></td>
      <td style="text-align:right;font-weight:600;color:#0F6E56">${r.match_score}</td>
      ${cells}<td>${scrEsc(r.category || '')}</td></tr>`;
  }).join('');
  return `<div class="scr-tablewrap"><table>
    <thead><tr><th>Ticker</th><th style="text-align:right">Match</th>
      ${head}<th>Category</th></tr></thead>
    <tbody>${rows}</tbody></table></div>`;
}

document.addEventListener('DOMContentLoaded', scrInit);
"""
