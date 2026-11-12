/* pySTREAM in the browser: shows the pages and sends the user's changes to the model (pySTREAM_web.py). */
'use strict';

const FONT = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif';
const NARROW_CHART = 480; // charts narrower than this (in pixels) get their legend above the plot

const PAGES = {
  graphs:      { title: 'Graphs', subtitle: () => 'Base year & scenario', data: 'graphs', render: renderGraphs, icon: 'M4 19V9m6 10V5m6 14v-7m4 7H2' },
  consumption: { title: 'Edit consumption', subtitle: () => 'Scenario', render: renderConsumption, icon: 'M4 20h16M6 16l4-6 4 3 4-7', group: 'Edit' },
  production:  { title: 'Edit production', subtitle: () => 'Scenario', data: 'production', render: renderProduction, icon: 'M13 2 4 14h7l-1 8 9-12h-7z' },
  base_year:   { title: 'Base year data', subtitle: () => state.inputs.base_year, data: 'base_year', render: renderYearData, icon: 'M4 5h16v15H4zM4 10h16M9 5V3m6 2V3', group: 'Results' },
  scenario:    { title: 'Scenario data', subtitle: () => state.inputs.scenario_year, data: 'scenario', render: renderYearData, icon: 'M4 5h16v15H4zM4 10h16m-8 4h4' },
  transport:   { title: 'Transport data', subtitle: () => 'Base year & scenario', data: 'transport', render: renderTransport, icon: 'M3 16V8h11v8M14 11h4l3 3v2h-7M7 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4zm10 0a2 2 0 1 0 0-4 2 2 0 0 0 0 4z' },
  co2:         { title: 'CO2 emissions', subtitle: () => 'Base year & scenario', data: 'co2', render: renderCO2, icon: 'M7 18a5 5 0 1 1 1-9.9A6 6 0 0 1 19 10a4 4 0 0 1-1 8z' },
  economy:     { title: 'Economy', subtitle: () => 'Base year & scenario', data: 'economy', render: renderEconomy, icon: 'M12 3v18m4-14H10a2.5 2.5 0 0 0 0 5h4a2.5 2.5 0 0 1 0 5H7' },
  timeseries:  { title: 'Time series', subtitle: () => 'Scenario', data: 'timeseries', render: renderTimeSeries, icon: 'M3 12h4l3-8 4 16 3-8h4' },
};

const state = {
  page: 'graphs',
  inputs: null,      // the scenario's editable values, as last calculated
  draft: {},         // changes not calculated yet: key -> value
  draftYear: null,
  pageData: {},      // page data, cleared when the scenario changes
  ui: { graph: 'sankey', fecUnit: {}, prodUnit: {}, transportUnit: {}, average: 'week', showAllFuels: false },
};
let pendingCharts = [];
let sumUpdaters = [];

// Small helpers ----------------------------------------------------------------
const $ = (selector) => document.querySelector(selector);

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value == null || value === false) continue;
    if (key === 'class') el.className = value;
    else if (key.startsWith('on')) el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? '' : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child == null || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

function icon(path) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('width', '18'); svg.setAttribute('height', '18'); svg.setAttribute('aria-hidden', 'true');
  const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  p.setAttribute('d', path); p.setAttribute('fill', 'none'); p.setAttribute('stroke', 'currentColor');
  p.setAttribute('stroke-width', '1.8'); p.setAttribute('stroke-linecap', 'round'); p.setAttribute('stroke-linejoin', 'round');
  svg.append(p);
  return svg;
}

const pct = (v, d = 2) => (v * 100).toFixed(d) + '%';
const fix = (v, d) => Number(v).toFixed(d);
const sum = (values) => values.reduce((a, b) => a + b, 0);
const isHundred = (v) => Math.abs(v - 1) <= 1e-6; // the same check as when the scenario is updated

function debounce(fn, ms) {
  let timer;
  return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), ms); };
}

// Talking to pySTREAM --------------------------------------------------------------
async function api(path, { method = 'GET', body, raw = false } = {}) {
  let response;
  try {
    response = await fetch(path, {
      method,
      headers: body !== undefined && !raw ? { 'Content-Type': 'application/json' } : {},
      body: body === undefined ? undefined : (raw ? body : JSON.stringify(body)),
    });
  } catch (e) {
    throw notRunning();
  }
  let data;
  try { data = await response.json(); } catch (e) { throw notRunning(); }
  if (!response.ok || data.error) throw data.error || { title: 'pySTREAM', message: 'Something went wrong (' + response.status + ').' };
  return data;
}

function notRunning() {
  return { title: 'pySTREAM is not running',
           message: 'The page cannot reach pySTREAM: it was closed.\n\nStart it again by double-clicking "pySTREAM Mac" (macOS) or "pySTREAM Windows.bat" (Windows).' };
}

// Telling pySTREAM that this page is open ------------------------------------------------
// pySTREAM stops by itself a minute after its last page was closed (it may run without a window).
const PAGE_ID = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : String(Math.random()).slice(2) + Date.now();
let closedOnPurpose = false;

async function hello() {
  if (closedOnPurpose) return;
  try {
    const response = await fetch('/api/hello', { method: 'POST', body: PAGE_ID });
    if (!response.ok) throw new Error(String(response.status));
    $('#not-running').hidden = true;
  } catch (e) {
    $('#not-running').hidden = false;
  }
}

