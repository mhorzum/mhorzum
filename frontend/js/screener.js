// Tarayıcı ve kayıtlı taramalar
import { api } from './api.js';
import { openSymbol, TF_LABELS } from './chart.js';
import { addSymbol, getLists } from './watchlist.js';
import { $, el, fmtNum, fmtPct, fmtPrice, fmtTime, modal, pctClass, store, toast, bus } from './ui.js';

const PRESETS = [
  ['', 'Hazır taramalar…'],
  ['rsi14 < 30', 'RSI aşırı satım (< 30)'],
  ['rsi14 > 70', 'RSI aşırı alım (> 70)'],
  ['cross_up(sma50, sma200)', 'Altın kesişim (SMA50 ↑ SMA200)'],
  ['cross_down(sma50, sma200)', 'Ölüm kesişimi (SMA50 ↓ SMA200)'],
  ['cross_up(macd, macd_signal) and macd < 0', 'MACD sıfır altı al kesişimi'],
  ['close > prev(hh20) and rel_volume > 1.5', '20 bar zirve kırılımı + hacim'],
  ['st_dir == 1 and prev(st_dir) == -1', 'SuperTrend al sinyali'],
  ['close >= high_52w * 0.97', '52 hafta zirvesine %3 yakın'],
  ['close > ema20 and ema20 > ema50 and ema50 > sma200', 'Güçlü trend dizilimi'],
  ['bb_width < 6 and adx14 < 20', 'Bollinger sıkışması'],
  ['cross_up(close, bb_lower) or (prev(close) < prev(bb_lower) and close > bb_lower)', 'Bollinger alt banttan dönüş'],
  ['change_pct > 5 and rel_volume > 2', 'Hacimli yükseliş (> %5)'],
];

const INDEXES = ['XU030', 'XU100', 'SPX', 'NDX'];
let fields = {};
let lastResult = null;
let editingScanId = null;
let sortState = { key: null, desc: true };

export async function initScreener() {
  const info = await api.screenerFields();
  fields = info.fields;

  const f = store.get('screener', { expression: 'rsi14 < 30', timeframe: '1d', bist: true, us: true, indexes: [] });
  $('#scr-expr').value = f.expression;
  $('#scr-tf').replaceChildren(...Object.entries(TF_LABELS).map(([tf, l]) =>
    el('option', { value: tf, selected: tf === f.timeframe }, `${l} (${tf})`)));
  $('#scr-bist').checked = f.bist;
  $('#scr-us').checked = f.us;
  $('#scr-indexes').replaceChildren(...INDEXES.map((ix) =>
    el('button', { class: `chip${f.indexes.includes(ix) ? ' on' : ''}`, dataset: { ix },
      onclick: (e) => e.currentTarget.classList.toggle('on') }, ix)));
  $('#scr-sort').replaceChildren(el('option', { value: '' }, 'Değişim %'),
    ...Object.keys(fields).map((k) => el('option', { value: k }, k)));
  $('#scr-presets').replaceChildren(...PRESETS.map(([v, l]) => el('option', { value: v }, l)));
  $('#scr-presets').onchange = (e) => { if (e.target.value) { $('#scr-expr').value = e.target.value; run(); } };

  const help = $('#scr-help-box');
  help.replaceChildren(
    el('div', {}, el('b', {}, 'Fonksiyonlar')),
    ...Object.entries(info.functions).map(([, d]) => el('div', {}, el('code', {}, d))),
    el('div', {}, el('b', {}, 'Bağlaçlar: '), el('code', {}, 'and / ve, or / veya, not, < <= > >= == !=, + - * /')),
    el('div', {}, el('b', {}, 'Alanlar')),
    ...Object.entries(fields).map(([k, d]) => el('div', {}, el('code', {}, k), ` – ${d}`)),
  );
  $('#scr-help').onclick = () => help.classList.toggle('hidden');
  $('#scr-run').onclick = run;
  $('#scr-expr').onkeydown = (e) => { if (e.key === 'Enter') run(); };
  $('#scr-save').onclick = saveScan;

  bus.on('watchlists:changed', (lists) => {
    const sel = $('#scr-watchlist');
    const v = sel.value;
    sel.replaceChildren(el('option', { value: '' }, 'Tümü'),
      ...lists.map((l) => el('option', { value: l.id, selected: String(l.id) === v }, l.name)));
  });
  await loadScans();
}

function formBody() {
  const markets = [];
  if ($('#scr-bist').checked) markets.push('BIST');
  if ($('#scr-us').checked) markets.push('US');
  return {
    expression: $('#scr-expr').value,
    timeframe: $('#scr-tf').value,
    markets,
    indexes: [...document.querySelectorAll('#scr-indexes .chip.on')].map((c) => c.dataset.ix),
    watchlist_id: $('#scr-watchlist').value ? Number($('#scr-watchlist').value) : null,
    sort_by: $('#scr-sort').value || null,
  };
}

