// Grafik: mum + hacim, indikatörler, çizimler, alarm çizgileri, anlık fiyat
import { api } from './api.js';
import { $, el, fmtNum, fmtPct, fmtPrice, modal, store, toast, bus } from './ui.js';

const LWC = window.LightweightCharts;
const COLORS = ['#2962ff', '#ff9800', '#e91e63', '#00bcd4', '#ab47bc', '#8bc34a', '#ffeb3b', '#f06292'];
const UP = '#26a69a';
const DOWN = '#ef5350';
const MARKET_TZ = { BIST: 'Europe/Istanbul', US: 'America/New_York' };
export const TF_LABELS = { '4h': '4S', '1d': 'G', '1w': 'H', '1mo': 'A', '3mo': '3A' };

let chart;
let candle;
let volume;
let indicatorMeta = {};
let current = null; // { symbol, tf, bars }
let indicatorSeries = []; // [{ind, series: [{key, api}]}]
let drawingObjs = []; // [{id, kind, remove()}]
let alertLines = [];
let liveLine = null;
let tool = null;
let trendStart = null;
let loadSeq = 0;

let state = {
  symbolId: store.get('symbolId', null),
  tf: store.get('tf', '1d'),
  indicators: store.get('indicators', [
    { uid: 1, name: 'ema', params: { length: 20 } },
    { uid: 2, name: 'ema', params: { length: 50 } },
    { uid: 3, name: 'rsi', params: { length: 14 } },
  ]),
};

function save() {
  store.set('symbolId', state.symbolId);
  store.set('tf', state.tf);
  store.set('indicators', state.indicators);
}

export const getState = () => ({ ...state, symbol: current?.symbol, lastClose: lastClose() });

function lastClose() {
  const b = current?.bars;
  return b && b.length ? b[b.length - 1].close : null;
}

export async function initChart() {
  chart = LWC.createChart($('#chart'), {
    autoSize: true,
    layout: {
      background: { color: '#131722' },
      textColor: '#d1d4dc',
      panes: { separatorColor: '#363a45', separatorHoverColor: '#2962ff55' },
    },
    grid: { vertLines: { color: '#1c2030' }, horzLines: { color: '#1c2030' } },
    crosshair: { mode: LWC.CrosshairMode.Normal },
    rightPriceScale: { borderColor: '#363a45' },
    timeScale: { borderColor: '#363a45', timeVisible: true, secondsVisible: false, rightOffset: 6 },
    localization: { locale: 'tr-TR' },
  });
  candle = chart.addSeries(LWC.CandlestickSeries, {
    upColor: UP, downColor: DOWN, borderVisible: false, wickUpColor: UP, wickDownColor: DOWN,
  });
  candle.priceScale().applyOptions({ scaleMargins: { top: 0.06, bottom: 0.22 } });
  volume = chart.addSeries(LWC.HistogramSeries, { priceFormat: { type: 'volume' }, priceScaleId: '' });
  volume.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });

  chart.subscribeCrosshairMove(renderLegend);
  // Çizim tıklamaları doğrudan DOM'dan alınır: lightweight-charts'ın subscribeClick'i,
  // ilk tıklamadan sonraki 500 ms içinde başka noktaya yapılan tıklamayı yutuyor.
  const container = $('#chart');
  let downAt = null;
  container.addEventListener('mousedown', (e) => { downAt = [e.clientX, e.clientY]; });
  container.addEventListener('click', (e) => {
    if (downAt && Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) > 4) return; // sürükleme
    const rect = container.getBoundingClientRect();
    onChartClick(e.clientX - rect.left, e.clientY - rect.top);
  });
  indicatorMeta = await api.indicatorList();
  buildIndicatorMenu();
  buildTimeframeButtons();

  $('#tool-hline').onclick = () => setTool(tool === 'hline' ? null : 'hline');
  $('#tool-trend').onclick = () => setTool(tool === 'trend' ? null : 'trend');
  $('#tool-clear').onclick = clearDrawings;
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') setTool(null); });

  bus.on('alerts:changed', () => current && loadAlertLines());
  setInterval(refreshLive, 30000);

  if (state.symbolId) {
    await openSymbol(state.symbolId).catch(() => showEmpty());
  } else {
    showEmpty();
  }
}