function bye() {
  if (navigator.sendBeacon) navigator.sendBeacon('/api/bye', PAGE_ID);
}

function startHello() {
  hello();
  setInterval(hello, 60 * 1000);
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') hello(); });
  window.addEventListener('pagehide', bye);
  window.addEventListener('pageshow', (e) => { if (e.persisted) hello(); });
}

async function closePySTREAM() {
  const message = changeCount() > 0
    ? 'Some changes are not calculated yet and will be lost. (Everything you calculated with "Update scenario" is saved.)'
    : 'Your scenario is saved. You can start pySTREAM again at any time.';
  if (!await confirmDialog('Close pySTREAM?', message, 'Close pySTREAM')) return;
  closedOnPurpose = true;
  try { await fetch('/api/quit', { method: 'POST', body: '' }); } catch (e) { /* already closed */ }
  window.removeEventListener('beforeunload', warnBeforeLeaving);
  document.body.replaceChildren(h('div', { class: 'closed-screen' }, h('div', { class: 'card' },
    h('h1', null, 'pySTREAM is closed'),
    h('p', null, 'You can close this tab now.'),
    h('p', null, 'To use pySTREAM again, double-click "pySTREAM Mac" (macOS) or "pySTREAM Windows.bat" (Windows) in the pySTREAM folder.'))));
  document.title = 'pySTREAM is closed';
}

function warnBeforeLeaving(e) {
  if (changeCount() > 0) { e.preventDefault(); e.returnValue = ''; }
}

// Busy indicator, dialogs and short messages -------------------------------------------
let busyCount = 0;
function busy(message) {
  busyCount++;
  $('#busy-text').textContent = message;
  $('#busy').hidden = false;
  document.body.style.cursor = 'progress';
}
function unbusy() {
  busyCount = Math.max(0, busyCount - 1);
  if (!busyCount) { $('#busy').hidden = true; document.body.style.cursor = ''; }
}

// Messages are shown one at a time: a message that comes while another is open waits until that one is closed
let dialogQueue = Promise.resolve();
function dialog(title, message, buttons, kind) {
  const shown = dialogQueue.then(() => showDialog(title, message, buttons, kind));
  dialogQueue = shown.catch(() => {});
  return shown;
}

function showDialog(title, message, buttons = [{ label: 'OK', value: true, primary: true }], kind = '') {
  return new Promise((resolve) => {
    const dlg = $('#dialog');
    dlg.querySelector('.dialog-body').className = 'dialog-body ' + kind;
    $('#dialog-title').textContent = title;
    $('#dialog-message').textContent = message;
    const box = $('#dialog-buttons');
    box.replaceChildren(...buttons.map((b) => h('button', { class: 'btn' + (b.primary ? ' primary' : ''), value: String(b.value), type: 'submit' }, b.label)));
    dlg.onclose = () => resolve(dlg.returnValue === 'true');
    dlg.returnValue = 'false';
    dlg.showModal();
    const primary = box.querySelector('.primary');
    if (primary) primary.focus();
  });
}
const showError = (e) => dialog(e.title || 'pySTREAM', e.message || String(e), undefined, 'error');
const confirmDialog = (title, message, yes) => dialog(title, message, [{ label: 'Cancel', value: false }, { label: yes, value: true, primary: true }]);

function toast(message, kind = '') {
  const el = h('div', { class: 'toast ' + kind }, message);
  $('#toasts').append(el);
  setTimeout(() => el.remove(), kind === 'error' ? 6000 : 3000);
}

async function showWarnings(warnings) {
  for (const w of warnings || []) await dialog(w.title, w.message);
}

// Changes that are not calculated yet ------------------------------------------------
const val = (key, original) => (key in state.draft ? state.draft[key] : original);
const changeCount = () => Object.keys(state.draft).length + (state.draftYear !== null ? 1 : 0);

function onDraftChanged() {
  const n = changeCount();
  $('#dirty').hidden = n === 0;
  $('#dirty-text').textContent = n === 1 ? '1 change not calculated yet' : n + ' changes not calculated yet';
  $('#btn-update').classList.toggle('attention', n > 0);
  $('#year').classList.toggle('changed', state.draftYear !== null);
  runSumUpdaters();
}

function runSumUpdaters() { for (const update of sumUpdaters) update(); }

function discardChanges() {
  state.draft = {};
  state.draftYear = null;
  $('#year').value = state.inputs.scenario_year;
  onDraftChanged();
  renderPage();
}

function buildChanges() {
  const changes = {};
  const put = (group, a, b, value) => {
    changes[group] = changes[group] || {};
    if (b === undefined) changes[group][a] = value;
    else { changes[group][a] = changes[group][a] || {}; changes[group][a][b] = value; }
  };
  const groups = { heat: 'heat', tf: 'transport_fuels', alloc: 'allocation', util: 'utilisation', el: 'electricity', dh: 'district_heat', price: 'prices' };
  for (const [key, value] of Object.entries(state.draft)) {
    const [kind, a, b] = key.split('|');
    if (kind === 'co2') changes.co2_price = value;
    else put(groups[kind], a, b, value);
  }
  if (state.draftYear !== null) changes.scenario_year = state.draftYear;
  return changes;
}