async function run() {
  const body = formBody();
  store.set('screener', {
    expression: body.expression, timeframe: body.timeframe, bist: body.markets.includes('BIST'),
    us: body.markets.includes('US'), indexes: body.indexes,
  });
  const msg = $('#scr-msg');
  msg.className = 'msg';
  msg.textContent = 'Taranıyor…';
  try {
    const res = await api.runScreen(body);
    showResult(res);
  } catch (e) {
    msg.className = 'msg err';
    msg.textContent = e.message;
  }
}

function showResult(res, title) {
  lastResult = res;
  sortState = { key: null, desc: true };
  $('#scr-msg').className = 'msg';
  $('#scr-msg').replaceChildren(
    `${title ? `${title}: ` : ''}${res.count} eşleşme / ${res.scanned} sembol tarandı (${TF_LABELS[res.timeframe]}). `,
    res.rows.length ? el('a', { href: '#', onclick: (e) => { e.preventDefault(); addAllToList(); } }, 'Sonuçları izleme listesine ekle') : '',
  );
  renderTable();
}

function renderTable() {
  const res = lastResult;
  const table = $('#scr-table');
  if (!res) { table.replaceChildren(); return; }
  const cols = res.columns;
  const rows = [...res.rows];
  if (sortState.key) {
    const get = (r) => (sortState.key === 'ticker' ? r.ticker : r.values[sortState.key]);
    rows.sort((a, b) => {
      const va = get(a); const vb = get(b);
      if (va === vb) return 0;
      if (va === null || va === undefined) return 1;
      if (vb === null || vb === undefined) return -1;
      return (va < vb ? -1 : 1) * (sortState.desc ? -1 : 1);
    });
  }
  const th = (key, label, cls) => el('th', {
    class: cls, title: fields[key] || '',
    onclick: () => { sortState = { key, desc: sortState.key === key ? !sortState.desc : true }; renderTable(); },
  }, label + (sortState.key === key ? (sortState.desc ? ' ▾' : ' ▴') : ''));
  table.replaceChildren(
    el('thead', {}, el('tr', {}, th('ticker', 'Sembol', 'l'), el('th', { class: 'l' }, 'Ad'),
      el('th', {}, 'Anlık'),
      ...cols.map((c) => th(c, c)))),
    el('tbody', {}, rows.map((r) => el('tr', { onclick: () => openSymbol(r.symbol_id).catch((e) => toast(e.message, true)) },
      el('td', {}, el('b', {}, r.ticker), el('span', { class: 'muted' }, ` ${r.market === 'BIST' ? 'BIST' : r.exchange}`)),
      el('td', { class: 'l muted' }, (r.name || '').slice(0, 32)),
      el('td', { class: pctClass(r.live_change_pct) }, r.live_price !== null ? `${fmtPrice(r.live_price)} (${fmtPct(r.live_change_pct)})` : '–'),
      ...cols.map((c) => {
        const v = r.values[c];
        if (c === 'change_pct' || c.startsWith('perf_')) return el('td', { class: pctClass(v) }, fmtPct(v));
        if (c.includes('volume') || c === 'obv' || c === 'vol_sma20') return el('td', {}, fmtNum(v));
        return el('td', {}, fmtPrice(v));
      })))),
  );
}

async function addAllToList() {
  const lists = getLists();
  const res = await modal('Sonuçları listeye ekle', [
    { name: 'list', label: 'İzleme listesi', type: 'select', options: lists.map((l) => [l.id, l.name]) },
  ]);
  if (!res) return;
  for (const r of lastResult.rows) await api.addToWatchlist(Number(res.list), r.symbol_id);
  await addSymbol(lastResult.rows[0].symbol_id, Number(res.list)); // listeyi yenile
  toast(`${lastResult.rows.length} sembol eklendi`);
}

// --------------------------------------------------------- kayıtlı taramalar
const SCHEDULES = [
  ['after_close', 'Gün sonu (borsa kapanışından sonra)'],
  ['manual', 'Sadece elle'],
  ['0 10 * * 1-5', 'Hafta içi 10:00'],
  ['30 9 * * 1-5', 'Hafta içi 09:30'],
  ['0 19 * * 1-5', 'Hafta içi 19:00'],
  ['0 */2 * * 1-5', 'Hafta içi 2 saatte bir'],
];