function showEmpty(text) {
  const box = $('#chart-empty');
  box.textContent = text || 'Bir sembol seçin (üstteki arama kutusu veya sağdaki izleme listesi).';
  box.classList.remove('hidden');
}

// ------------------------------------------------------------- yükleme
export async function openSymbol(symbolId, tf) {
  state.symbolId = symbolId;
  if (tf) state.tf = tf;
  save();
  const seq = ++loadSeq;
  const data = await api.bars(symbolId, state.tf);
  if (seq !== loadSeq) return; // daha yeni bir istek başladı
  current = { symbol: data.symbol, tf: state.tf, bars: data.bars, live: data.live };
  $('#chart-empty').classList.toggle('hidden', data.bars.length > 0);
  if (!data.bars.length) showEmpty('Bu sembol için henüz veri yok. Geçmiş veri indiriliyor olabilir.');

  candle.setData(data.bars.map(({ time, open, high, low, close }) => ({ time, open, high, low, close })));
  volume.setData(data.bars.map((b) => ({
    time: b.time, value: b.volume, color: b.close >= b.open ? `${UP}66` : `${DOWN}66`,
  })));
  const precision = data.bars.length && data.bars[data.bars.length - 1].close < 10 ? 4 : 2;
  candle.applyOptions({ priceFormat: { type: 'price', precision, minMove: 1 / 10 ** precision } });
  applyLive(data.live);
  chart.timeScale().applyOptions({ timeVisible: state.tf === '4h' });
  chart.timeScale().setVisibleLogicalRange({
    from: Math.max(0, data.bars.length - visibleBars()), to: data.bars.length + 5,
  });
  updateTfButtons();
  await Promise.all([renderIndicators(), loadDrawings(), loadAlertLines()]);
  renderLegend();
  bus.emit('symbol:changed', current.symbol);
}

function visibleBars() {
  return { '4h': 180, '1d': 160, '1w': 150, '1mo': 120, '3mo': 80 }[state.tf] || 150;
}

export function setTimeframe(tf) {
  if (!state.symbolId) { state.tf = tf; save(); updateTfButtons(); return; }
  openSymbol(state.symbolId, tf).catch((e) => toast(e.message, true));
}

function buildTimeframeButtons() {
  const box = $('#tf-buttons');
  for (const [tf, label] of Object.entries(TF_LABELS)) {
    box.append(el('button', { class: 'btn', dataset: { tf }, title: tf, onclick: () => setTimeframe(tf) }, label));
  }
  updateTfButtons();
}

function updateTfButtons() {
  for (const b of $('#tf-buttons').children) b.classList.toggle('active', b.dataset.tf === state.tf);
}

// ------------------------------------------------------- anlık fiyat
function marketDate(iso, market) {
  return new Intl.DateTimeFormat('en-CA', { timeZone: MARKET_TZ[market] }).format(new Date(iso));
}

function periodStart(day, tf) {
  const [y, m, d] = day.split('-').map(Number);
  const pad = (n) => String(n).padStart(2, '0');
  if (tf === '1d') return day;
  if (tf === '1mo') return `${y}-${pad(m)}-01`;
  if (tf === '3mo') return `${y}-${pad(Math.floor((m - 1) / 3) * 3 + 1)}-01`;
  const dt = new Date(Date.UTC(y, m - 1, d));
  dt.setUTCDate(dt.getUTCDate() - ((dt.getUTCDay() + 6) % 7)); // pazartesi
  return dt.toISOString().slice(0, 10);
}