// Main actions --------------------------------------------------------------------------
function scenarioChanged(result) {
  state.inputs = result.inputs;
  state.draft = {};
  state.draftYear = null;
  state.pageData = {};
  $('#year').value = state.inputs.scenario_year;
  onDraftChanged();
}

async function updateScenario() {
  if (document.activeElement && document.activeElement.classList.contains('cell-input')) document.activeElement.blur(); // keep what is being typed
  busy(state.draftYear !== null ? 'Updating the scenario year…' : 'Updating the scenario…');
  let result;
  try {
    result = await api('/api/update', { method: 'POST', body: buildChanges() });
  } catch (e) {
    unbusy();
    await showError(e);
    return false;
  }
  unbusy();
  scenarioChanged(result);
  toast('Scenario updated');
  await renderPage();
  await showWarnings(result.warnings);
  return true;
}

async function saveScenarioAs() {
  if (changeCount() > 0) {
    if (!await confirmDialog('Update the scenario first?', 'Some changes are not calculated yet. pySTREAM updates the scenario with them and then saves it.', 'Update and save')) return;
    if (!await updateScenario()) return;
  }
  busy('Saving the scenario…');
  let blob;
  try {
    const response = await fetch('/api/download-scenario');
    if (!response.ok) { const data = await response.json(); throw data.error; }
    blob = await response.blob();
  } catch (e) {
    unbusy();
    showError(e && e.title ? e : notRunning());
    return;
  }
  unbusy();
  if (window.showSaveFilePicker) { // Chrome and Edge: choose where to save it
    try {
      const handle = await window.showSaveFilePicker({ suggestedName: 'My scenario.xlsx',
        types: [{ description: 'Excel workbook', accept: { 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'] } }] });
      const writable = await handle.createWritable();
      await writable.write(blob);
      await writable.close();
      dialog('Scenario saved', 'The scenario was saved as "' + handle.name + '".\n\nUse "Open scenario…" to continue with it later.');
      return;
    } catch (e) {
      if (e.name === 'AbortError') return; // cancelled
    }
  }
  const link = h('a', { href: URL.createObjectURL(blob), download: 'My scenario.xlsx' });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 10000);
  dialog('Scenario saved', 'The scenario was saved as "My scenario.xlsx" in your Downloads folder (or where your browser saves downloads).\n\nUse "Open scenario…" to continue with it later.');
}

async function openScenario() {
  if (changeCount() > 0 && !await confirmDialog('Open another scenario?', 'Your changes that are not calculated yet will be lost.', 'Open scenario')) return;
  $('#file-input').click();
}

async function openScenarioFile(file) {
  busy('Opening ' + file.name + '…');
  try {
    const result = await api('/api/open-scenario', { method: 'POST', body: await file.arrayBuffer(), raw: true });
    unbusy();
    scenarioChanged(result);
    await renderPage();
    toast('Opened ' + file.name);
    await showWarnings(result.warnings);
  } catch (e) {
    unbusy();
    showError(e);
  }
}

async function resetScenario() {
  if (!await confirmDialog('Reset to default scenario', 'This replaces the current scenario with the default scenario that comes with pySTREAM.\n\nTo keep the current scenario, choose Cancel and use "Save scenario as…" first.', 'Reset now')) return;
  busy('Calculating the default scenario…');
  try {
    const result = await api('/api/reset', { method: 'POST', body: {} });
    unbusy();
    scenarioChanged(result);
    await renderPage();
    toast('Default scenario restored');
    await showWarnings(result.warnings);
  } catch (e) {
    unbusy();
    showError(e);
  }
}

// Navigation and page rendering -------------------------------------------------------
function buildNav() {
  const nav = $('#nav');
  for (const [name, page] of Object.entries(PAGES)) {
    if (page.group) nav.append(h('div', { class: 'nav-group' }, page.group));
    nav.append(h('button', { class: 'nav-btn', type: 'button', 'data-page': name, onclick: () => { location.hash = name; closeMenu(); } }, icon(page.icon), page.title));
  }
}

function go(name) {
  state.page = PAGES[name] ? name : 'graphs';
  renderPage();
}

async function renderPage() {
  const name = state.page;
  const page = PAGES[name];
  document.querySelectorAll('.nav-btn').forEach((b) => b.classList.toggle('active', b.dataset.page === name));
  $('#page-title').textContent = page.title;
  $('#page-subtitle').textContent = page.subtitle();
  document.title = page.title + ' – pySTREAM';
  const root = $('#content');
  let data = null;
  if (page.data) {
    data = state.pageData[page.data];
    if (!data) {
      const slow = page.data === 'timeseries';
      if (slow) busy('Calculating the time series…\nThis can take up to a minute.');
      else root.replaceChildren(h('div', { class: 'loading' }, 'Loading…'));
      try {
        data = await api('/api/page/' + page.data);
        state.pageData[page.data] = data;
      } catch (e) {
        if (slow) unbusy();
        root.replaceChildren(h('div', { class: 'loading' }, 'This page could not be shown.'));
        showError(e);
        return;
      }
      if (slow) unbusy();
    }
  }
  if (state.page !== name) return; // another page was chosen in the meantime
  pendingCharts = [];
  sumUpdaters = [];
  const scrollY = name === lastRenderedPage ? window.scrollY : 0; // stay in place when the same page is drawn again
  lastRenderedPage = name;
  root.replaceChildren();
  page.render(root, data, name);
  drawCharts();
  runSumUpdaters();
  window.scrollTo(0, scrollY);
}
let lastRenderedPage = null;

// Building blocks -------------------------------------------------------------------
function card({ title, sub, span = 12, actions, cls = '' }, ...children) {
  return h('section', { class: 'card span-' + span + ' ' + cls },
    h('div', { class: 'card-head' }, h('h2', null, title, sub != null ? h('small', null, sub) : null), actions || null),
    ...children);
}

function hint(text) { return h('p', { class: 'hint' }, text); }

function seg(options, current, onChange) {
  return h('div', { class: 'seg', role: 'group' }, options.map((o) =>
    h('button', { type: 'button', class: o === current ? 'active' : null, onclick: () => onChange(o) }, o)));
}

function dataTable(t) {
  const align = (i) => t.align[i] || 'right';
  const table = h('table', { class: 'data' },
    h('thead', null, h('tr', null, t.columns.map((c, i) => h('th', { class: align(i) }, c)))),
    h('tbody', null, t.rows.map((row) => {
      if (row.kind === 'group') return h('tr', { class: 'row-group' }, h('td', { colspan: t.columns.length }, row.cells[0]));
      return h('tr', { class: row.kind ? 'row-' + row.kind : null }, row.cells.map((c, i) => h('td', { class: align(i) }, c)));
    })));
  const wrap = h('div', { class: 'table-wrap' }, table);
  return t.note ? h('div', null, wrap, h('p', { class: 'note' }, t.note)) : wrap;
}

// A part of a card that can be redrawn on its own (for the TJ / % buttons)
function slot(build) {
  const el = h('div', { class: 'stack' });
  const redraw = () => { el.replaceChildren(...[build(redraw)].flat()); drawCharts(); };
  redraw();
  return el;
}

// Charts ------------------------------------------------------------------------------
function chart(fig, { size = '', file = 'pySTREAM' } = {}) {
  const el = h('div', { class: 'chart ' + size });
  el._fig = fig;
  el._file = file;
  pendingCharts.push(el);
  return el;
}

function drawCharts() {
  const waiting = [];
  for (const el of pendingCharts) {
    if (el.isConnected) drawChart(el);
    else waiting.push(el); // not on the page yet: drawn when it is
  }
  pendingCharts = waiting;
}

function drawChart(el) {
  const fig = el._fig;
  const narrow = el.clientWidth < NARROW_CHART;
  const layout = JSON.parse(JSON.stringify(fig.layout));
  layout.font = Object.assign({ family: FONT, size: 12, color: '#1F2A36' }, layout.font || {});
  layout.paper_bgcolor = '#FFFFFF';
  layout.plot_bgcolor = '#F7FAFD';
  layout.autosize = true;
  layout.hoverlabel = { font: { family: FONT } };
  layout.title = Object.assign({}, layout.title, { xref: 'container', x: 0, pad: { l: 4 } });
  const hasLegend = fig.data.some((d) => d.showlegend !== false && d.type !== 'sankey' && d.type !== 'pie');
  if (narrow && hasLegend) {
    // Narrow chart: the legend goes above the plot, where it has the full width, and the card's heading
    // replaces the chart's own title, so they do not overlap
    layout.title.text = '';
    layout.margin = Object.assign({}, layout.margin, { t: 10 });
    layout.legend = Object.assign({}, layout.legend, { orientation: 'h', x: 0, xanchor: 'left', y: 1.02, yanchor: 'bottom', title: null });
  }
  el._narrow = narrow;
  Plotly.react(el, fig.data, layout, {
    responsive: true,
    displaylogo: false,
    modeBarButtonsToRemove: ['lasso2d', 'select2d', 'autoScale2d'],
    toImageButtonOptions: { format: 'png', filename: el._file, scale: 2 },
  });
}

window.addEventListener('resize', debounce(() => {
  document.querySelectorAll('.chart').forEach((el) => {
    if (el._fig && el.isConnected && (el.clientWidth < NARROW_CHART) !== el._narrow) drawChart(el);
  });
}, 250));

// Editable values -----------------------------------------------------------------------
// kind 'share': shown and typed in %, stored as a fraction. kind 'price': shown and stored as it is.
function numInput(key, original, { kind = 'share', min = 0, max = 1, what = 'Shares', col = 0, label = '' } = {}) {
  const show = (v) => (kind === 'price' ? Number(v).toFixed(2) : (v * 100).toFixed(2));
  const input = h('input', { class: 'cell-input' + (kind === 'price' ? ' price' : ''), type: 'text', inputmode: 'decimal', autocomplete: 'off',
                             'data-col': col, 'aria-label': label || key.split('|').slice(1).join(', ') });
  const setShown = () => {
    input.value = show(val(key, original));
    input.dataset.shown = input.value;
    input.classList.toggle('changed', key in state.draft);
  };
  setShown();
  const unitLabel = kind === 'price' ? (key === 'co2' ? '€/t CO2' : '€/GJ') : '%';
  const commit = () => {
    if (input.value === input.dataset.shown) return;
    const text = input.value.trim().replace(/%$/, '').trim().replace(',', '.');
    const n = text === '' ? NaN : Number(text);
    if (!Number.isFinite(n)) {
      toast('Please enter a number, for example 5.3 (in ' + unitLabel + ').', 'error');
      setShown();
      return;
    }
    const value = kind === 'price' ? n : n / 100;
    if (value < min - 1e-12 || value > max + 1e-12) {
      const range = kind === 'price'
        ? what + ' must be ' + min + ' ' + unitLabel + ' or more.'
        : what + ' must be between ' + (min * 100) + ' % and ' + (max * 100) + ' %.';
      toast(range + ' You entered: ' + input.value.trim(), 'error');
      setShown();
      return;
    }
    if (show(value) === show(original) && Math.abs(value - original) < 1e-9 + (kind === 'price' ? 0.005 : 0.00005)) delete state.draft[key];
    else state.draft[key] = value;
    setShown();
    onDraftChanged();
  };
  input.addEventListener('focus', () => input.select());
  input.addEventListener('change', commit);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      commit();
      const inputs = [...input.closest('table, .stack, .card').querySelectorAll('input[data-col="' + col + '"]')];
      const next = inputs[inputs.indexOf(input) + (e.shiftKey ? -1 : 1)];
      if (next) next.focus(); else input.blur();
    } else if (e.key === 'Escape') {
      setShown();
      input.blur();
    }
  });
  return h('span', { class: 'cell-edit' }, input, kind === 'share' ? h('span', { class: 'unit' }, '%') : null);
}

function setSumCell(cell, value) {
  cell.textContent = pct(value);
  const bad = !isHundred(value);
  cell.classList.toggle('sum-bad', bad);
  cell.title = bad ? 'Must add up to 100 %' : '';
}

// Pages -------------------------------------------------------------------------------------
function renderGraphs(root, d) {
  const key = d.charts[state.ui.graph] ? state.ui.graph : 'sankey';
  root.append(h('div', { class: 'toolbar' },
    h('div', { class: 'chips' }, d.order.map((k) => h('button', { type: 'button', class: 'chip' + (k === key ? ' active' : ''),
      onclick: () => { state.ui.graph = k; renderPage(); } }, d.charts[k].label)))));
  const size = key === 'sankey' ? 'tall' : '';
  root.append(h('div', { class: 'grid' },
    card({ title: 'Base year', sub: d.base_year, span: 6 }, chart(d.charts[key].BY, { size, file: key + '_' + d.base_year })),
    card({ title: 'Scenario year', sub: d.scenario_year, span: 6 }, chart(d.charts[key].SC, { size, file: key + '_' + d.scenario_year }))));
  root.append(hint(key === 'sankey'
    ? 'Hover over a flow to see its size; drag a node to rearrange the diagram. The camera icon above a chart saves it as a picture (PNG) for your report.'
    : 'Both years are drawn on the same scale, so they can be compared directly. Hover to see the values; the camera icon above a chart saves it as a picture (PNG).'));
}

const EDIT_HINT = 'Click a value, type a new one and press Enter. Sums and amounts update right away; changed values are yellow. '
                + 'Press "Update scenario" (top right) to calculate the results of your changes.';

function renderConsumption(root) {
  const inp = state.inputs;
  root.append(hint(EDIT_HINT));
  root.append(h('div', { class: 'grid' },
    heatCard(inp.heat), allocationCard(inp.allocation), utilisationCard(inp.utilisation),
    transportFuelsCard(inp.transport_fuels)));
}

function heatCard(heat) {
  const sumCells = {};
  const table = h('table', { class: 'data' },
    h('thead', null, h('tr', null, h('th', null, 'Technology type'), heat.sectors.map((s) => h('th', { class: 'right' }, s)))),
    h('tbody', null, heat.rows.map((row) => h('tr', null, h('td', null, row.tech, h('span', { class: 'sub' }, row.fuel)),
      heat.sectors.map((s, i) => h('td', { class: 'right' }, numInput('heat|' + row.tech + '|' + s, row.values[s], { col: i, label: row.tech + ', ' + s })))))),
    h('tfoot', null, h('tr', null, h('td', null, 'Sum'), heat.sectors.map((s) => (sumCells[s] = h('td', { class: 'right' }))))));
  sumUpdaters.push(() => {
    for (const s of heat.sectors) setSumCell(sumCells[s], sum(heat.rows.map((r) => val('heat|' + r.tech + '|' + s, r.values[s]))));
  });
  return card({ title: 'Heating', sub: 'energy consumption', span: 6, cls: 'heat-card' },
    h('p', { class: 'caption' }, 'Share of each technology in the heat demand of each sector. Each sector must add up to 100 %.'),
    h('div', { class: 'table-wrap' }, table));
}

function transportFuelsCard(tf) {
  const rowSums = [];
  const body = h('tbody');
  tf.groups.forEach((group) => {
    body.append(h('tr', { class: 'row-group' }, h('td', { colspan: tf.fuels.length + 2 }, group.name)));
    for (const row of group.rows) {
      const cell = h('td', { class: 'right' });
      rowSums.push([row, cell]);
      body.append(h('tr', null, h('td', null, row.type),
        tf.fuels.map((f, i) => h('td', { class: 'right' }, numInput('tf|' + row.type + '|' + f, row.values[f], { col: i, label: row.type + ', ' + f }))), cell));
    }
  });
  sumUpdaters.push(() => {
    for (const [row, cell] of rowSums) setSumCell(cell, sum(tf.fuels.map((f) => val('tf|' + row.type + '|' + f, row.values[f]))));
  });
  const table = h('table', { class: 'data' },
    h('thead', null, h('tr', null, h('th', null, 'Transport type'), tf.fuels.map((f) => h('th', { class: 'right' }, f)), h('th', { class: 'right' }, 'Sum'))), body);
  return card({ title: 'Transport fuels', sub: 'energy consumption', span: 12 },
    h('p', { class: 'caption' }, 'Share of each fuel in the energy use of each transport type. Each row must add up to 100 %. Bikes use no fuel.'),
    h('div', { class: 'table-wrap' }, table));
}

function workTable(groups, prefix, options) {
  return h('table', { class: 'data' },
    h('thead', null, h('tr', null, h('th', null, 'Transport type'), h('th', { class: 'right' }, '[pkm] or [tkm]'))),
    h('tbody', null, groups.map((g) => [
      h('tr', { class: 'row-group' }, h('td', { colspan: 2 }, g.name)),
      g.rows.map((r) => h('tr', null, h('td', null, r.type), h('td', { class: 'right' }, numInput(prefix + '|' + r.type, r.value, Object.assign({ label: r.type }, options))))),
    ])));
}

function allocationCard(groups) {
  const sumCells = groups.map(() => h('td', { class: 'right' }));
  const table = workTable(groups, 'alloc', {});
  table.append(h('tfoot', null, groups.map((g, i) => h('tr', null, h('td', null, g.name + ' sum'), sumCells[i]))));
  sumUpdaters.push(() => groups.forEach((g, i) => setSumCell(sumCells[i], sum(g.rows.map((r) => val('alloc|' + r.type, r.value))))));
  return card({ title: 'Allocation of transport work', span: 3 },
    h('p', { class: 'caption' }, 'How the person and goods transport is divided between the transport types. Person and goods must each add up to 100 %.'),
    h('div', { class: 'table-wrap' }, table));
}

function utilisationCard(groups) {
  return card({ title: 'Utilisation degree', span: 3 },
    h('p', { class: 'caption' }, 'How full the vehicles are on average (1 % to 100 %).'),
    h('div', { class: 'table-wrap' }, workTable(groups, 'util', { min: 0.01, what: 'The utilisation degree (how full the vehicles are on average)' })));
}

function summary(rows) {
  // rows: [label, value, value2?] ; null = separator
  const box = h('div', { class: 'summary' });
  const cells = [];
  for (const row of rows) {
    if (row === null) { box.append(h('div', { class: 'sep' })); continue; }
    const label = h('div', { class: 'label' });
    const values = row.length > 1 ? [h('div', { class: 'value' }), h('div', { class: 'value' })] : [h('div', { class: 'value wide' })];
    box.append(label, ...values);
    cells.push([label, ...values]);
  }
  return [box, cells];
}

function productionTable(rows, prefix, amountOf) {
  const amountCells = rows.map(() => h('td', { class: 'right amount' }));
  const table = h('table', { class: 'data' },
    h('thead', null, h('tr', null, h('th', null, 'Production method'), h('th', { class: 'right' }, 'Share'), h('th', { class: 'right' }, 'Amount [PJ]'))),
    h('tbody', null, rows.map((r, i) => h('tr', null, h('td', null, r.tech),
      h('td', { class: 'right' }, numInput(prefix + '|' + r.tech, r.share, { label: r.tech })), amountCells[i]))));
  sumUpdaters.push(() => rows.forEach((r, i) => { amountCells[i].textContent = fix(amountOf(val(prefix + '|' + r.tech, r.share)), 2); }));
  return h('div', { class: 'table-wrap' }, table);
}

function renderProduction(root, d) {
  const inp = state.inputs;
  root.append(hint(EDIT_HINT + ' If the shares add up to less than 100 %, the rest is imported; above 100 %, the surplus is exported.'));

  const el = inp.electricity;
  const [elSummary, elCells] = summary([['Demand coverage'], ['Electricity imports'], ['Total demand'], ['Total production']]);
  sumUpdaters.push(() => {
    const coverage = sum(el.rows.map((r) => val('el|' + r.tech, r.share)));
    const imports = 1 - coverage;
    elCells[0][0].textContent = 'Demand coverage'; elCells[0][1].textContent = pct(coverage);
    elCells[1][0].textContent = imports >= -1e-10 ? 'Electricity imports' : 'Electricity exports'; elCells[1][1].textContent = pct(Math.abs(imports));
    elCells[2][0].textContent = 'Total demand'; elCells[2][1].textContent = fix(el.total_demand, 2) + ' PJ';
    elCells[3][0].textContent = 'Total production'; elCells[3][1].textContent = fix(coverage * el.total_demand, 2) + ' PJ';
  });
  const electricity = card({ title: 'Electricity', sub: 'production', span: 4 },
    productionTable(el.rows, 'el', (share) => share * el.total_demand), elSummary);

  const dh = inp.district_heat;
  const [dhSummary, dhCells] = summary([['Heat imports', '', ''], ['Total production', '', ''], null, ['Combined heat & power (CHP)'], ['Total district heating']]);
  sumUpdaters.push(() => {
    const shares = sum(dh.rows.map((r) => val('dh|' + r.tech, r.share)));
    const imports = 1 - shares;
    dhCells[0][0].textContent = imports >= -1e-10 ? 'Heat imports' : 'Heat exports';
    dhCells[0][1].textContent = pct(Math.abs(imports)); dhCells[0][2].textContent = fix(Math.abs(imports * dh.boiler_demand), 1) + ' PJ';
    dhCells[1][0].textContent = 'Total production';
    dhCells[1][1].textContent = pct(shares); dhCells[1][2].textContent = fix(shares * dh.boiler_demand, 1) + ' PJ';
    dhCells[2][0].textContent = 'Combined heat & power (CHP)'; dhCells[2][1].textContent = fix(dh.chp, 1) + ' PJ';
    dhCells[3][0].textContent = 'Total district heating'; dhCells[3][1].textContent = fix(dh.chp + shares * dh.boiler_demand, 1) + ' PJ';
  });
  const districtHeat = card({ title: 'District heat boilers', sub: 'production', span: 4 },
    h('p', { class: 'caption' }, 'Shares of the district heat that the CHP plants do not cover (' + fix(dh.boiler_demand, 1) + ' PJ).'),
    productionTable(dh.rows, 'dh', (share) => share * dh.boiler_demand), dhSummary);

  const mix = card({ title: 'Production mix', sub: 'last update', span: 4, cls: 'production-mix' },
    h('div', { class: 'pies stack' },
      chart(d.heat_sources, { size: 'small', file: 'DH_sources' }),
      chart(d.electricity_categories, { size: 'small', file: 'electricity_categories' }),
      chart(d.heat_categories, { size: 'small', file: 'DH_categories' })));

  const resources = card({ title: 'Resources', sub: 'available & used (last update)', span: 12 },
    h('div', { class: 'inner resources' }, dataTable(d.resources_table), chart(d.resources_chart, { size: 'wide', file: 'resources' })));

  root.append(h('div', { class: 'grid' }, electricity, districtHeat, mix, resources));
}

function renderYearData(root, d, name) {
  const fec = card({ title: 'Final Energy Consumption (FEC)', span: 6 },
    chart(d.fec_chart, { size: 'short', file: 'FECstacked' + d.year }),
    slot((redraw) => {
      const unit = state.ui.fecUnit[name] || 'TJ';
      return [
        h('div', { class: 'toolbar' }, h('h3', null, unit === 'TJ' ? 'Consumption [TJ]' : 'Shares of consumption [%]'),
          seg(['TJ', '%'], unit, (u) => { state.ui.fecUnit[name] = u; redraw(); })),
        dataTable(d.fec_tables[unit]),
      ];
    }));
  const production = card({ title: 'Production', span: 6 },
    slot((redraw) => {
      const unit = state.ui.prodUnit[name] || 'PJ';
      return [
        h('div', { class: 'toolbar' }, h('h3', null, unit === 'PJ' ? 'Produced [PJ]' : 'Shares of production [%]'),
          seg(['PJ', '%'], unit, (u) => { state.ui.prodUnit[name] = u; redraw(); })),
        h('div', { class: 'inner two' },
          h('div', { class: 'stack' }, h('h3', null, 'Power'), dataTable(d.production_tables[unit].power)),
          h('div', { class: 'stack' }, h('h3', null, 'District heating'), dataTable(d.production_tables[unit].heat))),
      ];
    }),
    h('div', { class: 'inner two' },
      chart(d.power_chart, { size: 'wide', file: 'electricity_production_' + d.year }),
      chart(d.heat_chart, { size: 'wide', file: 'heat_production_' + d.year })));
  root.append(h('div', { class: 'grid' }, fec, production));
}

function renderTransport(root, d) {
  const grid = h('div', { class: 'grid' });
  for (const [key, title] of [['BY', 'Base year'], ['SC', 'Scenario']]) {
    const y = d[key];
    grid.append(card({ title, sub: y.year, span: 12 },
      h('div', { class: 'inner transport' },
        slot((redraw) => {
          const unit = state.ui.transportUnit[key] || 'TJ';
          return [h('div', { class: 'toolbar' }, h('h3', null, 'Fuel consumption ' + (unit === 'TJ' ? '[TJ]' : '[%]')),
                    seg(['TJ', '%'], unit, (u) => { state.ui.transportUnit[key] = u; redraw(); })),
                  dataTable(y.fuel_tables[unit])];
        }),
        h('div', { class: 'stack' }, h('h3', null, 'Total per fuel'), dataTable(y.totals_table)),
        chart(y.chart, { file: 'transport_fuels_' + y.year }))));
  }
  root.append(grid);
}

function renderCO2(root, d) {
  const toggle = h('input', { type: 'checkbox', checked: state.ui.showAllFuels || null,
    onchange: (e) => { state.ui.showAllFuels = e.target.checked; root.classList.toggle('hide-empty', !state.ui.showAllFuels); } });
  root.classList.toggle('hide-empty', !state.ui.showAllFuels);
  root.append(h('div', { class: 'toolbar' }, hint('CO2 emissions in million tons, per fuel and per sector. "w. CCS" includes the CO2 that is captured and stored.'),
    h('label', { class: 'check' }, toggle, 'Show fuels without emissions')));
  const grid = h('div', { class: 'grid' });
  for (const [key, title] of [['BY', 'Base year'], ['SC', 'Scenario']]) {
    const y = d[key];
    grid.append(card({ title, sub: y.year + ' · CO2 emissions [mill tons]', span: 12 },
      h('div', { class: 'inner co2' }, dataTable(y.fuel_table), dataTable(y.sector_table))));
  }
  root.append(grid);
}

function renderEconomy(root, d) {
  const inp = state.inputs;
  root.append(hint('Fuel prices and the CO2 price of the scenario can be changed; press "Update scenario" to calculate the costs again.'));
  const by = d.BY, sc = d.SC;
  const byPrices = h('div', { class: 'stack' }, h('h3', null, 'Fuel prices'), dataTable(by.prices_table),
    h('div', { class: 'inline-field' }, 'CO2 price [€/t CO2]', h('span', { class: 'value' }, fix(by.co2_price, 2))));
  const priceTable = h('table', { class: 'data' },
    h('thead', null, h('tr', null, h('th', null, 'Fuel'), h('th', { class: 'right' }, 'Price [€/GJ]'))),
    h('tbody', null, inp.prices.rows.map((r) => h('tr', null, h('td', null, r.fuel),
      h('td', { class: 'right' }, numInput('price|' + r.fuel, r.price, { kind: 'price', min: 0, max: Infinity, what: 'Prices', label: r.fuel }))))));
  const scPrices = h('div', { class: 'stack' }, h('h3', null, 'Fuel prices'), h('div', { class: 'table-wrap' }, priceTable),
    h('div', { class: 'inline-field' }, 'CO2 price [€/t CO2]',
      numInput('co2', inp.prices.co2_price, { kind: 'price', min: 0, max: Infinity, what: 'The CO2 price', col: 1, label: 'CO2 price' })));
  const costs = (y) => h('div', { class: 'stack' }, h('h3', null, 'Costs [mill. €]'), dataTable(y.costs_table), chart(y.chart, { size: 'short', file: 'costs' + y.year }));
  root.append(h('div', { class: 'grid' },
    card({ title: 'Base year', sub: by.year, span: 12 }, h('div', { class: 'inner prices' }, byPrices, costs(by))),
    card({ title: 'Scenario', sub: sc.year, span: 12 }, h('div', { class: 'inner prices' }, scPrices, costs(sc)))));
}

function renderTimeSeries(root, d) {
  const recalc = async () => {
    busy('Calculating the time series…\nThis can take up to a minute.');
    try {
      state.pageData.timeseries = await api('/api/timeseries', { method: 'POST', body: {} });
    } catch (e) {
      unbusy();
      showError(e);
      return;
    }
    unbusy();
    renderPage();
  };
  root.append(h('div', { class: 'toolbar' },
    hint('Hourly electricity production in the scenario, as it was last updated' + (changeCount() ? ' (your changes that are not calculated yet are not included)' : '') + '.'),
    h('button', { class: 'btn', type: 'button', onclick: recalc }, 'Recalculate time series')));
  root.append(h('div', { class: 'grid' },
    card({ title: 'Load duration curve', span: 8 }, chart(d.duration, { file: 'durationCurve' })),
    card({ title: 'Flexible technologies', span: 4 }, dataTable(d.flexible_table),
      h('p', { class: 'note' }, 'The technologies that cover the consumption that is left after wind, solar, wave and hydro power, in order of their running costs.')),
    card({ title: 'Average production', span: 12,
          actions: seg(['Average week', 'Average month'], state.ui.average === 'month' ? 'Average month' : 'Average week',
                       (o) => { state.ui.average = o === 'Average month' ? 'month' : 'week'; renderPage(); }) },
      chart(state.ui.average === 'month' ? d.month : d.week, { file: state.ui.average === 'month' ? 'avgMonth' : 'avgWeek' }))));
}

// Menu on small screens ------------------------------------------------------------------
function closeMenu() { $('#sidebar').classList.remove('open'); $('#scrim').classList.remove('show'); }

// Start ----------------------------------------------------------------------------------------
async function init() {
  buildNav();
  $('#menu-toggle').addEventListener('click', () => { $('#sidebar').classList.add('open'); $('#scrim').classList.add('show'); });
  $('#scrim').addEventListener('click', closeMenu);
  $('#btn-update').addEventListener('click', updateScenario);
  $('#btn-discard').addEventListener('click', discardChanges);
  $('#btn-save-as').addEventListener('click', () => { closeMenu(); saveScenarioAs(); });
  $('#btn-open').addEventListener('click', () => { closeMenu(); openScenario(); });
  $('#btn-reset').addEventListener('click', () => { closeMenu(); resetScenario(); });
  $('#btn-quit').addEventListener('click', () => { closeMenu(); closePySTREAM(); });
  $('#file-input').addEventListener('change', (e) => {
    const file = e.target.files[0];
    e.target.value = '';
    if (file) openScenarioFile(file);
  });
  const year = $('#year');
  year.addEventListener('input', () => {
    const v = year.value.trim();
    state.draftYear = v === String(state.inputs.scenario_year) ? null : v;
    onDraftChanged();
  });
  year.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); updateScenario(); } });
  window.addEventListener('beforeunload', warnBeforeLeaving);
  window.addEventListener('hashchange', () => go(location.hash.slice(1)));
  startHello();

  try {
    state.inputs = await api('/api/inputs');
  } catch (e) {
    $('#content').replaceChildren(h('div', { class: 'loading' }, 'pySTREAM could not be started.'));
    showError(e);
    return;
  }
  year.value = state.inputs.scenario_year;
  go(location.hash.slice(1));
}

init();