async function saveScan() {
  const body = formBody();
  const existing = editingScanId ? (await api.scans()).find((s) => s.id === editingScanId) : null;
  const schedOpts = [...SCHEDULES];
  if (existing && !schedOpts.some(([v]) => v === existing.schedule)) schedOpts.push([existing.schedule, existing.schedule]);
  const res = await modal(existing ? 'Taramayı güncelle' : 'Taramayı kaydet', [
    { name: 'name', label: 'Ad', value: existing?.name || '' },
    { name: 'schedule', label: 'Zamanlama', type: 'select', options: schedOpts, value: existing?.schedule || 'after_close' },
    { name: 'cron', label: 'veya özel cron (dk saat gün ay haftagünü, İstanbul saati)', value: '' },
    { name: 'notify', label: 'Yeni eşleşmelerde bildirim gönder', type: 'checkbox', value: existing ? existing.notify : true },
  ]);
  if (!res?.name) return;
  const payload = { ...body, name: res.name, schedule: res.cron.trim() || res.schedule, notify: res.notify, active: true };
  try {
    if (existing) await api.updateScan(existing.id, payload);
    else await api.createScan(payload);
    editingScanId = null;
    $('#scr-save').textContent = 'Tarama olarak kaydet';
    toast('Tarama kaydedildi');
    await loadScans();
  } catch (e) { toast(e.message, true); }
}

export async function loadScans() {
  const scans = await api.scans();
  const table = $('#scans-table');
  const schedText = (s) => SCHEDULES.find(([v]) => v === s)?.[1] || `cron: ${s}`;
  table.replaceChildren(
    el('thead', {}, el('tr', {}, ...['Ad', 'İfade', 'Periyot', 'Borsa', 'Zamanlama', 'Son çalışma', 'Eşleşme', ''].map((h, i) =>
      el('th', { class: i < 2 ? 'l' : '' }, h)))),
    el('tbody', {}, scans.map((s) => el('tr', {},
      el('td', { class: 'l' }, el('b', {}, s.name), s.active ? '' : el('span', { class: 'muted' }, ' (pasif)')),
      el('td', { class: 'expr-cell', title: s.expression }, s.expression),
      el('td', {}, TF_LABELS[s.timeframe]),
      el('td', {}, [...s.markets.map((m) => (m === 'US' ? 'ABD' : m)), ...s.indexes].join(', ')),
      el('td', {}, schedText(s.schedule)),
      el('td', {}, fmtTime(s.last_run_at)),
      el('td', {}, s.last_count ?? '–', s.last_new?.length ? el('span', { class: 'up' }, ` (+${s.last_new.length} yeni)`) : ''),
      el('td', {},
        el('button', { class: 'btn', onclick: () => runSaved(s) }, 'Çalıştır'), ' ',
        el('button', { class: 'btn', onclick: () => editScan(s) }, 'Düzenle'), ' ',
        el('button', { class: 'btn', onclick: () => history(s) }, 'Geçmiş'), ' ',
        el('button', { class: 'btn', onclick: () => toggleScan(s) }, s.active ? 'Durdur' : 'Başlat'), ' ',
        el('button', { class: 'btn', onclick: () => removeScan(s) }, 'Sil')),
    ))),
  );
  if (!scans.length) {
    table.append(el('tbody', {}, el('tr', {}, el('td', { class: 'l muted', colspan: 8 },
      'Kayıtlı tarama yok. Tarayıcı sekmesinde bir ifade yazıp "Tarama olarak kaydet" deyin.'))));
  }
}

async function runSaved(s) {
  try {
    const res = await api.runScan(s.id);
    document.querySelector('.tab[data-tab="screener"]').click();
    showResult(res, s.name);
    await loadScans();
  } catch (e) { toast(e.message, true); }
}

function editScan(s) {
  $('#scr-expr').value = s.expression;
  $('#scr-tf').value = s.timeframe;
  $('#scr-bist').checked = s.markets.includes('BIST');
  $('#scr-us').checked = s.markets.includes('US');
  for (const c of document.querySelectorAll('#scr-indexes .chip')) c.classList.toggle('on', s.indexes.includes(c.dataset.ix));
  $('#scr-watchlist').value = s.watchlist_id || '';
  $('#scr-sort').value = s.sort_by || '';
  editingScanId = s.id;
  $('#scr-save').textContent = `"${s.name}" taramasını güncelle`;
  document.querySelector('.tab[data-tab="screener"]').click();
}

async function toggleScan(s) {
  await api.updateScan(s.id, { ...s, active: !s.active });
  await loadScans();
}

async function removeScan(s) {
  const ok = await modal(`"${s.name}" taraması silinsin mi?`, [], { okText: 'Sil' });
  if (!ok) return;
  await api.deleteScan(s.id);
  await loadScans();
}

async function history(s) {
  const runs = await api.scanResults(s.id);
  const body = el('table', { class: 'grid' },
    el('thead', {}, el('tr', {}, el('th', { class: 'l' }, 'Zaman'), el('th', {}, 'Eşleşme'), el('th', { class: 'l' }, 'Yeni'))),
    el('tbody', {}, runs.map((r) => el('tr', {},
      el('td', { class: 'l' }, fmtTime(r.run_at)),
      el('td', {}, r.match_count),
      el('td', { class: 'l' }, r.new_matches.map((t) => t.split(':')[1]).join(', ') || '–')))));
  await modal(`${s.name} – son çalıştırmalar`, [], { okText: null, body });
}