function applyLive(q) {
  if (liveLine) { candle.removePriceLine(liveLine); liveLine = null; }
  if (!q || !current || !current.bars.length) return;
  current.live = q;
  if (current.tf === '4h') {
    liveLine = candle.createPriceLine({
      price: q.price, color: '#ffeb3b', lineWidth: 1, lineStyle: LWC.LineStyle.Dotted, title: 'Anlık',
    });
    return;
  }
  const bars = current.bars;
  const last = bars[bars.length - 1];
  const day = marketDate(q.fetched_at, current.symbol.market);
  const t = periodStart(day, current.tf);
  if (t < last.time) return; // eski fiyat
  if (t === last.time) {
    candle.update({
      time: t, open: last.open, close: q.price,
      high: Math.max(last.high, q.price), low: Math.min(last.low, q.price),
    });
  } else {
    const open = q.open ?? q.price;
    candle.update({
      time: t, open, close: q.price,
      high: Math.max(q.high ?? q.price, q.price, open), low: Math.min(q.low ?? q.price, q.price, open),
    });
  }
}

async function refreshLive() {
  if (!current) return;
  try {
    const s = await api.symbol(current.symbol.id);
    if (s.quote && (!current.live || s.quote.fetched_at !== current.live.fetched_at)) {
      applyLive(s.quote);
      renderLegend();
    }
  } catch { /* geçici hata */ }
}

// ------------------------------------------------------------ indikatörler
function buildIndicatorMenu() {
  const menu = $('#indicator-menu');
  for (const [name, meta] of Object.entries(indicatorMeta)) {
    menu.append(el('button', { onclick: () => { menu.classList.add('hidden'); addIndicator(name); } },
      meta.label, el('small', { class: 'muted' }, meta.pane === 'overlay' ? ' · fiyat üstü' : ' · ayrı panel')));
  }
  $('#btn-indicators').onclick = (e) => { e.stopPropagation(); menu.classList.toggle('hidden'); };
  document.addEventListener('click', (e) => { if (!menu.contains(e.target)) menu.classList.add('hidden'); });
}

async function addIndicator(name) {
  const params = await editParams(name, indicatorMeta[name].params);
  if (!params) return;
  const uid = Math.max(0, ...state.indicators.map((i) => i.uid)) + 1;
  state.indicators.push({ uid, name, params });
  save();
  await renderIndicators();
  renderLegend();
}

async function editParams(name, params) {
  const keys = Object.keys(params);
  if (!keys.length) return {};
  const res = await modal(`${indicatorMeta[name].label} ayarları`,
    keys.map((k) => ({ name: k, label: k, type: 'number', value: params[k] })));
  if (!res) return null;
  for (const k of keys) if (Number.isNaN(res[k])) res[k] = params[k];
  return res;
}

function indicatorTitle(ind) {
  const vals = Object.values(ind.params);
  return `${indicatorMeta[ind.name]?.label || ind.name}${vals.length ? ` (${vals.join(', ')})` : ''}`;
}

async function renderIndicators() {
  for (const { series } of indicatorSeries) for (const s of series) chart.removeSeries(s.api);
  indicatorSeries = [];
  while (chart.panes().length > 1) chart.removePane(chart.panes().length - 1);
  if (!current) return;

  const { symbol, tf } = current;
  const results = await Promise.all(state.indicators.map((ind) =>
    api.indicator(symbol.id, tf, ind.name, ind.params).catch((e) => ({ error: e.message }))));
  if (!current || current.symbol.id !== symbol.id || current.tf !== tf) return;

  let pane = 0;
  let colorIdx = 0;
  const nextColor = () => COLORS[colorIdx++ % COLORS.length];
  state.indicators.forEach((ind, i) => {
    const res = results[i];
    if (res.error) { toast(`${indicatorTitle(ind)}: ${res.error}`, true); return; }
    const meta = indicatorMeta[ind.name];
    const paneIdx = meta.pane === 'overlay' ? 0 : ++pane;
    const series = [];
    const line = (key, data, opts = {}) => {
      const s = chart.addSeries(LWC.LineSeries, {
        color: nextColor(), lineWidth: 1.5, priceLineVisible: false, lastValueVisible: true,
        crosshairMarkerVisible: false, ...opts,
      }, paneIdx);
      s.setData(data);
      series.push({ key, api: s });
      return s;
    };

    if (ind.name === 'supertrend') {
      const dir = new Map(res.outputs.dir.map((p) => [p.time, p.value]));
      line('supertrend', res.outputs.supertrend.map((p) => ({ ...p, color: dir.get(p.time) > 0 ? UP : DOWN })),
        { lineWidth: 2 });
    } else if (ind.name === 'macd') {
      const h = chart.addSeries(LWC.HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, paneIdx);
      h.setData(res.outputs.hist.map((p) => ({ ...p, color: p.value >= 0 ? `${UP}aa` : `${DOWN}aa` })));
      series.push({ key: 'hist', api: h });
      line('macd', res.outputs.macd, { color: '#2962ff' });
      line('signal', res.outputs.signal, { color: '#ff9800' });
    } else if (ind.name === 'bb') {
      const c = nextColor();
      line('upper', res.outputs.upper, { color: c, lineWidth: 1 });
      line('middle', res.outputs.middle, { color: `${c}99`, lineWidth: 1, lineStyle: LWC.LineStyle.Dashed });
      line('lower', res.outputs.lower, { color: c, lineWidth: 1 });
    } else if (ind.name === 'adx') {
      line('adx', res.outputs.adx, { color: '#ff9800', lineWidth: 2 });
      line('+DI', res.outputs.plus_di, { color: UP, lineWidth: 1 });
      line('-DI', res.outputs.minus_di, { color: DOWN, lineWidth: 1 });
    } else {
      for (const [key, data] of Object.entries(res.outputs)) line(key, data);
    }
    if (meta.levels && series.length) {
      for (const lvl of meta.levels) {
        series[0].api.createPriceLine({
          price: lvl, color: '#787b86', lineWidth: 1, lineStyle: LWC.LineStyle.Dashed, axisLabelVisible: false,
        });
      }
    }
    indicatorSeries.push({ ind, series });
  });

  const panes = chart.panes();
  panes[0].setStretchFactor(panes.length > 1 ? 3 : 1);
  for (let i = 1; i < panes.length; i++) panes[i].setStretchFactor(1);
}

// ------------------------------------------------------------------ legend
function renderLegend(param) {
  const box = $('#legend');
  if (!current) { box.replaceChildren(); return; }
  const { symbol } = current;
  let bar = param?.seriesData?.get(candle);
  if (!bar) {
    const data = candle.data();
    bar = data[data.length - 1];
  }
  const idx = bar ? candle.data().findIndex((b) => b.time === bar.time) : -1;
  const prev = idx > 0 ? candle.data()[idx - 1] : null;
  const chg = bar && prev ? (bar.close / prev.close - 1) * 100 : null;
  const vol = bar ? (param?.seriesData?.get(volume)?.value ?? current.bars.find((b) => b.time === bar.time)?.volume) : null;
  const cls = chg > 0 ? 'up' : chg < 0 ? 'down' : '';

  const live = current.live;
  const liveText = live ? ` · anlık ${fmtPrice(live.price)} (${fmtPct(live.change_pct)})` : '';
  const rows = [
    el('div', { class: 'title' }, `${symbol.ticker} `,
      el('span', { class: 'muted' }, `${symbol.name || ''} · ${symbol.exchange} · ${TF_LABELS[current.tf]}${liveText}`)),
    bar ? el('div', { class: cls },
      `A ${fmtPrice(bar.open)}  Y ${fmtPrice(bar.high)}  D ${fmtPrice(bar.low)}  K ${fmtPrice(bar.close)}  `,
      `${fmtPct(chg)}  Hacim ${fmtNum(vol)}`) : null,
  ];
  const inds = el('div');
  for (const { ind, series } of indicatorSeries) {
    const vals = series
      .map((s) => param?.seriesData?.get(s.api)?.value ?? s.api.data().at(-1)?.value)
      .filter((v) => v !== undefined)
      .map((v) => fmtPrice(v)).join(' / ');
    inds.append(el('span', { class: 'ind' }, `${indicatorTitle(ind)} `, el('span', { class: 'muted' }, vals),
      el('button', { title: 'Ayarlar', onclick: () => editIndicator(ind.uid) }, '⚙'),
      el('button', { title: 'Kaldır', onclick: () => removeIndicator(ind.uid) }, '×')));
  }
  rows.push(inds);
  box.replaceChildren(...rows.filter(Boolean));
}

async function editIndicator(uid) {
  const ind = state.indicators.find((i) => i.uid === uid);
  const params = await editParams(ind.name, ind.params);
  if (!params) return;
  ind.params = params;
  save();
  await renderIndicators();
  renderLegend();
}

async function removeIndicator(uid) {
  state.indicators = state.indicators.filter((i) => i.uid !== uid);
  save();
  await renderIndicators();
  renderLegend();
}

// ---------------------------------------------------------------- çizimler
function setTool(t) {
  tool = t;
  trendStart = null;
  $('#tool-hline').classList.toggle('active', t === 'hline');
  $('#tool-trend').classList.toggle('active', t === 'trend');
  $('#chart').classList.toggle('drawing', !!t);
}

async function onChartClick(x, y) {
  if (!tool || !current) return;
  if (y > chart.panes()[0].getHeight()) return; // yalnızca fiyat paneli
  const price = candle.coordinateToPrice(y);
  const time = chart.timeScale().coordinateToTime(x) ?? undefined;
  if (price === null) return;
  const param = { time };
  try {
    if (tool === 'hline') {
      const d = await api.createDrawing({ symbol_id: current.symbol.id, kind: 'hline', data: { price } });
      addDrawing(d);
      setTool(null);
    } else if (tool === 'trend') {
      if (param.time === undefined) { toast('Trend çizgisi için bir barın üzerine tıklayın'); return; }
      if (!trendStart) { trendStart = { time: param.time, price }; toast('İkinci noktaya tıklayın'); return; }
      if (trendStart.time === param.time) return;
      const d = await api.createDrawing({
        symbol_id: current.symbol.id, kind: 'trendline',
        data: { tf: current.tf, p1: trendStart, p2: { time: param.time, price } },
      });
      addDrawing(d);
      setTool(null);
    }
  } catch (e) { toast(e.message, true); }
}

function addDrawing(d) {
  if (d.kind === 'hline') {
    const line = candle.createPriceLine({
      price: d.data.price, color: '#4fc3f7', lineWidth: 1, lineStyle: LWC.LineStyle.Solid, axisLabelVisible: true,
    });
    drawingObjs.push({ id: d.id, remove: () => candle.removePriceLine(line) });
  } else if (d.kind === 'trendline') {
    if (d.data.tf !== current.tf) return; // trend çizgileri çizildiği periyotta görünür
    const pts = [d.data.p1, d.data.p2].sort((a, b) => (a.time < b.time ? -1 : 1));
    const s = chart.addSeries(LWC.LineSeries, {
      color: '#4fc3f7', lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    }, 0);
    s.setData(pts.map((p) => ({ time: p.time, value: p.price })));
    drawingObjs.push({ id: d.id, remove: () => chart.removeSeries(s) });
  }
}

async function loadDrawings() {
  drawingObjs.forEach((o) => o.remove());
  drawingObjs = [];
  if (!current) return;
  const list = await api.drawings(current.symbol.id).catch(() => []);
  list.forEach(addDrawing);
}

async function clearDrawings() {
  if (!current || !drawingObjs.length) return;
  const ok = await modal(`${current.symbol.ticker} için tüm çizimler silinsin mi?`, [], { okText: 'Sil' });
  if (!ok) return;
  const all = await api.drawings(current.symbol.id);
  await Promise.all(all.map((d) => api.deleteDrawing(d.id)));
  await loadDrawings();
}

async function loadAlertLines() {
  alertLines.forEach((l) => candle.removePriceLine(l));
  alertLines = [];
  if (!current) return;
  const alerts = await api.alerts().catch(() => []);
  for (const a of alerts) {
    if (a.kind !== 'price' || !a.active || a.symbol_id !== current.symbol.id) continue;
    alertLines.push(candle.createPriceLine({
      price: a.value, color: '#ff9800', lineWidth: 1, lineStyle: LWC.LineStyle.Dashed,
      title: a.operator === 'cross_up' ? '⏰↑' : '⏰↓',
    }));
  }
}
